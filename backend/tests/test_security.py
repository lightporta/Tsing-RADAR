"""安全原语测试（v2.2）。

覆盖 validate_public_url（SSRF 形状校验离线近似）、BoundedReader（有界读取）、
redact_token（日志脱敏），以及 scrape_faculty 接入 URL 校验后的拒绝行为。
"""

import io

import pytest

from app.services.security import (
    BoundedReader,
    UnsafeURL,
    redact_token,
    validate_public_url,
)


# ===== validate_public_url =====

@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",          # 非 HTTPS
        "ftp://example.com/x",         # 非 HTTPS scheme
        "https://localhost/x",         # localhost
        "https://127.0.0.1/x",         # 环回 IPv4
        "https://127.0.0.1:8000/x",    # 环回 IPv4 带端口
        "https://0.0.0.0/x",           # 未分配
        "https://10.0.0.1/x",          # RFC1918
        "https://192.168.1.1/x",       # RFC1918
        "https://172.16.5.5/x",        # RFC1918 172.16/12
        "https://172.31.255.255/x",    # RFC1918 172.16/12 上界
        "https://169.254.1.1/x",       # 链路本地
        "https://[::1]/x",            # IPv6 环回
        "https://[fe80::1]/x",        # IPv6 链路本地
        "https://foo.local/x",         # mDNS
        "https://bar.example/x",       # 保留 TLD
        "https://baz.test/x",          # 保留 TLD
        "https://qux.invalid/x",       # 保留 TLD
        "not a url",
        "",
    ],
)
def test_validate_public_url_rejects(url):
    with pytest.raises(UnsafeURL):
        validate_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tsinghua.edu.cn/",
        "https://example.com?x=1#frag",   # fragment 应被剥离，example.com 在 allow_hosts 放行
    ],
)
def test_validate_public_url_accepts_with_allowlist(url):
    # example.com 默认被保留 TLD 拒绝，显式 allow 后通过
    out = validate_public_url(url, allow_hosts=["example.com"])
    assert out.startswith("https://")
    assert "#" not in out


def test_validate_public_url_accepts_public_https():
    out = validate_public_url("https://www.tsinghua.edu.cn/faculty/")
    assert out == "https://www.tsinghua.edu.cn/faculty/"


def test_validate_public_url_strips_fragment():
    out = validate_public_url("https://www.tsinghua.edu.cn/a#b")
    assert out == "https://www.tsinghua.edu.cn/a"


# ===== BoundedReader =====

def test_bounded_reader_within_limit():
    stream = io.BytesIO(b"hello world")
    reader = BoundedReader(stream, max_bytes=100, chunk_size=4)
    chunks = list(reader.read_chunks())
    assert b"".join(chunks) == b"hello world"
    assert reader.consumed == 11


def test_bounded_reader_exceeds_limit():
    stream = io.BytesIO(b"x" * 50)
    reader = BoundedReader(stream, max_bytes=10, chunk_size=4)
    with pytest.raises(ValueError):
        list(reader.read_chunks())


def test_bounded_reader_read_all_ok():
    stream = io.BytesIO(b"abcdef")
    assert BoundedReader(stream, max_bytes=100).read_all() == b"abcdef"


def test_bounded_reader_rejects_zero_max():
    with pytest.raises(ValueError):
        BoundedReader(io.BytesIO(b""), max_bytes=0)


# ===== redact_token =====

@pytest.mark.parametrize(
    "raw, must_contain, must_not_contain",
    [
        ("Authorization: Bearer abc123xyz", "[REDACTED]", "abc123xyz"),
        ("X-Student-Token: s3cr3t", "[REDACTED]", "s3cr3t"),
        ("X-Admin-Token: adm1n", "[REDACTED]", "adm1n"),
        ("GET /x?token=t0k", "[REDACTED]", "t0k"),
        ("GET /x?admin_token=at0k&y=1", "[REDACTED]", "at0k"),
        ("GET /x?signature=s1g", "[REDACTED]", "s1g"),
        ("https://user:passw0rd@host/x", "[REDACTED]", "passw0rd"),
    ],
)
def test_redact_token(raw, must_contain, must_not_contain):
    out = redact_token(raw)
    assert must_contain in out
    assert must_not_contain not in out


def test_redact_token_preserves_safe_text():
    assert redact_token("nothing sensitive here") == "nothing sensitive here"
    assert redact_token("") == ""
    assert redact_token(None) is None  # type: ignore[arg-type]


# ===== scrape_faculty 接入 =====

def test_scrape_faculty_rejects_ssrf_target():
    """scrape_faculty 应拒绝私网/环回 URL（400）。"""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/internal/scrape/faculty", json={"url": "http://127.0.0.1:8000/admin"})
    assert resp.status_code == 400
    assert "校验失败" in resp.json()["detail"]


def test_scrape_faculty_accepts_public_https():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/internal/scrape/faculty",
        json={"url": "https://www.tsinghua.edu.cn/faculty/"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert resp.json()["url"] == "https://www.tsinghua.edu.cn/faculty/"
