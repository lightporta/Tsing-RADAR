"""导师隐私控制：可见性即时生效、下线/隐藏申请审批流。"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.mentor_profile import MentorProfile
from app.models.takedown_request import TakedownRequest
from tests.mentor_helpers import (
    auto_claim,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
)

EMAIL = "mentor01@tsinghua.edu.cn"
ADMIN = {"X-Admin-Token": "test-admin-token-not-for-production"}


def test_visibility_updates_take_effect_immediately(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.get("/api/mentor/privacy", headers=headers)
    assert response.status_code == 200
    assert response.json()["visibility"] == {}

    response = client.patch(
        "/api/mentor/privacy/visibility",
        headers=headers,
        json={"visibility": {"contact_email": False, "self_intro": False}},
    )
    assert response.status_code == 200
    assert response.json()["visibility"]["contact_email"] is False

    # 不支持的字段拒绝
    response = client.patch(
        "/api/mentor/privacy/visibility",
        headers=headers,
        json={"visibility": {"unknown_field": False}},
    )
    assert response.status_code == 422

    status = client.get("/api/mentor/privacy", headers=headers).json()
    assert status["visibility"]["contact_email"] is False


def test_full_takedown_flow(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.post(
        "/api/mentor/privacy/takedowns",
        headers=headers,
        json={"reason": "涉及个人隐私", "scope": "full", "field_name": None},
    )
    assert response.status_code == 200
    req_id = response.json()["req_id"]

    # pending 期间不生效
    status = client.get("/api/mentor/privacy", headers=headers).json()
    assert status["takedown"]["active"] is False

    # 重复申请被拒绝
    response = client.post(
        "/api/mentor/privacy/takedowns",
        headers=headers,
        json={"reason": "再申请一次", "scope": "full"},
    )
    assert response.status_code == 409

    response = client.post(
        f"/api/admin/mentor/takedowns/{req_id}/review",
        headers=ADMIN,
        json={"action": "approve", "reviewer": "ops-admin", "note": "已核实"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    status = client.get("/api/mentor/privacy", headers=headers).json()
    assert status["takedown"]["active"] is True

    with SessionLocal() as db:
        profile = db.query(MentorProfile).one()
        assert profile.takedown_at is not None
        assert (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.event_type == "mentor_takedown_approve")
            .count()
            == 1
        )

    history = client.get("/api/mentor/privacy/takedowns", headers=headers).json()
    assert len(history["data"]) == 1
    assert history["data"][0]["status"] == "approved"


def test_field_takedown_hides_single_field(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.post(
        "/api/mentor/privacy/takedowns",
        headers=headers,
        json={"reason": "联系方式不便展示", "scope": "field", "field_name": "contact_email"},
    )
    assert response.status_code == 200
    req_id = response.json()["req_id"]

    response = client.post(
        f"/api/admin/mentor/takedowns/{req_id}/review",
        headers=ADMIN,
        json={"action": "approve", "reviewer": "ops-admin", "note": "ok"},
    )
    assert response.status_code == 200

    status = client.get("/api/mentor/privacy", headers=headers).json()
    assert status["takedown"]["active"] is False
    assert status["visibility"]["contact_email"] is False

    # field 模式缺少字段名 → 422
    response = client.post(
        "/api/mentor/privacy/takedowns",
        headers=headers,
        json={"reason": "测试", "scope": "field"},
    )
    assert response.status_code == 422


def test_takedown_reject_keeps_status_active(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.post(
        "/api/mentor/privacy/takedowns",
        headers=headers,
        json={"reason": "不想展示了", "scope": "full"},
    )
    req_id = response.json()["req_id"]
    response = client.post(
        f"/api/admin/mentor/takedowns/{req_id}/review",
        headers=ADMIN,
        json={"action": "reject", "reviewer": "ops-admin", "note": "理由不足"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    status = client.get("/api/mentor/privacy", headers=headers).json()
    assert status["takedown"]["active"] is False

    with SessionLocal() as db:
        request = db.get(TakedownRequest, req_id)
        assert request.decided_by == "admin:ops-admin"
        assert request.admin_note == "理由不足"
