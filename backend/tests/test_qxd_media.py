"""清小搭多模态 URL 安全测试。"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from app.services.qxd_media import (
    MediaSecurityError,
    MediaTooLargeError,
    SafeMediaFetcher,
)


async def public_resolver(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.asyncio
async def test_blocks_local_private_and_nonstandard_targets():
    fetcher = SafeMediaFetcher(
        allowed_hosts=["example.com"],
        resolver=public_resolver,
    )
    blocked = [
        "http://127.0.0.1/secret",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/secret",
        "https://localhost/secret",
        "https://user:pass@example.com/file",
        "https://example.com:8443/file",
        "file:///etc/passwd",
    ]
    for url in blocked:
        with pytest.raises(MediaSecurityError):
            await fetcher.validate_url(url)


@pytest.mark.asyncio
async def test_enforces_configured_host_allowlist():
    fetcher = SafeMediaFetcher(
        allowed_hosts=["oss.example.edu"],
        resolver=public_resolver,
    )
    assert (
        await fetcher.validate_url("https://sub.oss.example.edu/file.pdf")
        == "https://sub.oss.example.edu/file.pdf"
    )
    with pytest.raises(MediaSecurityError):
        await fetcher.validate_url("https://oss.example.edu.evil.test/file.pdf")


@pytest.mark.asyncio
async def test_revalidates_redirect_target_before_following():
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data"},
        )

    fetcher = SafeMediaFetcher(
        allowed_hosts=["files.example.edu"],
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(MediaSecurityError):
        await fetcher.fetch("https://files.example.edu/start", "file")
    assert requests == ["https://files.example.edu/start"]


@pytest.mark.asyncio
async def test_enforces_streamed_size_limit():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=b"12345",
        )

    fetcher = SafeMediaFetcher(
        allowed_hosts=["files.example.edu"],
        resolver=public_resolver,
        image_max_bytes=4,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(MediaTooLargeError):
        await fetcher.fetch("https://files.example.edu/image.png", "image")


@pytest.mark.asyncio
async def test_fetches_public_content_and_returns_integrity_metadata():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "files.example.edu":
            return httpx.Response(
                302,
                headers={"Location": "https://cdn.example.edu/document.pdf"},
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"document",
        )

    fetcher = SafeMediaFetcher(
        allowed_hosts=["files.example.edu", "cdn.example.edu"],
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    )
    result = await fetcher.fetch(
        "https://files.example.edu/start",
        "file",
        filename="document.pdf",
    )
    assert result.final_url == "https://cdn.example.edu/document.pdf"
    assert result.size == len(b"document")
    assert result.sha256 == hashlib.sha256(b"document").hexdigest()
    assert result.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_empty_allowlist_and_missing_production_peer_fail_closed():
    empty_allowlist = SafeMediaFetcher(resolver=public_resolver)
    with pytest.raises(MediaSecurityError):
        await empty_allowlist.validate_url("https://files.example.edu/document.pdf")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"document",
        )

    production_fetcher = SafeMediaFetcher(
        allowed_hosts=["files.example.edu"],
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
        require_connected_peer=True,
    )
    with pytest.raises(MediaSecurityError, match="实际连接地址"):
        await production_fetcher.fetch(
            "https://files.example.edu/document.pdf",
            "file",
        )


@pytest.mark.asyncio
async def test_production_fetch_rejects_private_connected_peer():
    class PrivatePeer:
        def get_extra_info(self, name):
            assert name == "server_addr"
            return ("10.0.0.8", 443)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"document",
            extensions={"network_stream": PrivatePeer()},
        )

    fetcher = SafeMediaFetcher(
        allowed_hosts=["files.example.edu"],
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
        require_connected_peer=True,
    )
    with pytest.raises(MediaSecurityError, match="非公网地址"):
        await fetcher.fetch("https://files.example.edu/document.pdf", "file")
