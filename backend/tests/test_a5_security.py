"""A5 身份、对象授权、私有文件与前端隐私合同测试。"""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import uuid
import zipfile
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from app.db.session import SessionLocal
from app.core.config import settings
from app.main import app, startup_event
from app.models.identity import ExternalIdentity, IdentitySession
from app.models.questionnaire_session import QuestionnaireSession
from app.models.recruitment import Recruitment

QXD_BEARER = "test-qxd-key"
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"


def _web_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    response = client.get("/api/session")
    assert response.status_code == 200
    return client, {"X-CSRF-Token": client.cookies["tsing_radar_csrf"]}


def _idem(
    headers: dict[str, str],
    key: str | None = None,
) -> dict[str, str]:
    return {
        **headers,
        "Idempotency-Key": key or f"test:{uuid.uuid4()}",
    }


def _docx_bytes(text: str = "私有简历正文") -> bytes:
    output = io.BytesIO()
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                "</Types>"
            ),
        )
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _pdf_bytes() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(output)
    return output.getvalue()


def _upload_docx(
    client: TestClient,
    headers: dict[str, str],
    *,
    filename: str = "resume.docx",
):
    return client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                filename,
                _docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )


def _qxd_headers(claim: str | None = None, *, signature: str | None = None):
    headers = {"Authorization": f"Bearer {QXD_BEARER}"}
    if claim is not None:
        headers["X-QXD-End-User-Id"] = claim
        headers["X-QXD-End-User-Signature"] = signature or hmac.new(
            QXD_CLAIM_SECRET.encode(),
            claim.encode(),
            hashlib.sha256,
        ).hexdigest()
    return headers


def test_web_requires_server_session_and_csrf_and_ignores_legacy_identity_header():
    client = TestClient(app)
    missing = client.post(
        "/api/interviews",
        headers={"X-Student-Token": "forged-student"},
        json={},
    )
    assert missing.status_code == 401

    client, headers = _web_client()
    assert client.post("/api/interviews", json={}).status_code == 403
    assert client.post(
        "/api/interviews",
        headers={"X-CSRF-Token": "forged"},
        json={},
    ).status_code == 403
    created = client.post("/api/interviews", headers=headers, json={})
    assert created.status_code == 200


@pytest.mark.asyncio
async def test_production_fails_closed_when_web_cookie_is_not_secure(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "m" * 32)
    monkeypatch.setattr(settings, "SESSION_HMAC_SECRET", "s" * 32)
    monkeypatch.setattr(settings, "ARTIFACT_SIGNING_SECRET", "a" * 32)
    monkeypatch.setattr(settings, "QXD_API_KEY", "k" * 32)
    monkeypatch.setattr(settings, "QXD_END_USER_SIGNING_SECRET", "q" * 32)
    monkeypatch.setattr(settings, "WEB_COOKIE_SECURE", False)
    with pytest.raises(RuntimeError, match="WEB_COOKIE_SECURE"):
        await startup_event()


def test_web_sessions_are_opaque_refreshable_and_object_scoped():
    owner, owner_headers = _web_client()
    other, other_headers = _web_client()
    created = owner.post("/api/interviews", headers=owner_headers, json={}).json()
    session_id = created["session_id"]

    assert other.get(f"/api/interviews/{session_id}").status_code == 403
    assert other.patch(
        f"/api/interviews/{session_id}/profile",
        headers=other_headers,
        json={"expected_version": created["profile_version"]},
    ).status_code == 403

    with SessionLocal() as db:
        record = db.get(QuestionnaireSession, session_id)
        owner_subject = record.student_id
        identity = (
            db.query(IdentitySession)
            .filter(IdentitySession.subject_id == owner_subject)
            .one()
        )
        raw_cookie = owner.cookies["tsing_radar_session"]
        assert raw_cookie not in {
            identity.session_id,
            identity.subject_id,
            identity.token_digest,
        }

    refreshed = owner.get("/api/session")
    assert refreshed.status_code == 200
    assert owner.get(f"/api/interviews/{session_id}").status_code == 200


def test_web_interview_json_surface_persists_and_returns_a_complete_state():
    client, headers = _web_client()
    session_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/llm/chat",
        params={"stream": "false"},
        headers=headers,
        json={
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": "自然语言处理、对话系统"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    state = response.json()
    assert state["session_id"] == session_id
    assert state["profile"]["research_interests"] == [
        "自然语言处理",
        "对话系统",
    ]
    assert state["current_question"]["dimension"] == "research_mode"
    assert state["assistant_message"]
    assert client.get(f"/api/interviews/{session_id}").json()["profile"] == state["profile"]


def test_qxd_claim_is_separate_from_bearer_and_forgery_fails_closed(caplog):
    claim = f"end-user-{uuid.uuid4()}"
    forged = TestClient(app).post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim, signature="0" * 64),
        json={"user": "conversation", "messages": [{"role": "user", "content": "你好"}]},
    )
    assert forged.status_code == 401

    caplog.set_level(logging.INFO)
    valid = TestClient(app).post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"user": "conversation", "messages": [{"role": "user", "content": "你好"}]},
    )
    assert valid.status_code == 200
    with SessionLocal() as db:
        mapping = db.query(ExternalIdentity).order_by(ExternalIdentity.created_at.desc()).first()
        assert mapping is not None
        assert mapping.subject_id.startswith("usr_")
        assert claim not in mapping.claim_fingerprint
        persisted_text = " ".join(
            str(value)
            for row in db.query(QuestionnaireSession).all()
            for value in (row.student_id, row.messages, row.portrait)
        )
        assert QXD_BEARER not in persisted_text
        assert claim not in persisted_text
    assert QXD_BEARER not in caplog.text


def test_unverified_qxd_user_is_request_isolated_and_web_cannot_read_qxd_session():
    client = TestClient(app)
    before: set[str]
    with SessionLocal() as db:
        before = {
            row.session_id
            for row in db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.student_id.like("qreq_%"))
            .all()
        }
    payload = {
        "user": "self-asserted-user",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": False,
    }
    assert client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(),
        json=payload,
    ).status_code == 200
    assert client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(),
        json=payload,
    ).status_code == 200
    with SessionLocal() as db:
        created = [
            row
            for row in db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.student_id.like("qreq_%"))
            .all()
            if row.session_id not in before
        ]
    assert len(created) == 2
    assert created[0].student_id != created[1].student_id

    web, _ = _web_client()
    assert web.get(f"/api/interviews/{created[0].session_id}").status_code == 403


def test_private_docx_and_pdf_validation_sanitization_and_object_authorization():
    owner, owner_headers = _web_client()
    other, other_headers = _web_client()

    docx = _upload_docx(owner, owner_headers, filename="../我的 简历.docx")
    assert docx.status_code == 200
    item = docx.json()
    assert item["original_name"] == "我的 简历.docx"
    assert item["text_preview"] == "私有简历正文"
    assert not {"url", "path", "stored_name"} & set(item)

    pdf = owner.post(
        "/api/documents",
        headers=owner_headers,
        files={"file": ("resume.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert pdf.status_code == 200

    wrong_mime = owner.post(
        "/api/documents",
        headers=owner_headers,
        files={"file": ("resume.pdf", _pdf_bytes(), "text/plain")},
    )
    assert wrong_mime.status_code == 415
    wrong_magic = owner.post(
        "/api/documents",
        headers=owner_headers,
        files={"file": ("resume.pdf", b"not-pdf", "application/pdf")},
    )
    assert wrong_magic.status_code == 415
    wrong_extension = owner.post(
        "/api/documents",
        headers=owner_headers,
        files={"file": ("resume.txt", b"text", "text/plain")},
    )
    assert wrong_extension.status_code == 415
    malformed_docx = owner.post(
        "/api/documents",
        headers=owner_headers,
        files={
            "file": (
                "resume.docx",
                b"PK-not-a-zip",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert malformed_docx.status_code == 422

    document_id = item["document_id"]
    assert other.get(f"/api/documents/{document_id}").status_code == 403
    assert other.request(
        "DELETE",
        f"/api/documents/{document_id}",
        headers=_idem(other_headers),
        json={"confirm_delete": True},
    ).status_code == 403
    assert owner.request(
        "DELETE",
        f"/api/documents/{document_id}",
        headers=_idem(owner_headers),
        json={"confirm_delete": True},
    ).status_code == 200


def test_private_upload_size_limit_fails_before_parsing(monkeypatch):
    client, headers = _web_client()
    monkeypatch.setattr(settings, "PRIVATE_UPLOAD_MAX_BYTES", 16)
    response = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("large.pdf", b"%PDF-" + b"x" * 20, "application/pdf")},
    )
    assert response.status_code == 413


def test_application_is_in_app_only_and_all_operations_are_owner_scoped():
    owner, owner_headers = _web_client()
    other, other_headers = _web_client()
    document = _upload_docx(owner, owner_headers).json()

    with SessionLocal() as db:
        recruitment = Recruitment(
            publisher_id=f"reviewer_{uuid.uuid4().hex}",
            publisher_type="advisor",
            type="科研助理",
            title="审核通过的测试招募",
            req="仅用于本地授权回归",
            major="测试",
            deadline=date(2027, 1, 1),
            is_urgent=False,
            review_status="verified",
            publication_status="published",
            authorization_basis="explicit_consent",
            provenance={},
            governance={},
            quarantined_fields={},
        )
        db.add(recruitment)
        db.commit()
        db.refresh(recruitment)
        recruit_id = recruitment.recruit_id

    created = owner.post(
        "/api/applications",
        headers=_idem(owner_headers),
        json={
            "recruit_id": recruit_id,
            "document_id": document["document_id"],
            "confirm_in_app_only": True,
        },
    )
    assert created.status_code == 200
    record = created.json()
    assert record["delivery"] == "in_app_only_no_external_delivery"
    assert record["status"] == "submitted_in_app"
    assert "student_id" not in record

    app_id = record["app_id"]
    assert other.get(f"/api/applications/{app_id}").status_code == 403
    assert other.patch(
        f"/api/applications/{app_id}",
        headers=other_headers,
        json={"status": "withdrawn"},
    ).status_code == 403
    assert other.delete(
        f"/api/applications/{app_id}",
        headers=other_headers,
    ).status_code == 403
    withdrawn = owner.patch(
        f"/api/applications/{app_id}",
        headers=owner_headers,
        json={"status": "withdrawn"},
    )
    assert withdrawn.status_code == 200
    assert owner.delete(
        f"/api/applications/{app_id}",
        headers=owner_headers,
    ).status_code == 200
    with SessionLocal() as db:
        published = db.get(Recruitment, recruit_id)
        if published is not None:
            db.delete(published)
            db.commit()


def test_client_supplied_identity_fields_are_rejected():
    client, headers = _web_client()
    recruitment = client.post(
        "/api/recruitments",
        headers=headers,
        json={
            "publisher_id": "forged",
            "type": "招生",
            "title": "伪造发布者",
            "req": "应被拒绝",
            "major": "测试",
            "deadline": "2027-01-01",
        },
    )
    assert recruitment.status_code == 422
    feedback = client.post(
        "/api/feedback",
        headers=headers,
        json={"student_id": "forged", "advisor_id": "x", "rating": 1},
    )
    assert feedback.status_code == 422


def test_match_result_limit_is_hard_capped_and_home_does_not_fetch_all_mentors():
    client, headers = _web_client()
    invalid = client.post(
        "/api/match",
        headers=headers,
        json={"session_id": str(uuid.uuid4()), "ranking": {"result_limit": 21}},
    )
    assert invalid.status_code == 422

    root = Path(__file__).resolve().parents[2]
    store_source = (root / "frontend/src/stores/useAdvisorStore.ts").read_text(
        encoding="utf-8"
    )
    load_all_body = store_source.split("async function loadAll()", 1)[1].split(
        "async function match", 1
    )[0]
    assert "fetchAdvisors" not in load_all_body
    assert "fetchScatter" in load_all_body


def test_frontend_runtime_has_no_legacy_identity_or_external_contact_paths():
    root = Path(__file__).resolve().parents[2] / "frontend/src"
    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.suffix in {".ts", ".vue"}
    )
    for forbidden in (
        "X-Student-Token",
        "mailto:",
        "模拟登录",
        "SSO 占位",
        "student_id",
        "'anonymous'",
        '"anonymous"',
        "localStorage",
        "加密存储",
    ):
        assert forbidden not in runtime


def test_frontend_web_session_and_interview_rendering_regressions():
    root = Path(__file__).resolve().parents[2] / "frontend"
    development_env = (root / ".env.development").read_text(encoding="utf-8")
    api_base_lines = [
        line.strip()
        for line in development_env.splitlines()
        if line.strip().startswith("VITE_API_BASE=")
    ]
    assert api_base_lines == ["VITE_API_BASE="]

    chat_api = (root / "src/api/chat.ts").read_text(encoding="utf-8")
    assert "/api/v1/llm/chat?stream=false" in chat_api
    assert "getReader()" not in chat_api

    chat_store = (root / "src/stores/useChatStore.ts").read_text(encoding="utf-8")
    assert "return messages.value[messages.value.length - 1]" in chat_store
