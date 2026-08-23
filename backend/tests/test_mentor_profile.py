"""导师档案视图与字段级编辑审批流。"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.models.mentor_profile import MentorProfile
from app.models.mentor_profile_edit import MentorProfileEdit
from tests.mentor_helpers import (
    auto_claim,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
)

EMAIL = "mentor01@tsinghua.edu.cn"
ADMIN = {"X-Admin-Token": "test-admin-token-not-for-production"}


def _submit_edit(client, headers, *, field_name="self_intro", new_value="本人简介"):
    return client.post(
        "/api/mentor/profile/edits",
        headers=headers,
        json={"field_name": field_name, "new_value": new_value},
    )


def test_me_returns_public_fields_and_empty_self_claims(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.get("/api/mentor", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["advisor_id"] == "A001"
    assert body["name"] == "张伟"
    assert body["self_claims"] == {}
    assert body["hidden_fields"] == []
    assert body["takedown"]["active"] is False
    assert body["public_fields"]["title"] == "教授"


def test_unclaimed_mentor_cannot_read_profile(caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    response = client.get("/api/mentor", headers=headers)
    assert response.status_code == 409


def test_field_edit_goes_pending_then_approve_writes_self_claims(
    mentor_dataset, caplog
):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = _submit_edit(
        client, headers, field_name="self_intro", new_value="我是张伟"
    )
    assert response.status_code == 200
    edit_id = response.json()["edit_id"]
    assert response.json()["status"] == "pending"

    # 同字段 pending 期间不可重复提交
    response = _submit_edit(client, headers, new_value="再次提交")
    assert response.status_code == 409

    # 非白名单字段拒绝
    response = _submit_edit(client, headers, field_name="name", new_value="李四")
    assert response.status_code == 422

    # 审批通过后 self_claims 生效
    response = client.post(
        f"/api/admin/mentor/profile-edits/{edit_id}/review",
        headers=ADMIN,
        json={"action": "approve", "reviewer": "ops-admin", "note": "内容合规"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    body = client.get("/api/mentor", headers=headers).json()
    assert body["self_claims"]["self_intro"] == "我是张伟"

    # 编辑历史可见
    history = client.get("/api/mentor/profile/edits", headers=headers).json()
    assert len(history["data"]) == 1
    assert history["data"][0]["status"] == "approved"


def test_field_edit_reject_keeps_old_value(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = _submit_edit(client, headers, new_value="不应通过的内容")
    edit_id = response.json()["edit_id"]
    response = client.post(
        f"/api/admin/mentor/profile-edits/{edit_id}/review",
        headers=ADMIN,
        json={"action": "reject", "reviewer": "ops-admin", "note": "不合规"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    with SessionLocal() as db:
        profile = db.query(MentorProfile).one()
        assert "self_intro" not in (profile.self_claims or {})
        edit = db.get(MentorProfileEdit, edit_id)
        assert edit.decided_by == "admin:ops-admin"
        assert edit.admin_note == "不合规"


def test_visibility_hides_fields_from_mentor_view(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    response = client.patch(
        "/api/mentor/privacy/visibility",
        headers=headers,
        json={"visibility": {"self_intro": False, "contact_email": False}},
    )
    assert response.status_code == 200

    body = client.get("/api/mentor", headers=headers).json()
    assert body["hidden_fields"] == ["contact_email", "self_intro"]
    assert "contact_email" not in body["public_fields"]
