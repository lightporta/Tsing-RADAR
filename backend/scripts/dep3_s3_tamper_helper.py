#!/usr/bin/env python3
"""Internal helper for the DEP3 real-MinIO tamper integration test."""

from __future__ import annotations

import argparse
import uuid
from urllib.parse import urlsplit

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.private_document import PrivateDocument
from app.services.artifact_delivery import issue_delivery_grant
from app.services.identity import Principal
from app.services.object_storage import S3PrivateObjectStore


def _document(db, document_id: str) -> PrivateDocument:
    document = db.get(PrivateDocument, document_id)
    if document is None:
        raise RuntimeError("synthetic DEP3 document is missing")
    if document.object_backend != "s3":
        raise RuntimeError("synthetic DEP3 document is not in S3")
    return document


def mutate(document_id: str) -> None:
    with SessionLocal() as db:
        document = _document(db, document_id)
        store = S3PrivateObjectStore()
        response = store.client.get_object(
            Bucket=store.bucket,
            Key=document.stored_name,
        )
        body = response["Body"]
        try:
            payload = body.read()
        finally:
            body.close()
        assert len(payload) == document.size_bytes
        replacement = bytes(
            ((value + 1) % 256)
            for value in payload
        )
        assert replacement != payload
        assert len(replacement) == len(payload)
        store.client.put_object(
            Bucket=store.bucket,
            Key=document.stored_name,
            Body=replacement,
            ContentType=document.media_type,
        )


def issue_qxd(document_id: str) -> str:
    settings.PUBLIC_BASE_URL = "https://agent.example.edu"
    settings.ALLOW_TEST_PUBLIC_BASE_URL = True
    with SessionLocal() as db:
        document = _document(db, document_id)
        document.document_kind = "match_report"
        db.commit()
        issued = issue_delivery_grant(
            db,
            document=document,
            principal=Principal(
                subject_id=document.owner_subject_id,
                channel="qxd",
                auth_session_id=None,
                persistent=True,
            ),
            audience="qxd_platform",
            confirmed=True,
            idempotency_key=f"dep3-qxd-tamper:{uuid.uuid4()}",
        )
    return urlsplit(issued.download_url).path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("mutate", "issue-qxd"))
    parser.add_argument("document_id")
    args = parser.parse_args()
    if args.operation == "mutate":
        mutate(args.document_id)
        print("MUTATED")
    else:
        print(issue_qxd(args.document_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
