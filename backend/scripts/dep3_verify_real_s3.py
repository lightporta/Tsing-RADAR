#!/usr/bin/env python3
"""Verify the DEP3 MinIO-backed object adapter at its real byte boundary."""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.services.object_storage import (
    ObjectStorageError,
    S3PrivateObjectStore,
)


PDF_TYPE = "application/pdf"


class CapturingClient:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.body = None

    def get_object(self, **kwargs):
        response = self.delegate.get_object(**kwargs)
        self.body = response.get("Body")
        return response

    def __getattr__(self, name):
        return getattr(self.delegate, name)


def _closed(body) -> bool:
    if body is None:
        return False
    if bool(getattr(body, "closed", False)):
        return True
    raw_stream = getattr(body, "_raw_stream", None)
    return bool(getattr(raw_stream, "closed", False))


def main() -> int:
    assert settings.OBJECT_STORE_BACKEND == "s3"
    assert settings.S3_SERVER_SIDE_ENCRYPTION == "none"
    limit = settings.OBJECT_STORAGE_MAX_READ_BYTES
    store = S3PrivateObjectStore()
    exact_key = f"dep3/{uuid.uuid4().hex}.pdf"
    over_key = f"dep3/{uuid.uuid4().hex}.pdf"

    try:
        exact = b"A" * limit
        store.put_bytes(exact_key, exact, PDF_TYPE)
        assert store.get_bytes(exact_key, max_bytes=limit) == exact

        store.client.put_object(
            Bucket=store.bucket,
            Key=over_key,
            Body=b"B" * (limit + 1),
            ContentType=PDF_TYPE,
        )
        captured = CapturingClient(store.client)
        store.client = captured
        try:
            store.get_bytes(over_key, max_bytes=limit)
        except ObjectStorageError:
            pass
        else:
            raise AssertionError("real over-limit S3 object was returned")
        assert _closed(captured.body)
    finally:
        store.delete(exact_key)
        store.delete(over_key)

    print("MINIO_REAL_BOUNDARY_OVER_LIMIT_AND_STREAM_CLOSE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
