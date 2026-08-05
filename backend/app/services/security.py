"""离线可用的安全原语（v2.2 新增）。

对应 Annotation 1 的若干门禁中「离线可做」的部分：
- ``validate_public_url``：URL 形状校验（必须 HTTPS、拒绝环回/私网/链路本地/保留测试域），
  对应「公网 DNS/TLS/SSRF 复核」的离线近似。注意：这里只做形状与已解析 IP 的检查，
  不做真实 DNS 解析、证书链校验或重定向跟踪——这些需要正式域名与公网环境，属于未关闭门禁。
- ``BoundedReader``：有界流式读取，超限即失败，对应「对象读取硬上限」的离线实现。
- ``redact_token``：从日志/URL 中剥离令牌与签名，对应「签名令牌日志脱敏」的应用层部分。

这些函数不连接任何外部服务，可在 SQLite + 本地环境下端到端验证。
"""

from __future__ import annotations

import ipaddress
import re
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

# —— 保留/测试 TLD，按 RFC 2606 视为非法公网目标 ——
_RESERVED_TLD = {".example", ".test", ".invalid", ".localhost"}

# —— IPv4 私网/环回/链路本地范围（离线判定，不依赖 DNS）——
_PRIVATE_HOST_PREFIXES = (
    "127.",       # 环回
    "10.",        # RFC1918
    "192.168.",   # RFC1918
    "169.254.",   # 链路本地
    "0.",         # 本网络
)
# 172.16.0.0/12 需数值判断（172.16.* ~ 172.31.*）


def _is_private_ip_literal(host: str) -> bool:
    """判断 host 是否是私网/环回/链路本地/未分配 IP 字面量。

    覆盖 IPv4 与 IPv6。对非 IP 字面量（域名）返回 False。
    """
    # IPv6 字面量去掉方括号
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved


def _is_private_ipv4_prefix(host: str) -> bool:
    """对 IPv4 点分字面量做前缀/范围判断（兼容 ipaddress 无法命中的边缘写法）。"""
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        return False
    if host.startswith(_PRIVATE_HOST_PREFIXES):
        return True
    # 172.16.0.0/12
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (IndexError, ValueError):
            pass
    return False


class UnsafeURL(ValueError):
    """URL 未通过形状校验。"""


def validate_public_url(url: str, *, allow_hosts: Optional[Iterable[str]] = None) -> str:
    """校验 URL 是否为可安全外联的公网 HTTPS 地址。

    校验规则（离线）：
    1. 必须是绝对 URL，scheme 必须为 ``https``（开发期测试可由 allow_hosts 显式放行）；
    2. 主机不得为空，不得为 ``localhost`` 或 ``*.local``；
    3. 主机不得解析为环回/私网/链路本地/未分配 IP 字面量；
    4. 主机不得以保留/测试 TLD（.example/.test/.invalid/.localhost）结尾；
    5. 端口不得为常见危险端口（如 22/25/ SMTP 控制端口之外的危险项在此不展开，
       仅拒绝显式 0 端口与超高端口）。

    Args:
        url: 待校验 URL。
        allow_hosts: 显式放行的主机白名单（大小写不敏感），用于开发/测试。

    Returns:
        规范化后的 URL（剥离 fragment）。

    Raises:
        UnsafeURL: 任一校验失败。

    Note:
        本函数只做形状与 IP 字面量检查，**不做** DNS 解析、证书校验或重定向跟踪，
        因此不能替代生产环境的真实 SSRF 复核（对应门禁未关闭）。
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURL("URL 为空")

    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise UnsafeURL(f"必须 HTTPS，当前 scheme={parsed.scheme or '(空)'}")
    if not parsed.hostname:
        raise UnsafeURL("缺少主机名")

    host = parsed.hostname.lower()
    port = parsed.port

    allow = {h.lower() for h in allow_hosts} if allow_hosts else set()

    if host in allow:
        return _strip_fragment(parsed)

    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeURL(f"拒绝 localhost：{host}")
    if host.endswith(".local"):
        raise UnsafeURL(f"拒绝 mDNS .local：{host}")
    if any(host.endswith(tld) for tld in _RESERVED_TLD):
        raise UnsafeURL(f"拒绝保留/测试 TLD：{host}")
    if _is_private_ipv4_prefix(host) or _is_private_ip_literal(host):
        raise UnsafeURL(f"拒绝私网/环回/链路本地地址：{host}")
    if port is not None and (port <= 0 or port > 65535):
        raise UnsafeURL(f"非法端口：{port}")

    return _strip_fragment(parsed)


def _strip_fragment(parsed) -> str:
    """剥离 fragment 后还原 URL。"""
    return urlunparse(parsed._replace(fragment=""))


class BoundedReader:
    """有界流式读取器，防止一次性加载整个对象（对应「对象读取硬上限」门禁）。

    用法：
        reader = BoundedReader(file_like, max_bytes=settings.MAX_DOWNLOAD_BYTES)
        for chunk in reader.read_chunks():
            ...

    一旦累计读取字节数超过 ``max_bytes``，立即抛出 ``ValueError``，调用方应据此
    中止传输并记录审计事件；被读取的对象应保持不可下载状态。
    """

    def __init__(self, stream, max_bytes: int, *, chunk_size: int = 64 * 1024) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes 必须为正")
        self._stream = stream
        self._max_bytes = max_bytes
        self._chunk_size = chunk_size
        self._consumed = 0

    @property
    def consumed(self) -> int:
        return self._consumed

    def read_chunks(self) -> Iterable[bytes]:
        """逐块生成器；超限立即抛 ValueError。"""
        while True:
            chunk = self._stream.read(self._chunk_size)
            if not chunk:
                break
            self._consumed += len(chunk)
            if self._consumed > self._max_bytes:
                raise ValueError(
                    f"对象超过硬上限 {self._max_bytes} 字节（已读 {self._consumed}），中止"
                )
            yield chunk

    def read_all(self) -> bytes:
        """便捷方法：读到结束或超限。仅在确认对象较小且不超出上限时使用。"""
        parts: list[bytes] = []
        for chunk in self.read_chunks():
            parts.append(chunk)
        return b"".join(parts)


# —— 日志/URL 令牌脱敏（对应「签名令牌日志脱敏」应用层部分）——
# 每个 entry 为 (pattern, replace_index)：replace_index 指定哪一组被替换为 [REDACTED]
_REDACT_PATTERNS: list[tuple[re.Pattern, int]] = [
    # Authorization: Bearer xxx
    (re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE), 2),
    # header 形如 X-Student-Token: xxx / X-Admin-Token: xxx
    (re.compile(r"(X-(?:Student|Admin)-Token\s*[:=]\s*)([^\s,;]+)", re.IGNORECASE), 2),
    # query 形如 token=xxx / admin_token=xxx
    (re.compile(r"((?:admin_)?token\s*=\s*)([^&\s]+)", re.IGNORECASE), 2),
    # query 形如 signature=xxx
    (re.compile(r"(signature\s*=\s*)([^&\s]+)", re.IGNORECASE), 2),
    # Basic auth user:pass@
    (re.compile(r"(//[^/@:]+:)([^@]+)(@)", re.IGNORECASE), 2),
]
_REDACTED = "[REDACTED]"


def redact_token(text: str) -> str:
    """剥离文本中的令牌/签名/口令，供日志记录使用。

    覆盖：``Bearer xxx``、``X-Student-Token``/``X-Admin-Token`` 头、
    ``token=``/``signature=``/``admin_token=`` 查询参数、Basic 认证口令。
    非字符串或空串原样返回。
    """
    if not isinstance(text, str) or not text:
        return text
    redacted = text
    for pat, idx in _REDACT_PATTERNS:
        redacted = pat.sub(lambda m, i=idx: m.group(1) + _REDACTED + (m.group(3) if m.lastindex and m.lastindex >= 3 else ""), redacted)
    return redacted
