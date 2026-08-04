"""A6 幂等、CSRF、解析预算、生产门、审计与跨事务不变量。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.core.security_validation import (
    decode_secret_material,
    validate_production_secrets,
)
from app.db.session import SessionLocal
from app.main import app
from app.models.application import Application
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.idempotency import IdempotencyRecord
from app.models.private_document import (
    ArtifactDeliveryGrant,
    DeletedArtifactTombstone,
    PrivateDocument,
)
from app.models.recruitment import Recruitment
from app.schemas.actions import ApplicationCreateRequest, DocumentDeleteRequest
from app.schemas.artifacts import (
    DownloadGrantRequest,
    MatchReportArtifactRequest,
    ResumeArtifactRequest,
)
from app.schemas.resume import ResumeSubmitRequest
import app.services.artifact_generation as artifact_generation_service
import app.services.artifact_audit as artifact_audit_service
import app.services.idempotency as idempotency_service
from app.services.applications import create_in_app_application
from app.services.artifact_delivery import assert_qxd_delivery_ready
from app.services.idempotency import (
    idempotency_key_digest,
    request_fingerprint,
)
from app.services.document_locking import private_document_lock_statement
from app.services.private_documents import (
    delete_private_document_consistently,
    read_private_document_bytes,
)

QXD_BEARER = "test-qxd-key"
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"


def _web_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    assert client.get("/api/session").status_code == 200
    return client, {"X-CSRF-Token": client.cookies["tsing_radar_csrf"]}


def _clone_client(source: TestClient) -> TestClient:
    clone = TestClient(app)
    clone.cookies.update(source.cookies)
    return clone


def _idem(headers: dict[str, str], key: str) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key}


def _minimal_docx(text: str = "A6 private document") -> bytes:
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


def _upload_docx(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "审计测试简历.docx",
) -> dict:
    response = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                name,
                _minimal_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _resume_payload(name: str = "幂等测试同学", fmt: str = "docx") -> dict:
    return {
        "student_name": name,
        "dept": "自动化系",
        "email": "idempotency@example.edu",
        "phone": "",
        "education": "本科",
        "research_interests": ["机器人"],
        "projects": [],
        "awards": [],
        "positions": [],
        "format": fmt,
        "confirm_generation": True,
    }


def _confirmed_interview(
    client: TestClient,
    headers: dict[str, str],
) -> str:
    session_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/llm/chat",
        params={"stream": "false"},
        headers=headers,
        json={
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": "自然语言处理、对话系统"},
                {"role": "user", "content": "工程落地"},
                {"role": "user", "content": "高频具体指导"},
                {"role": "user", "content": "产业就业"},
                {"role": "user", "content": "成熟稳妥路线"},
                {"role": "user", "content": "无"},
                {"role": "user", "content": "确认画像"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    return session_id


def _parallel_posts(
    client: TestClient,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict,
    workers: int = 2,
) -> list:
    barrier = threading.Barrier(workers)

    def run(_index: int):
        clone = _clone_client(client)
        barrier.wait()
        return clone.post(url, headers=headers, json=payload)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, range(workers)))


def _create_recruitment() -> str:
    with SessionLocal() as db:
        recruitment = Recruitment(
            publisher_id=f"reviewer_{uuid.uuid4().hex}",
            publisher_type="advisor",
            type="科研助理",
            title="A6 并发测试招募",
            req="仅用于本地并发回归",
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
        return recruitment.recruit_id


def _pdf_pages(page_count: int, text: str = "boundary") -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pageCompression=1)
    for _index in range(page_count):
        document.drawString(72, 720, text)
        document.showPage()
    document.save()
    return output.getvalue()


def _storage_files() -> set[Path]:
    root = Path(settings.object_storage_local_root)
    return {item for item in root.rglob("*") if item.is_file()} if root.exists() else set()


def test_resume_and_report_idempotency_replay_concurrency_and_payload_conflict():
    client, headers = _web_client()
    resume_key = f"resume:{uuid.uuid4()}"
    payload = _resume_payload()
    responses = _parallel_posts(
        client,
        url="/api/resume/generate",
        headers=_idem(headers, resume_key),
        payload=payload,
    )
    assert [response.status_code for response in responses] == [200, 200]
    document_ids = {response.json()["document_id"] for response in responses}
    assert len(document_ids) == 1
    replay = client.post(
        "/api/resume/generate",
        headers=_idem(headers, resume_key),
        json=payload,
    )
    assert replay.status_code == 200
    assert replay.json()["document_id"] in document_ids
    conflict = client.post(
        "/api/resume/generate",
        headers=_idem(headers, resume_key),
        json={**payload, "student_name": "不同同学"},
    )
    assert conflict.status_code == 409
    with SessionLocal() as db:
        assert (
            db.query(PrivateDocument)
            .filter(PrivateDocument.document_id.in_(document_ids))
            .count()
            == 1
        )

    session_id = _confirmed_interview(client, headers)
    report_key = f"report:{uuid.uuid4()}"
    report_payload = {
        "session_id": session_id,
        "format": "docx",
        "confirm_generation": True,
    }
    reports = _parallel_posts(
        client,
        url="/api/artifacts/match-report",
        headers=_idem(headers, report_key),
        payload=report_payload,
    )
    assert [response.status_code for response in reports] == [200, 200]
    assert len({response.json()["document_id"] for response in reports}) == 1
    changed = client.post(
        "/api/artifacts/match-report",
        headers=_idem(headers, report_key),
        json={**report_payload, "format": "pdf"},
    )
    assert changed.status_code == 409


def test_generation_render_failure_is_recorded_without_object_and_new_key_retries(
    monkeypatch,
):
    client, headers = _web_client()
    before_documents = 0
    with SessionLocal() as db:
        before_documents = db.query(PrivateDocument).count()
    before_objects = _storage_files()
    payload = _resume_payload(name="渲染失败测试")
    key = f"resume-render-failure:{uuid.uuid4()}"
    operation = "generate_resume:web"
    digest = idempotency_key_digest(operation, key)
    original = artifact_generation_service._render_resume_docx

    def fail_render(_request):
        raise RuntimeError("template exploded with private input")

    monkeypatch.setattr(
        artifact_generation_service,
        "_render_resume_docx",
        fail_render,
    )
    failed = client.post(
        "/api/resume/generate",
        headers=_idem(headers, key),
        json=payload,
    )
    assert failed.status_code == 503
    replay = client.post(
        "/api/resume/generate",
        headers=_idem(headers, key),
        json=payload,
    )
    assert replay.status_code == 503
    assert replay.json() == failed.json()
    with SessionLocal() as db:
        record = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key_digest == digest)
            .one()
        )
        assert record.status == "failed"
        assert record.response_status == 503
        assert (
            db.query(ArtifactAuditEvent)
            .filter(
                ArtifactAuditEvent.idempotency_key_digest == digest,
                ArtifactAuditEvent.event_type == "generate_failed",
                ArtifactAuditEvent.reason_code == "generation_failed",
            )
            .count()
            == 1
        )
        assert db.query(PrivateDocument).count() == before_documents
    assert _storage_files() == before_objects

    monkeypatch.setattr(
        artifact_generation_service,
        "_render_resume_docx",
        original,
    )
    retried = client.post(
        "/api/resume/generate",
        headers=_idem(headers, f"resume-render-retry:{uuid.uuid4()}"),
        json=payload,
    )
    assert retried.status_code == 200, retried.text


def test_match_report_render_failure_is_recorded_and_replay_is_stable(monkeypatch):
    client, headers = _web_client()
    session_id = _confirmed_interview(client, headers)
    payload = {
        "session_id": session_id,
        "format": "docx",
        "confirm_generation": True,
    }
    key = f"report-render-failure:{uuid.uuid4()}"
    operation = "generate_match_report:web"
    digest = idempotency_key_digest(operation, key)
    before_objects = _storage_files()
    with SessionLocal() as db:
        before_documents = db.query(PrivateDocument).count()
    original = artifact_generation_service._render_match_report_docx

    def fail_render(_profile, _outcome):
        raise MemoryError("synthetic report render budget failure")

    monkeypatch.setattr(
        artifact_generation_service,
        "_render_match_report_docx",
        fail_render,
    )
    failed = client.post(
        "/api/artifacts/match-report",
        headers=_idem(headers, key),
        json=payload,
    )
    assert failed.status_code == 503
    replay = client.post(
        "/api/artifacts/match-report",
        headers=_idem(headers, key),
        json=payload,
    )
    assert replay.status_code == 503
    assert replay.json() == failed.json()
    with SessionLocal() as db:
        record = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key_digest == digest)
            .one()
        )
        assert record.status == "failed"
        assert db.query(PrivateDocument).count() == before_documents
    assert _storage_files() == before_objects

    monkeypatch.setattr(
        artifact_generation_service,
        "_render_match_report_docx",
        original,
    )
    retried = client.post(
        "/api/artifacts/match-report",
        headers=_idem(headers, f"report-render-retry:{uuid.uuid4()}"),
        json=payload,
    )
    assert retried.status_code == 200, retried.text


def test_stale_processing_key_is_atomically_failed_and_new_key_can_retry():
    client, headers = _web_client()
    owner_document = _upload_docx(client, headers)
    with SessionLocal() as db:
        owner = db.get(
            PrivateDocument,
            owner_document["document_id"],
        ).owner_subject_id
    payload = _resume_payload(name="陈旧幂等恢复")
    key = f"stale-resume:{uuid.uuid4()}"
    operation = "generate_resume:web"
    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.IDEMPOTENCY_PROCESSING_TTL_SECONDS + 5
    )
    record_id = str(uuid.uuid4())
    record = IdempotencyRecord(
        idempotency_id=record_id,
        owner_subject_id=owner,
        operation=operation,
        key_digest=idempotency_key_digest(operation, key),
        request_fingerprint=request_fingerprint(
            ResumeArtifactRequest(**payload).model_dump(mode="json")
        ),
        attempt_digest=hashlib.sha256(b"abandoned-attempt").hexdigest(),
        status="processing",
        created_at=stale_at,
        updated_at=stale_at,
    )
    with SessionLocal() as db:
        db.add(record)
        db.commit()

    started = time.monotonic()
    recovered = client.post(
        "/api/resume/generate",
        headers=_idem(headers, key),
        json=payload,
    )
    assert recovered.status_code == 503
    assert time.monotonic() - started < 2
    with SessionLocal() as db:
        persisted = db.get(IdempotencyRecord, record_id)
        assert persisted.status == "failed"
        assert persisted.completed_at is not None
        assert persisted.response_status == 503
    retried = client.post(
        "/api/resume/generate",
        headers=_idem(headers, f"stale-resume-retry:{uuid.uuid4()}"),
        json=payload,
    )
    assert retried.status_code == 200, retried.text


def test_reclaimed_generation_lease_fences_late_worker_and_removes_old_object(
    monkeypatch,
):
    client, headers = _web_client()
    payload = _resume_payload(name="租约围栏交错")
    old_key = f"fenced-old:{uuid.uuid4()}"
    new_key = f"fenced-new:{uuid.uuid4()}"
    operation = "generate_resume:web"
    old_digest = idempotency_key_digest(operation, old_key)
    new_digest = idempotency_key_digest(operation, new_key)
    before_objects = _storage_files()
    with SessionLocal() as db:
        before_documents = db.query(PrivateDocument).count()

    old_claimed = threading.Event()
    release_old = threading.Event()
    render_lock = threading.Lock()
    first_render = True
    original_render = artifact_generation_service._render_resume_docx

    def pause_first_render(request):
        nonlocal first_render
        with render_lock:
            should_pause = first_render
            first_render = False
        if should_pause:
            old_claimed.set()
            assert release_old.wait(10)
        return original_render(request)

    monkeypatch.setattr(
        artifact_generation_service,
        "_render_resume_docx",
        pause_first_render,
    )
    old_responses = []

    def run_old_worker():
        clone = _clone_client(client)
        old_responses.append(
            clone.post(
                "/api/resume/generate",
                headers=_idem(headers, old_key),
                json=payload,
            )
        )

    old_thread = threading.Thread(target=run_old_worker)
    old_thread.start()
    assert old_claimed.wait(10)
    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.IDEMPOTENCY_PROCESSING_TTL_SECONDS + 5
    )
    with SessionLocal() as db:
        record = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key_digest == old_digest)
            .one()
        )
        record.updated_at = stale_at
        db.commit()

    reclaimed = client.post(
        "/api/resume/generate",
        headers=_idem(headers, old_key),
        json=payload,
    )
    assert reclaimed.status_code == 503
    replacement = client.post(
        "/api/resume/generate",
        headers=_idem(headers, new_key),
        json=payload,
    )
    assert replacement.status_code == 200, replacement.text

    release_old.set()
    old_thread.join(15)
    assert not old_thread.is_alive()
    assert len(old_responses) == 1
    assert old_responses[0].status_code == 409

    with SessionLocal() as db:
        old_record = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key_digest == old_digest)
            .one()
        )
        new_record = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key_digest == new_digest)
            .one()
        )
        assert old_record.status == "failed"
        assert old_record.resource_id is None
        assert new_record.status == "completed"
        assert new_record.resource_id == replacement.json()["document_id"]
        assert db.query(PrivateDocument).count() == before_documents + 1
        old_success_events = (
            db.query(ArtifactAuditEvent)
            .filter(
                ArtifactAuditEvent.idempotency_key_digest == old_digest,
                ArtifactAuditEvent.event_type == "generate_completed",
            )
            .count()
        )
        assert old_success_events == 0
    assert len(_storage_files()) == len(before_objects) + 1


def test_stale_recovery_and_normal_completion_are_single_winner():
    owner = f"usr_{uuid.uuid4().hex}"
    operation = "lease-race"
    key = f"lease-race:{uuid.uuid4()}"
    with SessionLocal() as db:
        claim = idempotency_service.begin_idempotency(
            db,
            owner_subject_id=owner,
            operation=operation,
            key=key,
            payload={"value": 1},
        )
        record_id = claim.record.idempotency_id
        attempt_token = claim.attempt_token
    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.IDEMPOTENCY_PROCESSING_TTL_SECONDS + 5
    )
    with SessionLocal() as db:
        record = db.get(IdempotencyRecord, record_id)
        record.updated_at = stale_at
        db.commit()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def complete_worker():
        with SessionLocal() as db:
            record = db.get(IdempotencyRecord, record_id)
            barrier.wait()
            try:
                idempotency_service.complete_idempotency(
                    db,
                    record=record,
                    attempt_token=attempt_token,
                    resource_type="synthetic",
                    resource_id="winner",
                )
                outcomes.append("completed")
            except HTTPException:
                db.rollback()
                outcomes.append("complete_fenced")

    def recover_worker():
        with SessionLocal() as db:
            barrier.wait()
            recovered = idempotency_service._fail_stale_processing(
                db,
                owner_subject_id=owner,
                operation=operation,
                key_digest=idempotency_key_digest(operation, key),
            )
            outcomes.append("recovered" if recovered else "recovery_lost")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(complete_worker),
            pool.submit(recover_worker),
        ]
        for future in futures:
            future.result(timeout=10)
    assert sorted(outcomes) in (
        ["complete_fenced", "recovered"],
        ["completed", "recovery_lost"],
    )
    with SessionLocal() as db:
        persisted = db.get(IdempotencyRecord, record_id)
        if persisted.status == "completed":
            assert persisted.resource_id == "winner"
            assert outcomes.count("completed") == 1
        else:
            assert persisted.status == "failed"
            assert persisted.resource_id is None
            assert outcomes.count("recovered") == 1


def test_grant_idempotency_csrf_post_blob_and_single_consumption():
    client, headers = _web_client()
    first = _upload_docx(client, headers)
    second = _upload_docx(client, headers, name="另一个文件.docx")
    key = f"grant:{uuid.uuid4()}"
    url = f"/api/artifacts/{first['document_id']}/download-grant"
    responses = _parallel_posts(
        client,
        url=url,
        headers=_idem(headers, key),
        payload={"confirm_private_download": True},
    )
    assert [response.status_code for response in responses] == [200, 200]
    grant_urls = {response.json()["download_url"] for response in responses}
    assert len(grant_urls) == 1
    download_url = grant_urls.pop()
    conflict = client.post(
        f"/api/artifacts/{second['document_id']}/download-grant",
        headers=_idem(headers, key),
        json={"confirm_private_download": True},
    )
    assert conflict.status_code == 409
    with SessionLocal() as db:
        active = (
            db.query(ArtifactDeliveryGrant)
            .filter(
                ArtifactDeliveryGrant.document_id == first["document_id"],
                ArtifactDeliveryGrant.audience == "web_private",
                ArtifactDeliveryGrant.revoked.is_(False),
            )
            .all()
        )
        assert len(active) == 1
        grant_id = active[0].grant_id

    assert client.get(download_url).status_code == 405
    assert client.post(download_url).status_code == 403
    assert (
        client.post(
            download_url,
            headers={"X-CSRF-Token": "wrong"},
        ).status_code
        == 403
    )
    with SessionLocal() as db:
        assert db.get(ArtifactDeliveryGrant, grant_id).use_count == 0

    downloaded = client.post(download_url, headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK\x03\x04")
    assert downloaded.headers["x-artifact-sha256"] == hashlib.sha256(
        downloaded.content
    ).hexdigest()
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
    assert client.post(download_url, headers=headers).status_code == 410


def test_application_idempotency_and_database_active_uniqueness():
    client, headers = _web_client()
    document = _upload_docx(client, headers)
    other_document = _upload_docx(client, headers, name="第二份简历.docx")
    recruit_id = _create_recruitment()
    key = f"application:{uuid.uuid4()}"
    payload = {
        "recruit_id": recruit_id,
        "document_id": document["document_id"],
        "confirm_in_app_only": True,
    }
    responses = _parallel_posts(
        client,
        url="/api/applications",
        headers=_idem(headers, key),
        payload=payload,
    )
    assert [response.status_code for response in responses] == [200, 200]
    app_ids = {response.json()["app_id"] for response in responses}
    assert len(app_ids) == 1
    changed = client.post(
        "/api/applications",
        headers=_idem(headers, key),
        json={**payload, "document_id": other_document["document_id"]},
    )
    assert changed.status_code == 409

    different_keys = []
    barrier = threading.Barrier(2)

    def create_with_new_key(_index: int):
        clone = _clone_client(client)
        barrier.wait()
        return clone.post(
            "/api/applications",
            headers=_idem(headers, f"new-application:{uuid.uuid4()}"),
            json=payload,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        different_keys = list(pool.map(create_with_new_key, range(2)))
    assert all(response.status_code == 409 for response in different_keys)
    with SessionLocal() as db:
        assert (
            db.query(Application)
            .filter(
                Application.student_id
                == db.get(Application, next(iter(app_ids))).student_id,
                Application.recruit_id == recruit_id,
                Application.resume_id == document["document_id"],
                Application.status != "withdrawn",
            )
            .count()
            == 1
        )


@pytest.mark.parametrize("invalid", [1, "true"])
def test_confirmation_contracts_are_strict_booleans(invalid):
    resume = _resume_payload()
    with pytest.raises(ValidationError):
        ResumeArtifactRequest(**{**resume, "confirm_generation": invalid})
    with pytest.raises(ValidationError):
        MatchReportArtifactRequest(
            session_id="session",
            format="pdf",
            confirm_generation=invalid,
        )
    with pytest.raises(ValidationError):
        DownloadGrantRequest(confirm_private_download=invalid)
    with pytest.raises(ValidationError):
        ApplicationCreateRequest(
            recruit_id="recruit",
            document_id="document",
            confirm_in_app_only=invalid,
        )
    with pytest.raises(ValidationError):
        ResumeSubmitRequest(
            recruit_id="recruit",
            document_id="document",
            confirm_in_app_only=invalid,
        )
    with pytest.raises(ValidationError):
        DocumentDeleteRequest(confirm_delete=invalid)


def test_all_a6_mutations_require_persistent_idempotency_header():
    client, headers = _web_client()
    resume = client.post(
        "/api/resume/generate",
        headers=headers,
        json=_resume_payload(),
    )
    assert resume.status_code == 400

    document = _upload_docx(client, headers)
    grant = client.post(
        f"/api/artifacts/{document['document_id']}/download-grant",
        headers=headers,
        json={"confirm_private_download": True},
    )
    assert grant.status_code == 400
    deletion = client.request(
        "DELETE",
        f"/api/documents/{document['document_id']}",
        headers=headers,
        json={"confirm_delete": True},
    )
    assert deletion.status_code == 400

    recruit_id = _create_recruitment()
    application = client.post(
        "/api/applications",
        headers=headers,
        json={
            "recruit_id": recruit_id,
            "document_id": document["document_id"],
            "confirm_in_app_only": True,
        },
    )
    assert application.status_code == 400


def test_pdf_page_and_text_budgets_fail_closed_and_boundary_succeeds(monkeypatch):
    client, headers = _web_client()
    before_documents = 0
    with SessionLocal() as db:
        before_documents = db.query(PrivateDocument).count()
    before_objects = _storage_files()

    monkeypatch.setattr(settings, "PDF_MAX_PAGES", 2)
    too_many = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "too-many-pages.pdf",
                _pdf_pages(3),
                "application/pdf",
            )
        },
    )
    assert too_many.status_code == 413

    monkeypatch.setattr(settings, "PDF_MAX_PAGES", 5)
    monkeypatch.setattr(settings, "PDF_MAX_PAGE_TEXT_CHARS", 200)
    monkeypatch.setattr(settings, "PDF_MAX_EXTRACTED_TEXT_CHARS", 300)
    compressed = _pdf_pages(1, "A" * 10_000)
    assert len(compressed) < 8_000
    text_bomb = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("compressed.pdf", compressed, "application/pdf")},
    )
    assert text_bomb.status_code == 413

    monkeypatch.setattr(settings, "PDF_MAX_PAGE_TEXT_CHARS", 10_000)
    monkeypatch.setattr(settings, "PDF_MAX_EXTRACTED_TEXT_CHARS", 10_000)
    boundary = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "中文临界正常.pdf",
                _pdf_pages(5, "normal"),
                "application/pdf",
            )
        },
    )
    assert boundary.status_code == 200, boundary.text
    with SessionLocal() as db:
        assert db.query(PrivateDocument).count() == before_documents + 1
    assert len(_storage_files()) == len(before_objects) + 1


def test_upload_oversize_and_empty_rejections_are_audited_without_residue(
    monkeypatch,
):
    client, headers = _web_client()
    with SessionLocal() as db:
        before_documents = db.query(PrivateDocument).count()
        before_events = (
            db.query(ArtifactAuditEvent.sequence_id)
            .order_by(ArtifactAuditEvent.sequence_id.desc())
            .limit(1)
            .scalar()
            or 0
        )
    before_objects = _storage_files()
    monkeypatch.setattr(settings, "PRIVATE_UPLOAD_MAX_BYTES", 32)
    oversize_name = "张三-13800000000-超限.pdf"
    oversize = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                oversize_name,
                b"%PDF-" + b"A" * 32,
                "application/pdf",
            )
        },
    )
    assert oversize.status_code == 413
    empty_name = "李四-秘密空文件.docx"
    empty = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                empty_name,
                b"",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert empty.status_code == 422
    with SessionLocal() as db:
        assert db.query(PrivateDocument).count() == before_documents
        events = (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.sequence_id > before_events)
            .order_by(ArtifactAuditEvent.sequence_id)
            .all()
        )
    assert [event.event_type for event in events] == [
        "upload_rejected",
        "upload_rejected",
    ]
    assert all(
        event.reason_code == "compressed_size_limit_or_empty"
        for event in events
    )
    serialized = json.dumps(
        [
            {
                "operation": event.operation,
                "event_type": event.event_type,
                "reason_code": event.reason_code,
                "document_id": event.document_id,
            }
            for event in events
        ],
        ensure_ascii=False,
    )
    assert oversize_name not in serialized
    assert empty_name not in serialized
    assert _storage_files() == before_objects


def test_rejection_fails_closed_when_audit_event_cannot_be_persisted(
    monkeypatch,
):
    client, headers = _web_client()
    before_objects = _storage_files()
    with SessionLocal() as db:
        before_documents = db.query(PrivateDocument).count()

    def fail_audit_write(*_args, **_kwargs):
        raise RuntimeError("synthetic audit database outage")

    monkeypatch.setattr(
        artifact_audit_service,
        "add_artifact_event",
        fail_audit_write,
    )
    monkeypatch.setattr(settings, "PRIVATE_UPLOAD_MAX_BYTES", 16)
    rejected = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "private-name.pdf",
                b"%PDF-" + b"A" * 16,
                "application/pdf",
            )
        },
    )
    assert rejected.status_code == 503
    with SessionLocal() as db:
        assert db.query(PrivateDocument).count() == before_documents
    assert _storage_files() == before_objects


@pytest.mark.parametrize("size", [1, 16, 31])
def test_production_secret_minimum_decoded_bytes(size):
    with pytest.raises(RuntimeError, match="32"):
        decode_secret_material("TEST_SECRET", "x" * size)


def test_production_secret_encoding_unicode_and_separation():
    random_bytes = bytes(range(32))
    encoded = "base64:" + base64.b64encode(random_bytes).decode()
    assert decode_secret_material("BASE64_SECRET", encoded) == random_bytes
    assert decode_secret_material("HEX_SECRET", "hex:" + random_bytes.hex()) == random_bytes
    assert len(decode_secret_material("UNICODE_SECRET", "密" * 11)) == 33
    with pytest.raises(RuntimeError, match="32"):
        decode_secret_material("UNICODE_SECRET", "密" * 10)
    with pytest.raises(RuntimeError, match="不同密钥"):
        validate_production_secrets(
            SimpleNamespace(
                ADMIN_TOKEN="a" * 32,
                SESSION_HMAC_SECRET="s" * 32,
                ARTIFACT_SIGNING_SECRET="s" * 32,
                    QXD_API_KEY="configured-qxd-bearer-" + "b" * 32,
                QXD_END_USER_SIGNING_SECRET="q" * 32,
            )
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost",
        "https://127.0.0.1",
        "https://10.1.2.3",
        "https://169.254.169.254",
        "https://metadata.google.internal",
        "https://agent.local",
        "https://singlelabel",
        "https://agent.test",
        "https://agent.example.edu",
    ],
)
def test_qxd_public_base_rejects_obviously_non_public_hosts(monkeypatch, url):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", url)
    monkeypatch.setattr(settings, "ALLOW_TEST_PUBLIC_BASE_URL", False)
    with pytest.raises(HTTPException) as exc_info:
        assert_qxd_delivery_ready()
    assert exc_info.value.status_code == 503


def test_debug_contract_domain_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://agent.example.edu")
    monkeypatch.setattr(settings, "ALLOW_TEST_PUBLIC_BASE_URL", True)
    assert_qxd_delivery_ready()


def test_invalid_qxd_base_fails_before_object_grant_or_attachment(monkeypatch):
    client = TestClient(app)
    claim = f"bad-base-{uuid.uuid4()}"
    signature = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        claim.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Authorization": f"Bearer {QXD_BEARER}",
        "X-QXD-End-User-Id": claim,
        "X-QXD-End-User-Signature": signature,
    }
    messages = [
        "自然语言处理",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
        "无",
        "确认画像",
        "生成匹配报告",
        "确认生成并通过清小搭附件交付",
    ]
    with SessionLocal() as db:
        before = (
            db.query(PrivateDocument).count(),
            db.query(ArtifactDeliveryGrant).count(),
        )
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://127.0.0.1")
    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": content}
                for content in messages
            ]
        },
    )
    assert response.status_code == 503
    with SessionLocal() as db:
        assert (
            db.query(PrivateDocument).count(),
            db.query(ArtifactDeliveryGrant).count(),
        ) == before


def test_artifact_audit_rejections_sequence_and_privacy(monkeypatch):
    client, headers = _web_client()
    with SessionLocal() as db:
        before_sequence = (
            db.query(ArtifactAuditEvent.sequence_id)
            .order_by(ArtifactAuditEvent.sequence_id.desc())
            .limit(1)
            .scalar()
            or 0
        )

    eicar_marker = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
        b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    eicar = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "PII-张三-13800000000.pdf",
                b"%PDF-1.4\n" + eicar_marker,
                "application/pdf",
            )
        },
    )
    assert eicar.status_code == 422
    malformed = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("秘密正文.pdf", b"%PDF-invalid", "application/pdf")},
    )
    assert malformed.status_code == 422
    monkeypatch.setattr(settings, "FILE_SCAN_MODE", "clamav")
    monkeypatch.setattr(settings, "CLAMAV_HOST", None)
    unavailable = client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "不应入库.docx",
                _minimal_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert unavailable.status_code == 503
    monkeypatch.setattr(settings, "FILE_SCAN_MODE", "builtin")

    document = _upload_docx(client, headers)
    grant_key = f"audit-grant:{uuid.uuid4()}"
    issued = client.post(
        f"/api/artifacts/{document['document_id']}/download-grant",
        headers=_idem(headers, grant_key),
        json={"confirm_private_download": True},
    )
    assert issued.status_code == 200
    token = issued.json()["download_url"].rsplit("/", 1)[-1]
    assert client.post(issued.json()["download_url"], headers=headers).status_code == 200
    deleted = client.request(
        "DELETE",
        f"/api/documents/{document['document_id']}",
        headers=_idem(headers, f"delete:{uuid.uuid4()}"),
        json={"confirm_delete": True},
    )
    assert deleted.status_code == 200

    with SessionLocal() as db:
        events = (
            db.query(ArtifactAuditEvent)
            .filter(ArtifactAuditEvent.sequence_id > before_sequence)
            .order_by(ArtifactAuditEvent.sequence_id)
            .all()
        )
        event_types = [event.event_type for event in events]
        assert "scan_rejected" in event_types
        assert "parse_rejected" in event_types
        assert "scan_unavailable" in event_types
        document_events = [
            event.event_type
            for event in events
            if event.document_id == document["document_id"]
        ]
        for required in (
            "scan_completed",
            "upload_completed",
            "grant_issued",
            "grant_consumed",
            "grant_redeemed",
            "delete_started",
            "delete_completed",
        ):
            assert required in document_events
        assert document_events.index("grant_issued") < document_events.index(
            "grant_redeemed"
        )
        assert document_events.index("delete_started") < document_events.index(
            "delete_completed"
        )
        serialized = json.dumps(
            [
                {
                    "owner_subject_id": event.owner_subject_id,
                    "operation": event.operation,
                    "idempotency_key_digest": event.idempotency_key_digest,
                    "document_id": event.document_id,
                    "event_type": event.event_type,
                    "outcome": event.outcome,
                    "reason_code": event.reason_code,
                    "scan_method": event.scan_method,
                }
                for event in events
            ],
            ensure_ascii=False,
        )
    for forbidden in (
        token,
        "PII-张三-13800000000.pdf",
        "秘密正文",
        "不应入库.docx",
        eicar_marker.decode(),
    ):
        assert forbidden not in serialized
    assert client.get("/api/artifact-audit-events").status_code == 404


def _race_fixture() -> tuple[dict, str, str]:
    client, headers = _web_client()
    item = _upload_docx(client, headers)
    recruit_id = _create_recruitment()
    with SessionLocal() as db:
        owner = db.get(PrivateDocument, item["document_id"]).owner_subject_id
    return item, owner, recruit_id


def _assert_application_delete_invariant(document_id: str) -> None:
    with SessionLocal() as db:
        active = (
            db.query(Application)
            .filter(
                Application.resume_id == document_id,
                Application.status != "withdrawn",
            )
            .all()
        )
        document = db.get(PrivateDocument, document_id)
        tombstone = db.get(DeletedArtifactTombstone, document_id)
        if active:
            assert len(active) == 1
            assert document is not None
            assert document.status == "ready"
            assert read_private_document_bytes(document)
            assert tombstone is None
        else:
            assert document is None
            assert tombstone is not None


def test_postgresql_lock_protocol_compiles_to_select_for_update():
    sql = str(
        private_document_lock_statement("document-id").compile(
            dialect=postgresql.dialect()
        )
    )
    assert "FOR UPDATE" in sql
    assert "private_documents.document_id" in sql


@pytest.mark.parametrize("first", ["application", "delete", "simultaneous"])
def test_application_and_delete_two_connection_invariant(monkeypatch, first):
    import app.services.applications as application_service
    import app.services.private_documents as document_service

    item, owner, recruit_id = _race_fixture()
    document_id = item["document_id"]
    results: list[tuple[str, int]] = []
    start = threading.Barrier(2) if first == "simultaneous" else None
    held = threading.Event()
    release = threading.Event()

    if first == "application":
        original = application_service.lock_private_document

        def hold_application_lock(db, target):
            locked = original(db, target)
            held.set()
            assert release.wait(5)
            return locked

        monkeypatch.setattr(
            application_service,
            "lock_private_document",
            hold_application_lock,
        )
    elif first == "delete":
        original = document_service.lock_private_document

        def hold_delete_lock(db, target):
            locked = original(db, target)
            held.set()
            assert release.wait(5)
            return locked

        monkeypatch.setattr(
            document_service,
            "lock_private_document",
            hold_delete_lock,
        )

    def run_application():
        if start:
            start.wait()
        with SessionLocal() as db:
            try:
                application = create_in_app_application(
                    db,
                    subject_id=owner,
                    recruit_id=recruit_id,
                    document_id=document_id,
                    confirmed=True,
                    idempotency_key=f"race-app:{uuid.uuid4()}",
                )
                results.append(("application", 200 if application else 500))
            except HTTPException as exc:
                results.append(("application", exc.status_code))

    def run_delete():
        if start:
            start.wait()
        with SessionLocal() as db:
            document = db.get(PrivateDocument, document_id)
            if document is None:
                results.append(("delete", 404))
                return
            try:
                delete_private_document_consistently(
                    db,
                    document=document,
                )
                results.append(("delete", 200))
            except HTTPException as exc:
                results.append(("delete", exc.status_code))

    application_thread = threading.Thread(target=run_application)
    delete_thread = threading.Thread(target=run_delete)
    if first == "delete":
        delete_thread.start()
        assert held.wait(5)
        application_thread.start()
        time.sleep(0.1)
        release.set()
    elif first == "application":
        application_thread.start()
        assert held.wait(5)
        delete_thread.start()
        time.sleep(0.1)
        release.set()
    else:
        application_thread.start()
        delete_thread.start()
    application_thread.join(10)
    delete_thread.join(10)
    assert not application_thread.is_alive()
    assert not delete_thread.is_alive()
    assert len(results) == 2
    _assert_application_delete_invariant(document_id)


def test_withdrawn_application_releases_document_for_delete():
    client, headers = _web_client()
    document = _upload_docx(client, headers)
    recruit_id = _create_recruitment()
    created = client.post(
        "/api/applications",
        headers=_idem(headers, f"apply:{uuid.uuid4()}"),
        json={
            "recruit_id": recruit_id,
            "document_id": document["document_id"],
            "confirm_in_app_only": True,
        },
    )
    assert created.status_code == 200
    app_id = created.json()["app_id"]
    assert (
        client.patch(
            f"/api/applications/{app_id}",
            headers=headers,
            json={"status": "withdrawn"},
        ).status_code
        == 200
    )
    deleted = client.request(
        "DELETE",
        f"/api/documents/{document['document_id']}",
        headers=_idem(headers, f"delete:{uuid.uuid4()}"),
        json={"confirm_delete": True},
    )
    assert deleted.status_code == 200, deleted.text
    with SessionLocal() as db:
        application = db.get(Application, app_id)
        assert application.status == "withdrawn"
        assert application.resume_id is None
        assert db.get(PrivateDocument, document["document_id"]) is None
        assert (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.owner_subject_id == application.student_id)
            .count()
            >= 1
        )
