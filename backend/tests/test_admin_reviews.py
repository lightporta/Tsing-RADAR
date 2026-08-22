"""管理员审批端：三条审批流的列表、审批、鉴权与审计。"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.mentor_claim import MentorClaim
from app.models.mentor_profile import MentorProfile
from app.models.mentor_profile_edit import MentorProfileEdit
from app.models.takedown_request import TakedownRequest
from tests.mentor_helpers import (
    auto_claim,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
    verify_campus_card,
)

EMAIL = "mentor01@tsinghua.edu.cn"
ADMIN = {"X-Admin-Token": "test-admin-token-not-for-production"}


def test_admin_claims_listing_and_review(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    verify_campus_card(client, headers)
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={"candidate_id": "B001", "name": "李娜", "department": "自动化系"},
    )
    claim_id = response.json()["claim_id"]

    listing = client.get(
        "/api/admin/mentor/claims", headers=ADMIN
    ).json()["data"]
    assert any(item["claim_id"] == claim_id for item in listing)

    listing = client.get(
        "/api/admin/mentor/claims",
        headers=ADMIN,
        params={"status": "pending"},
    ).json()["data"]
    assert len(listing) == 1

    # 非法 action 拒绝
    response = client.post(
        f"/api/admin/mentor/claims/{claim_id}/review",
        headers=ADMIN,
        json={"action": "ban", "reviewer": "ops", "note": "x"},
    )
    assert response.status_code == 422


def test_admin_profile_edit_review_flow(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)
    response = client.post(
        "/api/mentor/profile/edits",
        headers=headers,
        json={"field_name": "research_highlights", "new_value": "多模态理解"},
    )
    edit_id = response.json()["edit_id"]

    listing = client.get("/api/admin/mentor/profile-edits", headers=ADMIN).json()[
        "data"
    ]
    assert any(item["edit_id"] == edit_id for item in listing)

    response = client.post(
        f"/api/admin/mentor/profile-edits/{edit_id}/review",
        headers=ADMIN,
        json={"action": "approve", "reviewer": "ops-admin", "note": "ok"},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        profile = db.query(MentorProfile).one()
        assert profile.self_claims["research_highlights"] == "多模态理解"
        assert (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.event_type == "mentor_edit_approve")
            .count()
            == 1
        )


def test_admin_takedown_listing_and_review(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)
    response = client.post(
        "/api/mentor/privacy/takedowns",
        headers=headers,
        json={"reason": "隐私", "scope": "full"},
    )
    req_id = response.json()["req_id"]

    listing = client.get("/api/admin/mentor/takedowns", headers=ADMIN).json()[
        "data"
    ]
    assert any(item["req_id"] == req_id for item in listing)

    response = client.post(
        f"/api/admin/mentor/takedowns/{req_id}/review",
        headers=ADMIN,
        json={"action": "approve", "reviewer": "ops-admin", "note": "ok"},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        request = db.get(TakedownRequest, req_id)
        assert request.status == "approved"
        assert (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.event_type == "mentor_takedown_approve")
            .count()
            == 1
        )


def test_double_review_is_rejected(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    verify_campus_card(client, headers)
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={"candidate_id": "B001", "name": "李娜", "department": "自动化系"},
    )
    claim_id = response.json()["claim_id"]
    for _ in range(2):
        response = client.post(
            f"/api/admin/mentor/claims/{claim_id}/review",
            headers=ADMIN,
            json={"action": "approve", "reviewer": "ops-admin", "note": "ok"},
        )
    assert response.status_code == 409


def test_admin_endpoints_are_protected(mentor_dataset):
    client, _ = mentor_web_client()
    response = client.get("/api/admin/mentor/claims")
    assert response.status_code == 403
    response = client.get(
        "/api/admin/mentor/claims", headers={"X-Admin-Token": "wrong"}
    )
    assert response.status_code == 403
