"""A5 身份、对象授权、私有文件与前端隐私合同测试。"""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import re
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
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.identity import ExternalIdentity, IdentitySession
from app.models.private_document import PrivateDocument
from app.models.questionnaire_session import QuestionnaireSession
from app.models.recruitment import Recruitment
from app.services.recruitment_review import review_recruitment

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
    assert state["assistant_mode"] == "fixed_interview_with_optional_llm_enhancement"
    assert state["enhancement_status"] in {
        "available",
        "unavailable",
        "disabled",
    }
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
    # P-A：body user 字段由平台 Bearer 保护并稳定映射持久主体；
    # 不同 user 相互隔离，Web 会话无法读取清小搭会话。
    client = TestClient(app)

    def _subject(user: str) -> str:
        fingerprint = hashlib.sha256(
            f"qxd-user:{user}".encode("utf-8")
        ).hexdigest()
        with SessionLocal() as db:
            return (
                db.query(ExternalIdentity)
                .filter(
                    ExternalIdentity.provider == "qxd_user",
                    ExternalIdentity.claim_fingerprint == fingerprint,
                )
                .one()
                .subject_id
            )

    payload_a = {
        "user": "self-asserted-user-a",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": False,
    }
    payload_b = {**payload_a, "user": "self-asserted-user-b"}
    assert client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(),
        json=payload_a,
    ).status_code == 200
    assert client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(),
        json=payload_b,
    ).status_code == 200

    subject_a = _subject("self-asserted-user-a")
    subject_b = _subject("self-asserted-user-b")
    assert subject_a != subject_b

    with SessionLocal() as db:
        sessions = (
            db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.student_id.in_([subject_a, subject_b]))
            .all()
        )
    assert len(sessions) == 2
    assert {row.student_id for row in sessions} == {subject_a, subject_b}

    web, _ = _web_client()
    assert web.get(f"/api/interviews/{sessions[0].session_id}").status_code == 403


def test_private_docx_and_pdf_validation_sanitization_and_object_authorization():
    owner, owner_headers = _web_client()
    other, other_headers = _web_client()

    docx = _upload_docx(owner, owner_headers, filename="../我的 简历.docx")
    assert docx.status_code == 200
    item = docx.json()
    assert item["original_name"] == "我的 简历.docx"
    assert item["text_preview"] == ""
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


def test_declared_oversized_upload_is_rejected_before_multipart_parsing(
    monkeypatch,
):
    client, headers = _web_client()
    monkeypatch.setattr(settings, "PRIVATE_UPLOAD_MAX_BYTES", 16)
    response = client.post(
        "/api/documents",
        headers={**headers, "Content-Length": str(64 * 1024 + 17)},
        content=b"not-a-multipart-body",
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "文件超过大小限制"}


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


def test_recruitment_submission_mine_edit_resubmit_withdraw_and_idempotency():
    owner, owner_headers = _web_client()
    other, other_headers = _web_client()
    payload = {
        "type": "科研助理",
        "title": "内部审核流程测试",
        "req": "验证待审核、撤回和批准链路",
        "major": "测试",
        "deadline": "2027-01-01",
        "is_urgent": False,
    }
    create_headers = _idem(owner_headers)
    first = owner.post("/api/recruitments", headers=create_headers, json=payload)
    assert first.status_code == 200
    first_id = first.json()["recruit_id"]
    replay = owner.post("/api/recruitments", headers=create_headers, json=payload)
    assert replay.status_code == 200
    assert replay.json()["recruit_id"] == first_id
    mine = owner.get("/api/recruitments/mine").json()["data"][0]
    assert mine["review_status"] == "pending_review"
    assert mine["req"] == payload["req"]
    assert mine["major"] == payload["major"]
    assert mine["deadline"] == payload["deadline"]
    assert mine["is_urgent"] is False
    with SessionLocal() as db:
        review_recruitment(
            db,
            recruit_id=first_id,
            action="reject",
            reviewer="test-reviewer",
            reason="请补充职责",
        )
    revised = {**payload, "title": "修改后的内部审核流程测试", "submit_for_review": True}
    assert other.patch(
        f"/api/recruitments/{first_id}",
        headers=_idem(other_headers),
        json=revised,
    ).status_code == 403
    update_headers = _idem(owner_headers)
    updated = owner.patch(
        f"/api/recruitments/{first_id}",
        headers=update_headers,
        json=revised,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "pending_review"
    assert owner.patch(
        f"/api/recruitments/{first_id}",
        headers=update_headers,
        json=revised,
    ).json() == updated.json()
    with SessionLocal() as db:
        stored = db.get(Recruitment, first_id)
        assert stored is not None
        assert stored.title == revised["title"]
        assert stored.review_status == "pending_review"
        assert stored.publication_status == "restricted"
        assert stored.verified_at is None
        assert stored.governance["review_history"][-1]["reason"] == "请补充职责"
    assert other.delete(
        f"/api/recruitments/{first_id}", headers=_idem(other_headers)
    ).status_code == 403
    assert owner.delete(
        f"/api/recruitments/{first_id}", headers=_idem(owner_headers)
    ).status_code == 200
    assert first_id not in {
        item["recruit_id"]
        for item in owner.get("/api/recruitments/mine").json()["data"]
    }

    second = owner.post(
        "/api/recruitments",
        headers=_idem(owner_headers),
        json={**payload, "title": "审核批准流程测试"},
    )
    second_id = second.json()["recruit_id"]
    with SessionLocal() as db:
        reviewed = review_recruitment(
            db,
            recruit_id=second_id,
            action="approve",
            reviewer="test-reviewer",
            reason="fixture verified",
        )
        assert reviewed.authorization_basis == "publisher_submission_reviewed"
        assert reviewed.governance["review_history"][0]["reviewer"] == "test-reviewer"
    public_ids = {
        item["recruit_id"] for item in owner.get("/api/recruitments").json()["data"]
    }
    assert second_id in public_ids
    assert owner.delete(
        f"/api/recruitments/{second_id}", headers=_idem(owner_headers)
    ).status_code == 200
    public_ids = {
        item["recruit_id"] for item in owner.get("/api/recruitments").json()["data"]
    }
    assert second_id not in public_ids


def test_private_document_analysis_requires_owner_and_single_use_glm_consent(
    monkeypatch,
):
    owner, owner_headers = _web_client()
    other, other_headers = _web_client()
    text = (
        "姓名：测试同学\n"
        "邮箱：student@example.edu\n"
        "研究方向：自然语言处理、可信人工智能\n"
        "科研经历：完成校内检索项目\n"
        "奖项：一等奖、二等奖\n"
        "职务：班长\n"
        "未选择的秘密：do-not-send"
    )
    uploaded = owner.post(
        "/api/documents",
        headers=owner_headers,
        files={
            "file": (
                "facts.docx",
                _docx_bytes(text),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["document_id"]
    assert uploaded.json()["text_preview"] == ""
    with SessionLocal() as db:
        assert db.get(PrivateDocument, document_id).extracted_text == ""

    assert other.post(
        f"/api/documents/{document_id}/analysis",
        headers=other_headers,
        json={"confirm_private_parse": True},
    ).status_code == 403
    assert owner.post(
        f"/api/documents/{document_id}/analysis",
        headers=owner_headers,
        json={"confirm_private_parse": False},
    ).status_code == 422
    analyzed = owner.post(
        f"/api/documents/{document_id}/analysis",
        headers=owner_headers,
        json={"confirm_private_parse": True},
    )
    assert analyzed.status_code == 200
    analysis = analyzed.json()
    assert analysis["retention"] == "not_stored"
    assert analysis["external_model_called"] is False
    facts = {item["field"]: item["value"] for item in analysis["facts"]}
    assert facts["name"] == "测试同学"
    assert facts["email"] == "student@example.edu"
    assert facts["interest_tags"] == ["自然语言处理", "可信人工智能"]
    assert facts["awards"] == ["一等奖", "二等奖"]
    assert facts["positions"] == ["班长"]

    calls: list[str] = []

    async def fake_llm_complete(messages):
        calls.append(messages[0].content)
        return "仅基于所选片段的解读"

    import app.api.v1.documents as documents_api

    monkeypatch.setattr(documents_api, "llm_complete", fake_llm_complete)
    request = {
        "confirm_single_use": False,
        "selections": [
            {"field": "research_interest", "selected_text": "研究方向：自然语言处理、可信人工智能"}
        ],
    }
    denied = owner.post(
        f"/api/documents/{document_id}/interpretation",
        headers=owner_headers,
        json=request,
    )
    assert denied.status_code == 422
    assert calls == []
    assert other.post(
        f"/api/documents/{document_id}/interpretation",
        headers=other_headers,
        json={**request, "confirm_single_use": True},
    ).status_code == 403
    assert calls == []
    assert owner.post(
        f"/api/documents/{document_id}/interpretation",
        headers=owner_headers,
        json={
            "confirm_single_use": True,
            "selections": [
                {"field": "research_interest", "selected_text": "not-from-file"}
            ],
        },
    ).status_code == 422
    assert calls == []

    interpreted = owner.post(
        f"/api/documents/{document_id}/interpretation",
        headers=owner_headers,
        json={**request, "confirm_single_use": True},
    )
    assert interpreted.status_code == 200
    assert interpreted.json() == {
        "interpretation": "仅基于所选片段的解读",
        "provider": "glm",
        "retention": "not_stored",
    }
    assert len(calls) == 1
    assert "研究方向：自然语言处理、可信人工智能" in calls[0]
    assert "do-not-send" not in calls[0]
    with SessionLocal() as db:
        events = (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.document_id == document_id)
            .all()
        )
        event_text = " ".join(
            str(getattr(event, column.name))
            for event in events
            for column in ArtifactAuditEvent.__table__.columns
        )
    assert "自然语言处理" not in event_text
    assert "do-not-send" not in event_text
    assert {event.event_type for event in events} >= {
        "authorization_confirmed",
        "interpretation_completed",
    }

    assert owner.request(
        "DELETE",
        f"/api/documents/{document_id}",
        headers=_idem(owner_headers),
        json={"confirm_delete": True},
    ).status_code == 200


def test_client_supplied_identity_fields_are_rejected():
    client, headers = _web_client()
    recruitment = client.post(
        "/api/recruitments",
        headers=_idem(headers),
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
    assert "fetchMentorDistribution" in load_all_body
    assert "fetchScatter" not in load_all_body


def test_frontend_runtime_has_no_legacy_identity_or_external_contact_paths():
    root = Path(__file__).resolve().parents[2] / "frontend/src"
    sources = [
        path
        for path in root.rglob("*")
        if path.suffix in {".ts", ".vue"}
    ]
    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sources
    )
    for forbidden in (
        "X-Student-Token",
        "mailto:",
        "模拟登录",
        "SSO 占位",
        "student_id",
        "'anonymous'",
        '"anonymous"',
        "加密存储",
    ):
        assert forbidden not in runtime

    storage_module = root / "utils/browserStorage.ts"
    storage_source = storage_module.read_text(encoding="utf-8")
    assert "window.localStorage" in storage_source
    direct_storage_access = re.compile(r"(?:window\.)?localStorage\s*[.\[]")
    for path in sources:
        if path == storage_module:
            continue
        source = path.read_text(encoding="utf-8")
        assert direct_storage_access.search(source) is None, path


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
