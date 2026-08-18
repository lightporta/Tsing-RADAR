from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.file_scanning import ScanUnavailableError, scan_payload
from app.services.object_storage import (
    LocalPrivateObjectStore,
    ObjectStorageError,
    S3PrivateObjectStore,
)


PDF = "application/pdf"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class FakeStreamingBody:
    def __init__(
        self,
        payload: bytes,
        *,
        read_error: bool = False,
        close_error: bool = False,
    ) -> None:
        self.payload = payload
        self.offset = 0
        self.read_error = read_error
        self.close_error = close_error
        self.closed = False

    def read(self, size: int) -> bytes:
        if self.read_error:
            raise OSError("simulated read failure")
        block = self.payload[self.offset : self.offset + size]
        self.offset += len(block)
        return block

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise OSError("simulated close failure")


class FakeS3Client:
    def __init__(self, response: dict | None = None) -> None:
        self.response = response or {}
        self.put_requests: list[dict] = []

    def get_object(self, **_kwargs):
        return self.response

    def put_object(self, **kwargs):
        self.put_requests.append(kwargs)


def _s3_store(client: FakeS3Client) -> S3PrivateObjectStore:
    store = object.__new__(S3PrivateObjectStore)
    store.bucket = "private-artifacts"
    store.client = client
    return store


def test_local_object_reads_are_chunk_bounded_and_exact_boundary_passes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    store = LocalPrivateObjectStore(str(tmp_path))
    store.put_bytes("objects/boundary.pdf", b"12345678", PDF)
    assert store.get_bytes("objects/boundary.pdf", max_bytes=8) == b"12345678"

    store._path("objects/tampered.pdf").parent.mkdir(parents=True, exist_ok=True)
    store._path("objects/tampered.pdf").write_bytes(b"123456789")
    with pytest.raises(ObjectStorageError, match="超过声明大小"):
        store.get_bytes("objects/tampered.pdf", max_bytes=8)


def test_s3_declared_content_length_over_limit_fails_and_closes(monkeypatch):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    body = FakeStreamingBody(b"12345678")
    store = _s3_store(
        FakeS3Client({"ContentLength": 9, "Body": body})
    )
    with pytest.raises(ObjectStorageError, match="超过声明大小"):
        store.get_bytes("objects/file.pdf", max_bytes=8)
    assert body.closed is True


@pytest.mark.parametrize(
    "content_length",
    [None, "", "8", -1, True],
)
def test_s3_invalid_or_missing_content_length_fails_and_closes(
    monkeypatch,
    content_length,
):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    body = FakeStreamingBody(b"12345678")
    response = {"Body": body}
    if content_length is not None:
        response["ContentLength"] = content_length
    store = _s3_store(FakeS3Client(response))

    with pytest.raises(ObjectStorageError, match="声明大小无效"):
        store.get_bytes("objects/file.pdf", max_bytes=8)
    assert body.closed is True


def test_s3_missing_body_fails_with_stable_error(monkeypatch):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    store = _s3_store(FakeS3Client({"ContentLength": 8}))

    with pytest.raises(ObjectStorageError, match="响应缺少内容流"):
        store.get_bytes("objects/file.pdf", max_bytes=8)


def test_s3_lying_content_length_cannot_bypass_stream_limit(monkeypatch):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    body = FakeStreamingBody(b"123456789")
    store = _s3_store(
        FakeS3Client({"ContentLength": 4, "Body": body})
    )
    with pytest.raises(ObjectStorageError, match="超过声明大小"):
        store.get_bytes("objects/file.pdf", max_bytes=8)
    assert body.closed is True


def test_s3_exact_boundary_passes_and_body_is_closed(monkeypatch):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    body = FakeStreamingBody(b"12345678")
    store = _s3_store(
        FakeS3Client({"ContentLength": 8, "Body": body})
    )
    assert store.get_bytes("objects/file.pdf", max_bytes=8) == b"12345678"
    assert body.closed is True


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (FakeStreamingBody(b"", read_error=True), "读取失败"),
        (FakeStreamingBody(b"1234", close_error=True), "关闭失败"),
    ],
)
def test_s3_read_and_close_errors_are_stable(monkeypatch, body, expected):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    store = _s3_store(
        FakeS3Client({"ContentLength": 4, "Body": body})
    )
    with pytest.raises(ObjectStorageError, match=expected):
        store.get_bytes("objects/file.pdf", max_bytes=8)
    assert body.closed is True


def test_s3_addressing_style_is_applied_to_botocore(monkeypatch):
    import boto3

    captured: dict = {}

    def fake_client(service_name: str, **kwargs):
        captured["service_name"] = service_name
        captured.update(kwargs)
        return FakeS3Client()

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setattr(settings, "S3_BUCKET", "private-artifacts")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY_ID", "local-app")
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", "x" * 32)
    monkeypatch.setattr(settings, "S3_ADDRESSING_STYLE", "path")
    S3PrivateObjectStore()
    assert captured["service_name"] == "s3"
    assert captured["config"].s3["addressing_style"] == "path"


def test_s3_encryption_mode_is_explicit_and_never_silently_downgraded(
    monkeypatch,
):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MAX_READ_BYTES", 8)
    client = FakeS3Client()
    store = _s3_store(client)

    monkeypatch.setattr(settings, "S3_SERVER_SIDE_ENCRYPTION", "none")
    store.put_bytes("objects/local.pdf", b"local", PDF)
    assert "ServerSideEncryption" not in client.put_requests[-1]

    monkeypatch.setattr(settings, "S3_SERVER_SIDE_ENCRYPTION", "AES256")
    store.put_bytes("objects/encrypted.pdf", b"secure", PDF)
    assert client.put_requests[-1]["ServerSideEncryption"] == "AES256"


def test_clamav_timeout_fails_closed(monkeypatch):
    def timeout_connection(*_args, **_kwargs):
        raise TimeoutError("simulated clamd timeout")

    monkeypatch.setattr(settings, "FILE_SCAN_MODE", "clamav")
    monkeypatch.setattr(settings, "CLAMAV_HOST", "clamav")
    monkeypatch.setattr(
        "app.services.file_scanning.socket.create_connection",
        timeout_connection,
    )
    with pytest.raises(ScanUnavailableError, match="扫描服务不可用"):
        scan_payload(b"%PDF-1.4\n%%EOF", ".pdf")
