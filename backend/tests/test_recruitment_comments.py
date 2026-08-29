"""招募评论区：两级树、分级审核可见性、举报即隐藏、软删保楼层、
点赞幂等、限频 429、幂等重放、CSRF 与公开口径一致性合同测试。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.recruitment import Recruitment
from app.models.recruitment_comment import (
    RecruitmentComment,
    RecruitmentCommentLike,
)
from app.services.recruitment_review import review_recruitment

ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token-not-for-production"}


@pytest.fixture(autouse=True)
def isolate_comment_records():
    """评论/点赞/评论审计事件按用例隔离（幂等记录用唯一键天然隔离）。"""
    yield
    with SessionLocal() as db:
        db.query(RecruitmentCommentLike).delete(synchronize_session=False)
        db.query(RecruitmentComment).delete(synchronize_session=False)
        db.query(ArtifactAuditEvent).filter(
            ArtifactAuditEvent.operation == "recruitment_comment"
        ).delete(synchronize_session=False)
        db.commit()


def _web_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    response = client.get("/api/session")
    assert response.status_code == 200
    return client, {"X-CSRF-Token": client.cookies["tsing_radar_csrf"]}


def _idem(headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or f"comment:{uuid.uuid4()}"}


def _recruitment_payload(**overrides) -> dict:
    base = {
        "type": "科研助理",
        "title": "课题组招募科研助理",
        "req": "熟悉 Python，每周投入 8 小时以上",
        "major": "计算机科学与技术",
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
        "is_urgent": False,
    }
    base.update(overrides)
    return base


def _publish_public_recruitment(
    client: TestClient, headers: dict[str, str], **overrides
) -> str:
    """学生端投稿 + 审核通过 → 进入公开口径，返回 recruit_id。"""
    response = client.post(
        "/api/recruitments",
        headers=_idem(headers, f"recruit:{uuid.uuid4()}"),
        json=_recruitment_payload(**overrides),
    )
    assert response.status_code == 200, response.text
    recruit_id = response.json()["recruit_id"]
    with SessionLocal() as db:
        review_recruitment(
            db,
            recruit_id=recruit_id,
            action="approve",
            reviewer="ops-admin",
            reason="内容合规",
        )
    return recruit_id


def _post_comment(
    client: TestClient,
    headers: dict[str, str],
    recruit_id: str,
    content: str,
    *,
    parent_id: str | None = None,
    key: str | None = None,
):
    return client.post(
        f"/api/recruitments/{recruit_id}/comments",
        headers=_idem(headers, key),
        json={"content": content, "parent_id": parent_id},
    )


def _tree(client: TestClient, recruit_id: str) -> dict:
    response = client.get(f"/api/recruitments/{recruit_id}/comments")
    assert response.status_code == 200, response.text
    return response.json()


# =====================================================================
# 两级树结构
# =====================================================================


def test_two_level_tree_with_embedded_replies():
    """父评论分页 + 每父内嵌回复；输出不含 author_principal。"""
    client, headers = _web_client()
    recruit_id = _publish_public_recruitment(client, headers)
    top = _post_comment(client, headers, recruit_id, "请问名额还有吗？")
    assert top.status_code == 200, top.text
    top_id = top.json()["comment_id"]
    reply = _post_comment(
        client, headers, recruit_id, "还有两个，欢迎投递", parent_id=top_id
    )
    assert reply.status_code == 200, reply.text

    tree = _tree(client, recruit_id)
    assert tree["meta"]["total"] == 1
    assert len(tree["data"]) == 1
    parent = tree["data"][0]
    assert parent["comment_id"] == top_id
    assert parent["content"] == "请问名额还有吗？"
    assert parent["reply_total"] == 1
    assert len(parent["replies"]) == 1
    assert parent["replies"][0]["content"] == "还有两个，欢迎投递"
    # 隐私红线：公开输出无 author_principal
    assert "author_principal" not in parent
    assert "author_principal" not in parent["replies"][0]
    assert parent["badge"]


def test_reply_to_reply_returns_422():
    """仅两级：对回复再回复 → 422。"""
    client, headers = _web_client()
    recruit_id = _publish_public_recruitment(client, headers)
    top = _post_comment(client, headers, recruit_id, "顶层问题").json()[
        "comment_id"
    ]
    reply = _post_comment(
        client, headers, recruit_id, "一级回复", parent_id=top
    ).json()["comment_id"]
    nested = _post_comment(
        client, headers, recruit_id, "二级回复", parent_id=reply
    )
    assert nested.status_code == 422


# =====================================================================
# 分级审核可见性
# =====================================================================


def test_op_comment_is_instantly_visible():
    """楼主（发布者本人）评论即时 approved 且公开可见。"""
    client, headers = _web_client()
    recruit_id = _publish_public_recruitment(client, headers)
    # 发布者本人（同一会话）评论 → is_op → approved
    created = _post_comment(client, headers, recruit_id, "楼主补充：名额两个")
    assert created.status_code == 200
    assert created.json()["review_status"] == "approved"
    tree = _tree(client, recruit_id)
    assert tree["meta"]["total"] == 1
    assert tree["data"][0]["is_op"] is True
    assert tree["data"][0]["badge"] == "楼主"


def test_comment_with_link_held_for_review_and_hidden_publicly():
    """含链接评论先审后发：初始 pending_review，公开树不可见；审核通过后可见。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    guest, guest_headers = _web_client()
    created = _post_comment(
        guest, guest_headers, recruit_id, "资料在 https://example.com 这里"
    )
    assert created.status_code == 200
    assert created.json()["review_status"] == "pending_review"
    comment_id = created.json()["comment_id"]

    # 公开不可见
    assert _tree(guest, recruit_id)["meta"]["total"] == 0

    # 审核队列可见 → 通过后公开可见
    queue = guest.get("/api/admin/mentor/comments", headers=ADMIN_HEADERS)
    assert queue.status_code == 200
    assert any(
        item["comment_id"] == comment_id for item in queue.json()["data"]
    )
    reviewed = guest.post(
        f"/api/admin/mentor/comments/{comment_id}/review",
        headers=ADMIN_HEADERS,
        json={"action": "approve", "reviewer": "ops", "note": "链接为公开资料"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_status"] == "approved"
    tree = _tree(guest, recruit_id)
    assert tree["meta"]["total"] == 1

    # 治理历史写入评论行（与招募审核同构字段）
    with SessionLocal() as db:
        row = db.get(RecruitmentComment, comment_id)
        history = row.governance["review_history"]
        assert history[-1]["action"] == "approve"
        assert history[-1]["reviewer"] == "ops"
        assert history[-1]["reason"] == "链接为公开资料"
        assert history[-1]["reviewed_at"]


def test_admin_reject_keeps_comment_hidden():
    """审核驳回：评论保持公开不可见。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    guest, guest_headers = _web_client()
    created = _post_comment(
        guest, guest_headers, recruit_id, "vx: abcde12345 私聊"
    )
    comment_id = created.json()["comment_id"]
    reviewed = guest.post(
        f"/api/admin/mentor/comments/{comment_id}/review",
        headers=ADMIN_HEADERS,
        json={"action": "reject", "reviewer": "ops", "note": "含站外联系方式"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "rejected"
    assert _tree(guest, recruit_id)["meta"]["total"] == 0


def test_admin_comment_routes_require_admin_token():
    """评论审核路由沿用 verify_admin：无 token → 403。"""
    client, _ = _web_client()
    assert client.get("/api/admin/mentor/comments").status_code == 403


# =====================================================================
# 举报即隐藏
# =====================================================================


def test_report_hides_comment_immediately():
    """举报后评论立即从公开树消失并进审核队列。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    author, author_headers = _web_client()
    created = _post_comment(author, author_headers, recruit_id, "正常讨论")
    comment_id = created.json()["comment_id"]
    assert created.json()["review_status"] == "approved"
    assert _tree(author, recruit_id)["meta"]["total"] == 1

    reporter, reporter_headers = _web_client()
    reported = reporter.post(
        f"/api/recruitments/{recruit_id}/comments/{comment_id}/report",
        headers=_idem(reporter_headers),
        json={"reason": "疑似广告"},
    )
    assert reported.status_code == 200, reported.text
    # 立即隐藏
    assert _tree(reporter, recruit_id)["meta"]["total"] == 0
    # 进审核队列并带举报原因
    queue = reporter.get("/api/admin/mentor/comments", headers=ADMIN_HEADERS)
    item = next(
        row
        for row in queue.json()["data"]
        if row["comment_id"] == comment_id
    )
    assert item["reports"][-1]["reason"] == "疑似广告"


# =====================================================================
# 软删保楼层
# =====================================================================


def test_soft_delete_keeps_thread_with_placeholder():
    """作者自删：公开树显示「已删除」占位，回复仍可见；重复删除幂等。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    top = _post_comment(publisher, pub_headers, recruit_id, "顶层评论").json()[
        "comment_id"
    ]
    guest, guest_headers = _web_client()
    _post_comment(guest, guest_headers, recruit_id, "回复保留", parent_id=top)

    deleted = publisher.delete(
        f"/api/recruitments/{recruit_id}/comments/{top}",
        headers=_idem(pub_headers),
    )
    assert deleted.status_code == 200, deleted.text
    tree = _tree(guest, recruit_id)
    assert tree["meta"]["total"] == 1
    parent = tree["data"][0]
    assert parent["deleted"] is True
    assert parent["content"] == "该评论已删除"
    assert parent["reply_total"] == 1
    assert parent["replies"][0]["content"] == "回复保留"

    # 非作者删除 → 403；重复删除（新幂等键）幂等成功
    forbidden = guest.delete(
        f"/api/recruitments/{recruit_id}/comments/{top}",
        headers=_idem(guest_headers),
    )
    assert forbidden.status_code == 403
    again = publisher.delete(
        f"/api/recruitments/{recruit_id}/comments/{top}",
        headers=_idem(pub_headers),
    )
    assert again.status_code == 200


# =====================================================================
# 点赞幂等
# =====================================================================


def test_like_is_deduplicated_per_principal():
    """同一主体重复点赞（不同幂等键）只 +1；同键重放返回首次结果。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    comment_id = _post_comment(
        publisher, pub_headers, recruit_id, "求赞评论"
    ).json()["comment_id"]

    liker, liker_headers = _web_client()
    key = f"like:{uuid.uuid4()}"
    first = liker.post(
        f"/api/recruitments/{recruit_id}/comments/{comment_id}/like",
        headers=_idem(liker_headers, key),
    )
    assert first.status_code == 200
    assert first.json()["like_count"] == 1
    # 同键重放
    replay = liker.post(
        f"/api/recruitments/{recruit_id}/comments/{comment_id}/like",
        headers=_idem(liker_headers, key),
    )
    assert replay.json() == first.json()
    # 同主体新键再点赞：去重不增加
    again = liker.post(
        f"/api/recruitments/{recruit_id}/comments/{comment_id}/like",
        headers=_idem(liker_headers),
    )
    assert again.status_code == 200
    assert again.json()["like_count"] == 1
    with SessionLocal() as db:
        row = db.get(RecruitmentComment, comment_id)
        assert row.like_count == 1


# =====================================================================
# 限频（服务内确定性）
# =====================================================================


def test_per_post_limit_returns_429_on_fourth_comment():
    """单帖每主体 ≤3 条：第 4 条 → 429。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    guest, guest_headers = _web_client()
    for index in range(3):
        resp = _post_comment(
            guest, guest_headers, recruit_id, f"第 {index + 1} 条"
        )
        assert resp.status_code == 200, resp.text
    fourth = _post_comment(guest, guest_headers, recruit_id, "第 4 条")
    assert fourth.status_code == 429
    assert "上限" in fourth.json()["detail"]


def test_daily_limit_returns_429(monkeypatch):
    """同一主体每日 ≤ 上限：跨帖累计，超限 429。"""
    monkeypatch.setattr(settings, "COMMENT_DAILY_LIMIT", 2)
    publisher, pub_headers = _web_client()
    first_post = _publish_public_recruitment(publisher, pub_headers)
    second_post = _publish_public_recruitment(publisher, pub_headers)
    guest, guest_headers = _web_client()
    assert _post_comment(guest, guest_headers, first_post, "第一条").status_code == 200
    assert _post_comment(guest, guest_headers, second_post, "第二条").status_code == 200
    third = _post_comment(guest, guest_headers, second_post, "第三条")
    assert third.status_code == 429
    assert "今日" in third.json()["detail"]


# =====================================================================
# 合同测试：幂等重放 / CSRF / 公开口径一致性
# =====================================================================


def test_create_comment_idempotent_replay_returns_first_result():
    """同一 Idempotency-Key 重放发评论：返回首次结果，不产生重复行。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    key = f"comment:{uuid.uuid4()}"
    first = _post_comment(
        publisher, pub_headers, recruit_id, "幂等测试评论", key=key
    )
    assert first.status_code == 200
    replay = _post_comment(
        publisher, pub_headers, recruit_id, "幂等测试评论", key=key
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()
    with SessionLocal() as db:
        count = (
            db.query(RecruitmentComment)
            .filter(RecruitmentComment.recruit_id == recruit_id)
            .count()
        )
    assert count == 1


def test_post_comment_without_csrf_is_forbidden():
    """无 CSRF token 的 POST → 403。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    client, _headers = _web_client()
    resp = client.post(
        f"/api/recruitments/{recruit_id}/comments",
        headers={"Idempotency-Key": f"comment:{uuid.uuid4()}"},
        json={"content": "无令牌评论"},
    )
    assert resp.status_code == 403


def test_comment_on_non_public_recruitment_returns_404():
    """未过审帖下不能有公开评论：发表与读取均按公开口径。"""
    client, headers = _web_client()
    created = client.post(
        "/api/recruitments",
        headers=_idem(headers, f"recruit:{uuid.uuid4()}"),
        json=_recruitment_payload(),
    )
    recruit_id = created.json()["recruit_id"]  # pending_review，未公开
    resp = _post_comment(client, headers, recruit_id, "抢跑评论")
    assert resp.status_code == 404
    # 评论树读取正常返回空（不暴露帖子是否存在）
    assert _tree(client, recruit_id)["meta"]["total"] == 0


def test_comment_submission_writes_audit_event_without_content():
    """发表写审计：枚举字段，无评论正文。"""
    publisher, pub_headers = _web_client()
    recruit_id = _publish_public_recruitment(publisher, pub_headers)
    secret_text = "审计红线验证评论正文"
    _post_comment(publisher, pub_headers, recruit_id, secret_text)
    with SessionLocal() as db:
        events = (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.operation == "recruitment_comment")
            .all()
        )
    assert len(events) == 1
    assert events[0].event_type == "submitted"
    assert events[0].outcome == "success"
    # 审计行没有任何字段携带评论正文
    row_values = {
        getattr(events[0], column)
        for column in (
            "owner_subject_id",
            "operation",
            "event_type",
            "outcome",
            "reason_code",
            "document_id",
            "idempotency_key_digest",
            "scan_method",
        )
    }
    assert all(secret_text not in str(value) for value in row_values)


# =====================================================================
# 详情端点：过滤口径 + 向后兼容 + 与列表一致
# =====================================================================


def test_detail_endpoint_returns_enriched_fields():
    """详情端点：公开帖返回扩展字段 + 时间线 + 相关招募。"""
    client, headers = _web_client()
    recruit_id = _publish_public_recruitment(
        client,
        headers,
        location="北京·清华科技园",
        quota="2 人",
        compensation="按学校助研标准",
        duration="6 个月",
        apply_method="站内投递简历即可",
        tags=["LLM", "系统"],
    )
    other_id = _publish_public_recruitment(
        client, headers, tags=["LLM", "推理"]
    )
    resp = client.get(f"/api/recruitments/{recruit_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["location"] == "北京·清华科技园"
    assert data["quota"] == "2 人"
    assert data["tags"] == ["LLM", "系统"]
    assert data["apply_method"] == "站内投递简历即可"
    assert data["created_at"] and data["verified_at"]
    assert "publisher_id" not in data
    related_ids = [item["recruit_id"] for item in data["related"]]
    assert other_id in related_ids
    assert recruit_id not in related_ids


def test_detail_endpoint_404_for_pending_takedown_and_expired():
    """未过审 / 已下架 / 已过期帖：详情一律 404，且与公开列表口径一致。"""
    client, headers = _web_client()
    # 未过审
    pending = client.post(
        "/api/recruitments",
        headers=_idem(headers, f"recruit:{uuid.uuid4()}"),
        json=_recruitment_payload(),
    ).json()["recruit_id"]
    assert client.get(f"/api/recruitments/{pending}").status_code == 404

    # 过审后下架
    taken_down = _publish_public_recruitment(client, headers)
    with SessionLocal() as db:
        record = db.get(Recruitment, taken_down)
        record.takedown_at = datetime(2026, 8, 18, 1, 0, 0)
        db.commit()
    assert client.get(f"/api/recruitments/{taken_down}").status_code == 404

    # 过审后过期（直接改写 deadline 模拟时间流逝）
    expired = _publish_public_recruitment(client, headers)
    with SessionLocal() as db:
        record = db.get(Recruitment, expired)
        record.deadline = date.today() - timedelta(days=1)
        db.commit()
    assert client.get(f"/api/recruitments/{expired}").status_code == 404

    # 公开口径一致：列表里看不到的帖，详情也 404
    listed_ids = {
        item["recruit_id"] for item in client.get("/api/recruitments").json()["data"]
    }
    for hidden in (pending, taken_down, expired):
        assert hidden not in listed_ids
        assert client.get(f"/api/recruitments/{hidden}").status_code == 404


def test_detail_endpoint_omits_absent_enrichment_keys():
    """向后兼容：新字段缺省时响应不含多余键。"""
    client, headers = _web_client()
    recruit_id = _publish_public_recruitment(client, headers)
    data = client.get(f"/api/recruitments/{recruit_id}").json()["data"]
    for key in (
        "location",
        "quota",
        "compensation",
        "duration",
        "apply_method",
        "tags",
        "advisor_id",
    ):
        assert key not in data
    assert data["advisor"] is None


def test_list_filters_by_tag_and_advisor_id():
    """列表 ?tag= / ?advisor_id= 筛选在公开口径上叠加收窄。"""
    client, headers = _web_client()
    tagged = _publish_public_recruitment(client, headers, tags=["LLM"])
    advised = _publish_public_recruitment(
        client, headers, advisor_id="A001", tags=["系统"]
    )
    _publish_public_recruitment(client, headers)  # 无标签对照

    by_tag = client.get("/api/recruitments", params={"tag": "LLM"}).json()["data"]
    assert {item["recruit_id"] for item in by_tag} == {tagged}

    by_advisor = client.get(
        "/api/recruitments", params={"advisor_id": "A001"}
    ).json()["data"]
    assert {item["recruit_id"] for item in by_advisor} == {advised}
