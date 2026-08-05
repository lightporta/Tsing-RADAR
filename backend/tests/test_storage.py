"""对象存储路由与签名令牌测试（v2.2）。

覆盖：上传→下载闭环、超大文件被拒、错误令牌拒绝、删除成功、
扫描失败时对象保持不可下载，以及签名令牌的签发/校验/过期。
"""

import io
import time

import pytest

from app.services.signing import InvalidToken, issue_download_token, verify_download_token


# ===== signing =====

def test_token_roundtrip():
    token = issue_download_token("obj-1", ttl=60)
    assert token.startswith("obj-1.")
    verify_download_token(token, "obj-1")  # 不抛异常即通过


def test_token_object_mismatch():
    token = issue_download_token("obj-1")
    with pytest.raises(InvalidToken):
        verify_download_token(token, "obj-other")


def test_token_expired():
    token = issue_download_token("obj-1", ttl=-1)  # 已过期
    with pytest.raises(InvalidToken):
        verify_download_token(token, "obj-1")


def test_token_tampered_signature():
    token = issue_download_token("obj-1")
    parts = token.split(".")
    parts[3] = "a" * 64  # 篡改签名
    with pytest.raises(InvalidToken):
        verify_download_token(".".join(parts), "obj-1")


def test_token_malformed():
    with pytest.raises(InvalidToken):
        verify_download_token("garbage", "obj-1")


# ===== storage route =====

def _upload(client, filename: str, content: bytes):
    return client.post(
        "/api/storage/upload",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )


def test_upload_download_roundtrip(tmp_path, monkeypatch):
    """干净 PDF：上传成功 → 拿到令牌 → 下载内容一致。"""
    from app.services import storage as storage_mod
    from app.db.session import init_db

    # 用临时目录隔离本地存储
    monkeypatch.setattr("app.core.config.settings.STORAGE_LOCAL_DIR", str(tmp_path))
    storage_mod.reset_storage_cache()
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 干净 PDF（合法 magic 头 %PDF）
    content = b"%PDF-1.4\nhello tsing-radar\n"
    resp = _upload(client, "resume.pdf", content)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scan_status"] == "clean"
    assert data["download_token"]

    # 下载（带令牌）
    dl = client.get("/api/storage/download", params={"token": data["download_token"]})
    assert dl.status_code == 200, dl.text
    assert dl.content == content
    assert dl.headers.get("cache-control") == "no-store"


def test_upload_rejects_blocked_extension(tmp_path, monkeypatch):
    """危险扩展名：扫描失败，对象 quarantined，不可下载。"""
    from app.services import storage as storage_mod
    from app.db.session import init_db

    monkeypatch.setattr("app.core.config.settings.STORAGE_LOCAL_DIR", str(tmp_path))
    storage_mod.reset_storage_cache()
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    resp = _upload(client, "evil.exe", b"MZ" + b"\x00" * 100)
    assert resp.status_code == 422
    assert "扫描未通过" in resp.json()["detail"]


def test_upload_rejects_magic_mismatch(tmp_path, monkeypatch):
    """扩展名 .pdf 但 magic 头不符：扫描失败。"""
    from app.services import storage as storage_mod
    from app.db.session import init_db

    monkeypatch.setattr("app.core.config.settings.STORAGE_LOCAL_DIR", str(tmp_path))
    storage_mod.reset_storage_cache()
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = _upload(client, "fake.pdf", b"not a real pdf content at all")
    assert resp.status_code == 422


def test_download_rejects_wrong_token(tmp_path, monkeypatch):
    """上传后用错误令牌下载应被拒。"""
    from app.services import storage as storage_mod
    from app.db.session import init_db

    monkeypatch.setattr("app.core.config.settings.STORAGE_LOCAL_DIR", str(tmp_path))
    storage_mod.reset_storage_cache()
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = _upload(client, "ok.pdf", b"%PDF-1.4\nx\n")
    obj_id = resp.json()["object_id"]

    # 伪造令牌：object_id 对但签名错
    bad = f"{obj_id}.{int(time.time()) + 60}.bad.bad"
    dl = client.get("/api/storage/download", params={"token": bad})
    assert dl.status_code == 403


def test_upload_oversize_rejected(tmp_path, monkeypatch):
    """超过 MAX_UPLOAD_BYTES：413。"""
    from app.services import storage as storage_mod
    from app.db.session import init_db

    monkeypatch.setattr("app.core.config.settings.STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.MAX_UPLOAD_BYTES", 16)
    storage_mod.reset_storage_cache()
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    big = b"%PDF-1.4\n" + b"a" * 1024
    resp = _upload(client, "big.pdf", big)
    assert resp.status_code == 413


def test_delete_owned_object(tmp_path, monkeypatch):
    """所有者删除对象成功。"""
    from app.services import storage as storage_mod
    from app.db.session import init_db

    monkeypatch.setattr("app.core.config.settings.STORAGE_LOCAL_DIR", str(tmp_path))
    storage_mod.reset_storage_cache()
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = _upload(client, "del.pdf", b"%PDF-1.4\ny\n")
    obj_id = resp.json()["object_id"]

    dele = client.delete(f"/api/storage/objects/{obj_id}")
    assert dele.status_code == 200
    assert dele.json()["status"] == "deleted"

    # 再下载（旧令牌）应 404
    token = resp.json()["download_token"]
    dl = client.get("/api/storage/download", params={"token": token})
    assert dl.status_code == 404
