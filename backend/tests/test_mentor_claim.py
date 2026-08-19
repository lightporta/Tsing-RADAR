"""导师档案认领：候选匹配、唯一候选自动绑定、多候选人工审批、审计。"""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.mentor_account import MentorAccount
from app.models.mentor_claim import MentorClaim
from app.models.mentor_profile import MentorProfile
from tests.mentor_helpers import (
    auto_claim,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
    verify_campus_card,
)

EMAIL = "mentor01@tsinghua.edu.cn"
ADMIN = {"X-Admin-Token": "test-admin-token-not-for-production"}


def _review(
    client,
    path: str,
    *,
    action: str = "approve",
    reviewer: str = "ops-admin",
    note: str | None = "通过",
):
    return client.post(
        path,
        headers=ADMIN,
        json={"action": action, "reviewer": reviewer, "note": note},
    )


def test_eligible_lists_only_matching_candidates(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)

    response = client.get(
        "/api/mentor/claim/eligible",
        headers=headers,
        params={"name": "张伟", "department": "计算机科学与技术系"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["advisor_id"] == "A001"
    assert data[0]["in_db"] is False

    response = client.get(
        "/api/mentor/claim/eligible",
        headers=headers,
        params={"name": "李娜"},
    )
    assert len(response.json()["data"]) == 2
    assert {item["advisor_id"] for item in response.json()["data"]} == {
        "B001",
        "B002",
    }


def test_unique_candidate_auto_claims_and_creates_profile(
    mentor_dataset, caplog
):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    with SessionLocal() as db:
        account = db.query(MentorAccount).filter(MentorAccount.email == EMAIL).one()
        assert account.status == "claimed"
        assert account.advisor_id == "A001"
        claim = (
            db.query(MentorClaim)
            .filter(MentorClaim.account_id == account.account_id)
            .one()
        )
        assert claim.factor_used == "auto_unique"
        assert claim.status == "approved"
        profile = (
            db.query(MentorProfile)
            .filter(MentorProfile.account_id == account.account_id)
            .one()
        )
        assert profile.advisor_id == "A001"

    status = client.get("/api/mentor/auth/status", headers=headers).json()
    assert status["status"] == "claimed"
    assert status["advisor_id"] == "A001"


def test_multi_candidate_claim_goes_to_manual_review(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    verify_campus_card(client, headers)

    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={
            "candidate_id": "B001",
            "name": "李娜",
            "department": "自动化系",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_review"
    assert body["factor"] == "manual"

    with SessionLocal() as db:
        account = db.query(MentorAccount).filter(MentorAccount.email == EMAIL).one()
        assert account.status == "claim_pending"

    # 已进入待审批后不可重复提交
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={"candidate_id": "B002", "name": "李娜", "department": ""},
    )
    assert response.status_code == 409


def test_claim_rejects_mismatched_department(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    verify_campus_card(client, headers)
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={
            "candidate_id": "A001",
            "name": "张伟",
            "department": "自动化系",
        },
    )
    assert response.status_code == 404


def test_claim_rejects_already_claimed_advisor(mentor_dataset, caplog):
    client_a, headers_a = mentor_web_client()
    mentor_login(client_a, headers_a, caplog, email=EMAIL)
    auto_claim(client_a, headers_a)

    client_b, headers_b = mentor_web_client()
    mentor_login(client_b, headers_b, caplog, email="mentor02@tsinghua.edu.cn")
    verify_campus_card(client_b, headers_b)
    response = client_b.post(
        "/api/mentor/claim",
        headers=headers_b,
        json={
            "candidate_id": "A001",
            "name": "张伟",
            "department": "计算机科学与技术系",
        },
    )
    assert response.status_code == 409


def test_admin_rejects_and_approves_manual_claim(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    verify_campus_card(client, headers)
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={"candidate_id": "B001", "name": "李娜", "department": "自动化系"},
    )
    claim_id = response.json()["claim_id"]

    # 管理员审批前拒绝
    response = _review(client, f"/api/admin/mentor/claims/{claim_id}/review")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    with SessionLocal() as db:
        account = db.query(MentorAccount).filter(MentorAccount.email == EMAIL).one()
        assert account.status == "claimed"
        assert account.advisor_id == "B001"
        claim = db.get(MentorClaim, claim_id)
        assert claim.decided_by == "admin:ops-admin"
        assert (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.event_type == "mentor_claim_approve")
            .count()
            == 1
        )


def test_admin_surface_requires_admin_token(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    response = client.get("/api/admin/mentor/claims", headers=headers)
    assert response.status_code == 403


def test_claim_history_lists_records(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)
    response = client.get("/api/mentor/claim/history", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["status"] == "approved"
