#!/usr/bin/env python3
"""Real PostgreSQL two-connection invariants for DEP3."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

import app.services.applications as application_service
import app.services.private_documents as document_service
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.application import Application
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.idempotency import IdempotencyRecord
from app.models.private_document import (
    ArtifactDeliveryGrant,
    DeletedArtifactTombstone,
    PrivateDocument,
)
from app.models.recruitment import Recruitment
from app.services.applications import create_in_app_application
from app.services.artifact_delivery import (
    issue_delivery_grant,
    redeem_delivery_token,
)
from app.services.file_scanning import ScanResult
from app.services.identity import Principal
from app.services.object_storage import get_object_store_for_backend
from app.services.private_documents import (
    delete_private_document_consistently,
    read_private_document_bytes,
    store_private_artifact,
)


PDF_TYPE = "application/pdf"


def _owner() -> str:
    return f"dep3_pg_{uuid.uuid4().hex}"


def _document(
    owner: str,
    *,
    kind: str = "upload",
) -> PrivateDocument:
    payload = b"%PDF-1.4\nDEP3 synthetic PostgreSQL concurrency\n%%EOF"
    with SessionLocal() as db:
        return store_private_artifact(
            db,
            owner_subject_id=owner,
            original_name="dep3-concurrency.pdf",
            payload=payload,
            media_type=PDF_TYPE,
            document_kind=kind,
            extracted_text="DEP3 synthetic concurrency fixture",
            scan_result=ScanResult(
                status="clean",
                method="clamav-instream-plus-structural-v1",
                checked_at=datetime.now(timezone.utc),
            ),
        )


def _redeem(
    token: str,
    audience: str,
    principal: Principal | None,
    barrier: threading.Barrier,
) -> int:
    barrier.wait()
    with SessionLocal() as db:
        try:
            redeem_delivery_token(
                db,
                token=token,
                audience=audience,
                principal=principal,
            )
            return 200
        except HTTPException as exc:
            return exc.status_code


def verify_atomic_grants(owners: list[str]) -> None:
    web_owner = _owner()
    owners.append(web_owner)
    web_document = _document(web_owner)
    web_principal = Principal(
        subject_id=web_owner,
        channel="web",
        auth_session_id="dep3",
        persistent=True,
    )
    with SessionLocal() as db:
        issued = issue_delivery_grant(
            db,
            document=db.get(PrivateDocument, web_document.document_id),
            principal=web_principal,
            audience="web_private",
            confirmed=True,
            idempotency_key=f"dep3-web:{uuid.uuid4()}",
        )
    web_token = issued.download_url.rsplit("/", 1)[-1]
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: _redeem(
                    web_token,
                    "web_private",
                    web_principal,
                    barrier,
                ),
                range(2),
            )
        )
    assert results.count(200) == 1
    assert results.count(410) == 1
    with SessionLocal() as db:
        grant = (
            db.query(ArtifactDeliveryGrant)
            .filter(
                ArtifactDeliveryGrant.document_id
                == web_document.document_id
            )
            .one()
        )
        assert grant.use_count == 1 and grant.revoked is True

    qxd_owner = _owner()
    owners.append(qxd_owner)
    qxd_document = _document(qxd_owner, kind="match_report")
    qxd_principal = Principal(
        subject_id=qxd_owner,
        channel="qxd",
        auth_session_id=None,
        persistent=True,
    )
    settings.PUBLIC_BASE_URL = "https://agent.example.edu"
    settings.ALLOW_TEST_PUBLIC_BASE_URL = True
    with SessionLocal() as db:
        issued = issue_delivery_grant(
            db,
            document=db.get(PrivateDocument, qxd_document.document_id),
            principal=qxd_principal,
            audience="qxd_platform",
            confirmed=True,
            idempotency_key=f"dep3-qxd:{uuid.uuid4()}",
        )
    qxd_token = issued.download_url.rsplit("/", 1)[-1]
    barrier = threading.Barrier(6)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _index: _redeem(
                    qxd_token,
                    "qxd_platform",
                    None,
                    barrier,
                ),
                range(6),
            )
        )
    assert results.count(200) == 3
    assert results.count(410) == 3
    with SessionLocal() as db:
        grant = (
            db.query(ArtifactDeliveryGrant)
            .filter(
                ArtifactDeliveryGrant.document_id
                == qxd_document.document_id
            )
            .one()
        )
        assert grant.use_count == 3 and grant.revoked is True


def _recruitment(owner: str) -> str:
    recruit_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(
            Recruitment(
                recruit_id=recruit_id,
                publisher_id=owner,
                publisher_type="senior",
                type="research",
                title="DEP3 synthetic local-only recruitment",
                req="synthetic",
                review_status="verified",
                publication_status="published",
                authorization_basis="dep3_synthetic",
                verified_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                provenance={"scope": "dep3_synthetic"},
                governance={"scope": "dep3_synthetic"},
                quarantined_fields={},
            )
        )
        db.commit()
    return recruit_id


def _assert_race_invariant(document_id: str) -> bool:
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
            assert document is not None and document.status == "ready"
            assert read_private_document_bytes(document)
            assert tombstone is None
            return True
        assert document is None
        assert tombstone is not None
        return False


def verify_lock_order(first: str, owner: str) -> None:
    document = _document(owner)
    recruit_id = _recruitment(owner)
    results: list[tuple[str, int]] = []
    start = threading.Barrier(2) if first == "simultaneous" else None
    held = threading.Event()
    release = threading.Event()
    original_application_lock = application_service.lock_private_document
    original_delete_lock = document_service.lock_private_document

    if first == "application":
        def hold_application_lock(db, target):
            locked = original_application_lock(db, target)
            held.set()
            assert release.wait(10)
            return locked

        application_service.lock_private_document = hold_application_lock
    elif first == "delete":
        def hold_delete_lock(db, target):
            locked = original_delete_lock(db, target)
            held.set()
            assert release.wait(10)
            return locked

        document_service.lock_private_document = hold_delete_lock

    def run_application() -> None:
        if start:
            start.wait()
        with SessionLocal() as db:
            try:
                application = create_in_app_application(
                    db,
                    subject_id=owner,
                    recruit_id=recruit_id,
                    document_id=document.document_id,
                    confirmed=True,
                    idempotency_key=f"dep3-race-app:{uuid.uuid4()}",
                )
                results.append(("application", 200 if application else 500))
            except HTTPException as exc:
                results.append(("application", exc.status_code))

    def run_delete() -> None:
        if start:
            start.wait()
        with SessionLocal() as db:
            current = db.get(PrivateDocument, document.document_id)
            if current is None:
                results.append(("delete", 404))
                return
            try:
                delete_private_document_consistently(
                    db,
                    document=current,
                )
                results.append(("delete", 200))
            except HTTPException as exc:
                results.append(("delete", exc.status_code))

    application_thread = threading.Thread(target=run_application)
    delete_thread = threading.Thread(target=run_delete)
    try:
        if first == "delete":
            delete_thread.start()
            assert held.wait(10)
            application_thread.start()
            time.sleep(0.2)
            release.set()
        elif first == "application":
            application_thread.start()
            assert held.wait(10)
            delete_thread.start()
            time.sleep(0.2)
            release.set()
        else:
            application_thread.start()
            delete_thread.start()
        application_thread.join(20)
        delete_thread.join(20)
        assert not application_thread.is_alive()
        assert not delete_thread.is_alive()
        assert len(results) == 2
        has_active = _assert_race_invariant(document.document_id)
        if has_active:
            with SessionLocal() as db:
                application = (
                    db.query(Application)
                    .filter(
                        Application.resume_id == document.document_id,
                        Application.status != "withdrawn",
                    )
                    .one()
                )
                application.status = "withdrawn"
                application.resume_id = None
                db.commit()
                current = db.get(
                    PrivateDocument,
                    document.document_id,
                )
                delete_private_document_consistently(
                    db,
                    document=current,
                )
            assert not _assert_race_invariant(document.document_id)
    finally:
        application_service.lock_private_document = original_application_lock
        document_service.lock_private_document = original_delete_lock


def cleanup(owners: list[str]) -> None:
    with SessionLocal() as db:
        documents = (
            db.query(PrivateDocument)
            .filter(PrivateDocument.owner_subject_id.in_(owners))
            .all()
        )
        for document in documents:
            get_object_store_for_backend(document.object_backend).delete(
                document.stored_name
            )
        db.query(ArtifactDeliveryGrant).filter(
            ArtifactDeliveryGrant.owner_subject_id.in_(owners)
        ).delete(synchronize_session=False)
        db.query(Application).filter(
            Application.student_id.in_(owners)
        ).delete(synchronize_session=False)
        db.query(ArtifactAuditEvent).filter(
            ArtifactAuditEvent.owner_subject_id.in_(owners)
        ).delete(synchronize_session=False)
        db.query(IdempotencyRecord).filter(
            IdempotencyRecord.owner_subject_id.in_(owners)
        ).delete(synchronize_session=False)
        db.query(PrivateDocument).filter(
            PrivateDocument.owner_subject_id.in_(owners)
        ).delete(synchronize_session=False)
        db.query(DeletedArtifactTombstone).filter(
            DeletedArtifactTombstone.owner_subject_id.in_(owners)
        ).delete(synchronize_session=False)
        db.query(Recruitment).filter(
            Recruitment.publisher_id.in_(owners)
        ).delete(synchronize_session=False)
        db.commit()


def main() -> int:
    assert engine.dialect.name == "postgresql"
    owners: list[str] = []
    try:
        verify_atomic_grants(owners)
        for first in ("application", "delete", "simultaneous"):
            owner = _owner()
            owners.append(owner)
            verify_lock_order(first, owner)
    finally:
        cleanup(owners)
    print(
        "POSTGRES_REAL_ATOMIC_GRANTS_LOCK_ORDER_AND_WITHDRAW_DELETE_PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
