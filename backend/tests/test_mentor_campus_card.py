"""导师校园卡人工审核：上传校验、认领前置条件、材料清理与审计。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.mentor_campus_card import MentorCampusCard
from tests.mentor_helpers import (
    ADMIN_HEADERS,
    PNG_1PX,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
    review_campus_card,
    upload_campus_card,
)

EMAIL = "mentor01@tsinghua.edu.cn"


def _login(client_headers, caplog):
    client, headers = client_headers
    mentor_login(client, headers, caplog, email=EMAIL)
    return client, headers


def test_upload_creates_pending_card(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    response = upload_campus_card(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["card_id"]

    status = client.get(
        "/api/mentor/verification/campus-card", headers=headers
    ).json()
    assert status["status"] == "pending"
    assert status["eligible_to_claim"] is False
    assert status["card"]["media_type"] == "image/png"
    assert status["card"]["material_cleared"] is False
    # 待审材料不放审核说明
    assert status["card"]["review_note"] is None


def test_upload_rejects_unsupported_extension(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    response = upload_campus_card(
        client,
        headers,
        payload=b"GIF89a",
        filename="card.gif",
        media_type="image/gif",
    )
    assert response.status_code == 415


def test_upload_rejects_mime_mismatch(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    response = upload_campus_card(
        client,
        headers,
        payload=PNG_1PX,
        filename="card.png",
        media_type="image/jpeg",
    )
    assert response.status_code == 415


def test_upload_rejects_empty_file(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    response = upload_campus_card(
        client,
        headers,
        payload=b"",
        filename="card.png",
        media_type="image/png",
    )
    assert response.status_code == 422


def test_upload_replaces_pending_material(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    first = upload_campus_card(client, headers)
    assert first.status_code == 200
    second = upload_campus_card(client, headers)
    assert second.status_code == 200

    with SessionLocal() as db:
        cards = db.query(MentorCampusCard).all()
        pending = [card for card in cards if card.status == "pending"]
        assert len(pending) == 1
        assert pending[0].card_id == second.json()["card_id"]


def test_claim_blocked_without_card(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={
            "candidate_id": "A001",
            "name": "张伟",
            "department": "计算机科学与技术系",
        },
    )
    assert response.status_code == 403
    assert "校园卡" in response.json()["detail"]


def test_claim_blocked_when_card_rejected(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    card_id = upload_campus_card(client, headers).json()["card_id"]
    response = review_campus_card(
        client, card_id, action="reject", note="材料模糊，无法辨认"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    status = client.get(
        "/api/mentor/verification/campus-card", headers=headers
    ).json()
    assert status["eligible_to_claim"] is False

    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={
            "candidate_id": "A001",
            "name": "张伟",
            "department": "计算机科学与技术系",
        },
    )
    assert response.status_code == 403


def test_review_approve_clears_material_and_audits(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    card_id = upload_campus_card(client, headers).json()["card_id"]

    with SessionLocal() as db:
        card = db.get(MentorCampusCard, card_id)
        object_key = card.object_key
        assert object_key
        material_path = Path(settings.OBJECT_STORAGE_LOCAL_ROOT) / object_key
        assert material_path.is_file()

    response = review_campus_card(client, card_id)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["material_cleared"] is True

    with SessionLocal() as db:
        card = db.get(MentorCampusCard, card_id)
        assert card.object_key == ""
        assert card.material_cleared_at is not None
        assert card.reviewed_by == "ops-admin"
        assert material_path.exists() is False

    events = (
        SessionLocal()
        .query(ArtifactAuditEvent)
        .filter(ArtifactAuditEvent.event_type == "mentor_campus_card_reviewed")
        .all()
    )
    assert len(events) == 1
    # 审计事件不含材料正文或对象键，只含枚举式事件字段
    serialized = str(events[0].__dict__)
    assert events[0].document_id == card_id
    assert events[0].outcome == "approved"
    assert object_key not in serialized

    # 通过后即可认领
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={
            "candidate_id": "A001",
            "name": "张伟",
            "department": "计算机科学与技术系",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "claimed"


def test_review_requires_note(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    card_id = upload_campus_card(client, headers).json()["card_id"]
    response = review_campus_card(client, card_id, note="  ")
    assert response.status_code == 422


def test_review_rejects_unknown_card(mentor_dataset, caplog):
    client, _ = _login(mentor_web_client(), caplog)
    response = review_campus_card(client, "not-a-card-id")
    assert response.status_code == 404


def test_review_only_once(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    card_id = upload_campus_card(client, headers).json()["card_id"]
    assert review_campus_card(client, card_id).status_code == 200
    response = review_campus_card(client, card_id)
    assert response.status_code == 409


def test_admin_campus_card_list_and_filter(mentor_dataset, caplog):
    client, headers = _login(mentor_web_client(), caplog)
    card_id = upload_campus_card(client, headers).json()["card_id"]

    response = client.get(
        "/api/admin/mentor/campus-cards", headers=ADMIN_HEADERS
    )
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) == 1
    assert items[0]["card_id"] == card_id
    assert items[0]["status"] == "pending"
    assert "object_key" not in items[0]

    response = client.get(
        "/api/admin/mentor/campus-cards",
        headers=ADMIN_HEADERS,
        params={"status": "approved"},
    )
    assert response.json()["data"] == []


def test_admin_campus_card_requires_token(mentor_dataset, caplog):
    client, _ = _login(mentor_web_client(), caplog)
    response = client.get("/api/admin/mentor/campus-cards")
    assert response.status_code == 403


def test_campus_card_requires_mentor_login(mentor_dataset):
    client, headers = mentor_web_client()
    response = client.get(
        "/api/mentor/verification/campus-card", headers=headers
    )
    assert response.status_code == 401
