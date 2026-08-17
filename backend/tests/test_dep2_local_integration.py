from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

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


def test_minio_config_mount_and_initializer_are_statically_idempotent():
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    initializer = (
        REPOSITORY_ROOT / "deploy/minio/init-minio.sh"
    ).read_text(encoding="utf-8")

    assert "./deploy/minio:/config:ro" in compose
    referenced = {
        match
        for match in __import__("re").findall(
            r"/config/([a-zA-Z0-9._-]+)",
            initializer,
        )
    }
    assert referenced
    for filename in referenced:
        assert (REPOSITORY_ROOT / "deploy/minio" / filename).is_file()

    assert "ensure_user()" in initializer
    assert "mc admin user info" in initializer
    assert initializer.count('ensure_user "$MINIO_') == 2
    assert "mc admin user rm" not in initializer
    assert "mc admin user disable" not in initializer
    assert "mc mb --ignore-existing" in initializer


def _shell_path(path: Path) -> str:
    rendered = path.resolve().as_posix()
    if os.name == "nt":
        drive, remainder = rendered.split(":/", 1)
        return f"/mnt/{drive.lower()}/{remainder}"
    return rendered


def test_minio_initializer_converges_twice_with_controlled_mc_mock(tmp_path):
    source_dir = REPOSITORY_ROOT / "deploy/minio"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for filename in (
        "app-policy.template.json",
        "milvus-policy.template.json",
    ):
        shutil.copyfile(source_dir / filename, config_dir / filename)

    initializer = (source_dir / "init-minio.sh").read_text(encoding="utf-8")
    initializer = initializer.replace("/config/", f"{_shell_path(config_dir)}/")
    script_path = tmp_path / "init-minio.sh"
    script_path.write_text(initializer, encoding="utf-8", newline="\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_path = tmp_path / "users.state"
    log_path = tmp_path / "mc.log"
    fake_mc = bin_dir / "mc"
    fake_mc.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$MOCK_MC_LOG"
if [ "${1:-} ${2:-} ${3:-}" = "admin user info" ]; then
  grep -Fqx -- "$5" "$MOCK_MC_STATE" 2>/dev/null
  exit $?
fi
if [ "${1:-} ${2:-} ${3:-}" = "admin user add" ]; then
  touch "$MOCK_MC_STATE"
  grep -Fqx -- "$5" "$MOCK_MC_STATE" 2>/dev/null ||
    printf '%s\\n' "$5" >> "$MOCK_MC_STATE"
fi
exit 0
""",
        encoding="utf-8",
        newline="\n",
    )

    if os.name == "nt":
        runner_prefix = [
            "wsl.exe",
            "-d",
            "Ubuntu-22.04",
            "--",
        ]
    else:
        runner_prefix = []
    chmod = subprocess.run(
        [*runner_prefix, "chmod", "+x", _shell_path(fake_mc)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert chmod.returncode == 0, "controlled mock could not be prepared"

    command = [
        *runner_prefix,
        "env",
        f"PATH={_shell_path(bin_dir)}:/usr/bin:/bin",
        f"MOCK_MC_STATE={_shell_path(state_path)}",
        f"MOCK_MC_LOG={_shell_path(log_path)}",
        "MINIO_ROOT_USER=root-local",
        "MINIO_ROOT_PASSWORD=root-secret",
        "APP_S3_BUCKET=private-artifacts",
        "MINIO_APP_ACCESS_KEY=app-local",
        "MINIO_APP_SECRET_KEY=app-secret",
        "MILVUS_S3_BUCKET=milvus-data",
        "MINIO_MILVUS_ACCESS_KEY=milvus-local",
        "MINIO_MILVUS_SECRET_KEY=milvus-secret",
        "/bin/sh",
        _shell_path(script_path),
    ]
    first = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    second = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert first.returncode == 0
    assert second.returncode == 0

    assert state_path.read_text(encoding="utf-8").splitlines() == [
        "app-local",
        "milvus-local",
    ]
    operations = log_path.read_text(encoding="utf-8").splitlines()
    assert sum("admin user add local" in item for item in operations) == 4
    assert sum("admin policy attach local" in item for item in operations) == 4
    assert sum("mb --ignore-existing" in item for item in operations) == 4
    assert sum("anonymous set none" in item for item in operations) == 4
    assert all("unrelated" not in item for item in operations)
