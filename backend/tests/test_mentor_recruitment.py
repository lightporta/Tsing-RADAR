"""导师招募管理：发布→审核→公开可见、更新重提、下架。"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.db.session import SessionLocal
from app.models.recruitment import Recruitment
from app.services.recruitment_review import review_recruitment
from tests.mentor_helpers import (
    auto_claim,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
)

EMAIL = "mentor01@tsinghua.edu.cn"


def _idem(headers: dict[str, str]) -> dict[str, str]:
    """B-08：导师端写端点与学生侧对齐，强制 Idempotency-Key。"""
    return {**headers, "Idempotency-Key": f"mentor-recruit:{uuid.uuid4()}"}


def _payload(**overrides):
    base = {
        "type": "招生",
        "title": "招收 2027 级博士生",
        "req": "对 NLP 有浓厚兴趣",
        "major": "计算机科学与技术",
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
        "is_urgent": False,
    }
    base.update(overrides)
    return base


def test_mentor_publishes_then_review_makes_it_publicly_visible(
    mentor_dataset, caplog
):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.post(
        "/api/mentor/recruitments", headers=_idem(headers), json=_payload()
    )
    assert response.status_code == 200, response.text
    recruit_id = response.json()["recruit_id"]
    assert response.json()["publication_status"] == "restricted"

    # 导师端列表可见（pending_review）
    mine = client.get("/api/mentor/recruitments", headers=headers).json()
    assert len(mine["data"]) == 1
    assert mine["data"][0]["review_status"] == "pending_review"

    # 公开列表不可见（未审核）
    public = client.get("/api/recruitments").json()["data"]
    assert all(item.get("recruit_id") != recruit_id for item in public)

    # 管理员审批后公开可见
    with SessionLocal() as db:
        review_recruitment(
            db,
            recruit_id=recruit_id,
            action="approve",
            reviewer="ops-admin",
            reason="内容合规",
        )
    public = client.get("/api/recruitments").json()["data"]
    assert any(item.get("recruit_id") == recruit_id for item in public)


def test_mentor_updates_resubmits_and_withdraws(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.post(
        "/api/mentor/recruitments", headers=_idem(headers), json=_payload()
    )
    recruit_id = response.json()["recruit_id"]

    response = client.patch(
        f"/api/mentor/recruitments/{recruit_id}",
        headers=_idem(headers),
        json={**_payload(title="招收 2027 级博士生（更新）"), "submit_for_review": True},
    )
    assert response.status_code == 200
    assert response.json()["updated"] is True

    response = client.delete(
        f"/api/mentor/recruitments/{recruit_id}", headers=_idem(headers)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "withdrawn"

    mine = client.get("/api/mentor/recruitments", headers=headers).json()
    assert mine["data"] == []


def test_mentor_cannot_touch_other_publishers_recruitment(mentor_dataset, caplog):
    client_a, headers_a = mentor_web_client()
    mentor_login(client_a, headers_a, caplog, email=EMAIL)
    auto_claim(client_a, headers_a)
    response = client_a.post(
        "/api/mentor/recruitments", headers=_idem(headers_a), json=_payload()
    )
    recruit_id = response.json()["recruit_id"]

    client_b, headers_b = mentor_web_client()
    mentor_login(client_b, headers_b, caplog, email="mentor02@tsinghua.edu.cn")
    response = client_b.delete(
        f"/api/mentor/recruitments/{recruit_id}", headers=_idem(headers_b)
    )
    assert response.status_code == 403

    with SessionLocal() as db:
        record = db.get(Recruitment, recruit_id)
        assert record.publisher_type == "advisor"
        assert record.authorization_basis == "mentor_authorized"
