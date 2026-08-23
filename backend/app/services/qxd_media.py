"""清小搭多模态 URL 的受控下载器。"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings, settings

MediaKind = Literal["image", "audio", "file"]
Resolver = Callable[[str, int], Awaitable[list[str]]]
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
ALLOWED_PORTS = {80, 443}


class MediaFetchError(ValueError):
    """媒体无法安全、完整地拉取。"""


class MediaSecurityError(MediaFetchError):
    """URL 违反 SSRF 安全规则。"""


class MediaTooLargeError(MediaFetchError):
    """媒体超过对应类型大小限制。"""


@dataclass(frozen=True)
class FetchedMedia:
    kind: MediaKind
    source_url: str
    final_url: str
    filename: str | None
    content_type: str
    size: int
    sha256: str


async def _default_resolver(host: str, port: int) -> list[str]:
    def resolve() -> list[str]:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return sorted({record[4][0] for record in records})

    try:
        return await asyncio.to_thread(resolve)
    except socket.gaierror as exc:
        raise MediaFetchError("媒体域名无法解析") from exc


def _is_allowed_host(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    if not allowed_hosts:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)


def _assert_public_address(raw_address: str) -> None:
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError as exc:
        raise MediaSecurityError("媒体目标地址无效") from exc
    if not address.is_global:
        raise MediaSecurityError("媒体 URL 指向非公网地址")


def validate_remote_media_configuration(app_settings: Settings) -> None:
    if not app_settings.QXD_REMOTE_MEDIA_FETCH_ENABLED:
        return
    if not app_settings.QXD_API_KEY:
        raise RuntimeError("启用清小搭远程媒体输入前必须配置入站协议凭证")
    if not app_settings.qxd_media_allowed_hosts_list:
        raise RuntimeError("启用清小搭远程媒体输入必须配置非空域名白名单")


class SafeMediaFetcher:
    """逐跳校验 URL、DNS 与连接地址，并限制重定向、大小和超时。"""

    def __init__(
        self,
        *,
        allowed_hosts: list[str] | tuple[str, ...] = (),
        max_redirects: int = 3,
        timeout_seconds: float = 20.0,
        image_max_bytes: int = 20 * 1024 * 1024,
        audio_max_bytes: int = 25 * 1024 * 1024,
        file_max_bytes: int = 200 * 1024 * 1024,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        require_connected_peer: bool = False,
    ) -> None:
        self.allowed_hosts = tuple(
            host.lower().rstrip(".") for host in allowed_hosts if host.strip()
        )
        self.max_redirects = max_redirects
        self.timeout_seconds = timeout_seconds
        self.max_bytes = {
            "image": image_max_bytes,
            "audio": audio_max_bytes,
            "file": file_max_bytes,
        }
        self.resolver = resolver or _default_resolver
        self.transport = transport
        self.require_connected_peer = require_connected_peer

    @classmethod
    def from_settings(cls, app_settings: Settings = settings) -> "SafeMediaFetcher":
        return cls(
            allowed_hosts=app_settings.qxd_media_allowed_hosts_list,
            max_redirects=app_settings.QXD_MEDIA_MAX_REDIRECTS,
            timeout_seconds=app_settings.QXD_MEDIA_TIMEOUT_SECONDS,
            image_max_bytes=app_settings.QXD_IMAGE_MAX_BYTES,
            audio_max_bytes=app_settings.QXD_AUDIO_MAX_BYTES,
            file_max_bytes=app_settings.QXD_FILE_MAX_BYTES,
            require_connected_peer=app_settings.PRODUCTION_DEPLOYMENT,
        )

    async def validate_url(self, url: str) -> str:
        try:
            parsed = urlsplit(url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise MediaSecurityError("媒体 URL 格式无效") from exc

        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MediaSecurityError("媒体 URL 只允许绝对 HTTP(S) 地址")
        if parsed.username or parsed.password:
            raise MediaSecurityError("媒体 URL 不得包含用户凭证")
        if port not in ALLOWED_PORTS:
            raise MediaSecurityError("媒体 URL 使用了未允许的端口")

        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise MediaSecurityError("媒体域名无效") from exc
        if host == "localhost" or host.endswith(".localhost"):
            raise MediaSecurityError("媒体 URL 不得指向本地主机")
        if not _is_allowed_host(host, self.allowed_hosts):
            raise MediaSecurityError("媒体域名不在允许列表")

        try:
            literal_address = ipaddress.ip_address(host)
        except ValueError:
            addresses = await self.resolver(host, port)
            if not addresses:
                raise MediaFetchError("媒体域名没有可用地址")
            for address in addresses:
                _assert_public_address(address)
        else:
            _assert_public_address(str(literal_address))

        return url

    def _validate_connected_peer(self, response: httpx.Response) -> None:
        network_stream = response.extensions.get("network_stream")
        if network_stream is None or not hasattr(network_stream, "get_extra_info"):
            if self.require_connected_peer:
                raise MediaSecurityError("生产媒体请求缺少可验证的实际连接地址")
            return
        peer = network_stream.get_extra_info("server_addr")
        if not isinstance(peer, tuple) or not peer:
            if self.require_connected_peer:
                raise MediaSecurityError("生产媒体请求缺少可验证的实际连接地址")
            return
        _assert_public_address(str(peer[0]))

    @staticmethod
    def _validate_content_type(kind: MediaKind, content_type: str) -> None:
        if content_type == "application/octet-stream":
            return
        if kind == "image" and not content_type.startswith("image/"):
            raise MediaFetchError("图片 URL 返回了非图片内容")
        if kind == "audio" and not content_type.startswith("audio/"):
            raise MediaFetchError("音频 URL 返回了非音频内容")

    async def fetch(
        self,
        url: str,
        kind: MediaKind,
        *,
        filename: str | None = None,
        max_bytes: int | None = None,
    ) -> FetchedMedia:
        source_url = url
        current_url = url
        redirects = 0
        limit = self.max_bytes[kind]
        if max_bytes is not None:
            if max_bytes <= 0:
                raise MediaTooLargeError("媒体超过单次请求总大小限制")
            limit = min(limit, max_bytes)
        timeout = httpx.Timeout(self.timeout_seconds)

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                while True:
                    await self.validate_url(current_url)
                    async with client.stream(
                        "GET",
                        current_url,
                        headers={"Accept": "*/*", "User-Agent": "Tsing-RADAR/2.1"},
                    ) as response:
                        self._validate_connected_peer(response)

                        if response.status_code in REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location:
                                raise MediaFetchError("媒体重定向缺少 Location")
                            if redirects >= self.max_redirects:
                                raise MediaFetchError("媒体重定向次数过多")
                            current_url = urljoin(current_url, location)
                            redirects += 1
                            continue

                        if response.status_code < 200 or response.status_code >= 300:
                            raise MediaFetchError(
                                f"媒体下载返回 HTTP {response.status_code}"
                            )

                        content_length = response.headers.get("content-length")
                        if content_length:
                            try:
                                declared_size = int(content_length)
                            except ValueError as exc:
                                raise MediaFetchError(
                                    "媒体 Content-Length 无效"
                                ) from exc
                            if declared_size < 0:
                                raise MediaFetchError(
                                    "媒体 Content-Length 无效"
                                )
                            if declared_size > limit:
                                raise MediaTooLargeError("媒体超过大小限制")

                        content_type = (
                            response.headers.get(
                                "content-type", "application/octet-stream"
                            )
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                        )
                        self._validate_content_type(kind, content_type)

                        size = 0
                        digest = hashlib.sha256()
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > limit:
                                raise MediaTooLargeError("媒体超过大小限制")
                            digest.update(chunk)

                        return FetchedMedia(
                            kind=kind,
                            source_url=source_url,
                            final_url=current_url,
                            filename=filename,
                            content_type=content_type,
                            size=size,
                            sha256=digest.hexdigest(),
                        )
        except MediaFetchError:
            raise
        except httpx.TimeoutException as exc:
            raise MediaFetchError("媒体下载超时") from exc
        except httpx.HTTPError as exc:
            raise MediaFetchError("媒体下载失败") from exc
