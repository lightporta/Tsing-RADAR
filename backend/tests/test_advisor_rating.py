"""学生评价体系 M1：schema 校验、贝叶斯聚合、提交闭环与合同测试。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.main import app
from app.models.advisor_rating import AdvisorRating, AdvisorRatingSummary
from app.models.artifact_audit import ArtifactAuditEvent
from app.schemas.advisor_rating import RatingSubmitRequest
from app.services.advisor_rating import (
    _bayesian_aggregate,
    get_summary,
    refresh_summary,
    submit_rating,
)
from app.services.constants import TRAIT_KEYS

# =====================================================================
# 夹具与工具
# =====================================================================


@pytest.fixture(autouse=True)
def isolate_rating_records():
    """评分表按测试隔离，防止跨用例泄漏（幂等记录用唯一键天然隔离）。"""
    yield
    with SessionLocal() as db:
        db.query(AdvisorRatingSummary).delete(synchronize_session=False)
        db.query(AdvisorRating).delete(synchronize_session=False)
        db.query(ArtifactAuditEvent).filter(
            ArtifactAuditEvent.event_type == "advisor_rating_submitted"
        ).delete(synchronize_session=False)
        db.commit()


def _web_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    response = client.get("/api/session")
    assert response.status_code == 200
    return client, {"X-CSRF-Token": client.cookies["tsing_radar_csrf"]}


def _idem(headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or f"rating:{uuid.uuid4()}"}


def _scores(value: int = 4) -> dict[str, int]:
    return {key: value for key in TRAIT_KEYS}


def _post_rating(
    client: TestClient,
    headers: dict[str, str],
    advisor_id: str,
    *,
    value: int = 4,
    key: str | None = None,
):
    return client.post(
        f"/api/advisors/{advisor_id}/ratings",
        headers=_idem(headers, key),
        json={"scores": _scores(value), "period_in_group": "0.5-2y"},
    )


# =====================================================================
# 3.3 Schema 校验
# =====================================================================


def test_schema_rejects_missing_dimension_key():
    """六键不全必须拒绝。"""
    with pytest.raises(ValidationError, match="六维键"):
        RatingSubmitRequest(scores={"acumen": 5})


def test_schema_rejects_out_of_range_value():
    """值越界（0 / 6）必须拒绝。"""
    with pytest.raises(ValidationError, match="1-5"):
        RatingSubmitRequest(scores={**_scores(3), "acumen": 0})
    with pytest.raises(ValidationError, match="1-5"):
        RatingSubmitRequest(scores={**_scores(3), "funding": 6})


def test_schema_accepts_valid_scores():
    """六键齐全、值在 1-5 内正常通过；多余字段拒绝。"""
    request = RatingSubmitRequest(
        scores=_scores(5), period_in_group="2y+"
    )
    assert request.scores["mentorship"] == 5
    assert request.period_in_group == "2y+"
    with pytest.raises(ValidationError):
        RatingSubmitRequest(scores=_scores(5), evidence="M1 不开放文字")


# =====================================================================
# 3.4 贝叶斯聚合
# =====================================================================


def test_bayesian_single_score_shrinks_toward_prior():
    """单条满分 5 应向先验 3.0 收缩：(15+5)/6 ≈ 3.333。"""
    value, n = _bayesian_aggregate([(5, False)])
    assert n == 1
    assert value == 3.333
    assert value < 5


def test_bayesian_single_low_score_shrinks_upward():
    """单条低分 1 同样向 3.0 收缩：(15+1)/6 ≈ 2.667。"""
    value, _ = _bayesian_aggregate([(1, False)])
    assert value == 2.667
    assert value > 1


def test_bayesian_multi_scores_converge_to_mean():
    """多条评分收敛到真实均值：10 条 5 分 → (15+50)/15 ≈ 4.333。"""
    value, n = _bayesian_aggregate([(5, False)] * 10)
    assert n == 10
    assert value == 4.333
    # 样本越多越接近真实均值 5
    assert value > _bayesian_aggregate([(5, False)] * 2)[0]


def test_refresh_summary_upserts_materialized_row():
    """refresh_summary：approved 评分重算后物化表值正确，pending 不计入。"""
    with SessionLocal() as db:
        submit_rating(
            db,
            advisor_id="ADV_SVC_1",
            rater_principal="usr_a",
            scores=_scores(4),
            period_in_group=None,
        )
        submit_rating(
            db,
            advisor_id="ADV_SVC_1",
            rater_principal="usr_b",
            scores=_scores(2),
            period_in_group=None,
        )
        # evidence 非空 → pending_review，不参与聚合（M2 预留通路）
        submit_rating(
            db,
            advisor_id="ADV_SVC_1",
            rater_principal="usr_c",
            scores=_scores(1),
            period_in_group=None,
            evidence="待审核文字",
        )
        db.commit()

        row = db.get(AdvisorRatingSummary, "ADV_SVC_1")
        assert row is not None
        # (15 + 4 + 2) / 7 = 3.0
        assert row.acumen_value == 3.0
        assert row.acumen_n == 2
        assert row.last_collected_at is not None

        summary = get_summary(db, "ADV_SVC_1")
        assert summary is not None
        assert summary["total_n"] == 2
        assert summary["dimensions"]["funding"] == {"value": 3.0, "n": 2}
        assert summary["last_collected_at"] is not None

        pending = (
            db.query(AdvisorRating)
            .filter(AdvisorRating.rater_principal == "usr_c")
            .one()
        )
        assert pending.review_status == "pending_review"

        # 物化行可幂等重算（upsert 不报错、值不变）
        refresh_summary(db, "ADV_SVC_1")
        db.commit()
        assert db.get(AdvisorRatingSummary, "ADV_SVC_1").acumen_n == 2


# =====================================================================
# 3.5 API 闭环与合同测试
# =====================================================================


def test_submit_aggregate_summary_closed_loop():
    """提交 → 聚合 → summary 读取闭环。"""
    client, headers = _web_client()
    created = _post_rating(client, headers, "ADV_LOOP_1", value=4)
    assert created.status_code == 200
    body = created.json()
    assert body["advisor_id"] == "ADV_LOOP_1"
    assert body["review_status"] == "approved"
    assert body["rating_id"]

    summary_resp = client.get("/api/advisors/ADV_LOOP_1/ratings/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total_n"] == 1
    # (15+4)/6 ≈ 3.167
    assert summary["dimensions"]["acumen"] == {"value": 3.167, "n": 1}
    assert summary["last_collected_at"] is not None

    # 脱敏列表：不暴露打分人、不返回单人分数
    listed = client.get("/api/advisors/ADV_LOOP_1/ratings")
    assert listed.status_code == 200
    items = listed.json()["data"]
    assert len(items) == 1
    assert items[0]["period_in_group"] == "0.5-2y"
    assert items[0]["rater_verified"] is False
    assert "rater_principal" not in items[0]
    assert "scores" not in items[0]

    mine = client.get("/api/ratings/mine")
    assert mine.status_code == 200
    mine_items = mine.json()["data"]
    assert len(mine_items) == 1
    assert mine_items[0]["advisor_id"] == "ADV_LOOP_1"
    assert mine_items[0]["scores"] == _scores(4)


def test_idempotent_replay_returns_first_result():
    """同一 Idempotency-Key 重放：返回首次结果且不产生新记录。"""
    client, headers = _web_client()
    key = f"rating:{uuid.uuid4()}"
    first = _post_rating(client, headers, "ADV_IDEM_1", key=key)
    assert first.status_code == 200
    replay = _post_rating(client, headers, "ADV_IDEM_1", key=key)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    with SessionLocal() as db:
        count = (
            db.query(AdvisorRating)
            .filter(AdvisorRating.advisor_id == "ADV_IDEM_1")
            .count()
        )
    assert count == 1


def test_post_without_csrf_is_forbidden():
    """无 CSRF token 的 POST 返回 403。"""
    client, _headers = _web_client()
    resp = client.post(
        "/api/advisors/ADV_CSRF_1/ratings",
        headers={"Idempotency-Key": f"rating:{uuid.uuid4()}"},
        json={"scores": _scores(3)},
    )
    assert resp.status_code == 403


def test_duplicate_rating_same_advisor_returns_409():
    """同人同导师重复提交（新幂等键）返回 409。"""
    client, headers = _web_client()
    assert _post_rating(client, headers, "ADV_DUP_1").status_code == 200
    dup = _post_rating(client, headers, "ADV_DUP_1", value=5)
    assert dup.status_code == 409
    assert "不可重复提交" in dup.json()["detail"]


def test_daily_limit_returns_429_on_sixth_submission():
    """同一主体当日第 6 条评分返回 429（默认上限 5 条）。"""
    client, headers = _web_client()
    for index in range(5):
        resp = _post_rating(client, headers, f"ADV_LIMIT_{index}")
        assert resp.status_code == 200
    sixth = _post_rating(client, headers, "ADV_LIMIT_5")
    assert sixth.status_code == 429
    assert "上限" in sixth.json()["detail"]


def test_summary_empty_state_is_honest():
    """无评分导师：返回结构完整的全零空态，不伪造数据。"""
    client, _headers = _web_client()
    resp = client.get("/api/advisors/ADV_EMPTY_0/ratings/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["advisor_id"] == "ADV_EMPTY_0"
    assert summary["total_n"] == 0
    assert summary["last_collected_at"] is None
    assert set(summary["dimensions"]) == set(TRAIT_KEYS)
    for dimension in summary["dimensions"].values():
        assert dimension == {"value": None, "n": 0}

    listed = client.get("/api/advisors/ADV_EMPTY_0/ratings")
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_submit_writes_audit_event_without_payload():
    """提交事件写入审计（枚举字段，无评分正文）。"""
    client, headers = _web_client()
    assert _post_rating(client, headers, "ADV_AUDIT_1").status_code == 200
    with SessionLocal() as db:
        events = (
            db.query(ArtifactAuditEvent)
            .filter(
                ArtifactAuditEvent.event_type == "advisor_rating_submitted"
            )
            .all()
        )
    assert len(events) == 1
    assert events[0].operation == "submit_advisor_rating"
    assert events[0].outcome == "success"
