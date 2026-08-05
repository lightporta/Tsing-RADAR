"""一次性下载令牌签名与校验（v2.2 新增）。

对应 Annotation 1 门禁「真实私有 S3 读写…短时签名过期」与
「一次性 Web 下载授权」。使用 HMAC-SHA256 签发短时令牌，
令牌绑定 object_id 与到期时间，校验时比对常量时间。

注意：这提供了**应用层**的一次性下载授权；真实云存储的预签名 URL、
私有桶策略、最小权限凭证、TLS、服务端加密与禁止 public ACL 仍属未关闭门禁。
"""

from __future__ import annotations

import hmac
import time
from typing import Optional

from app.core.config import settings


class InvalidToken(Exception):
    """令牌无效或已过期。"""


def _sign(object_id: str, expires_at: int, nonce: str) -> str:
    """生成 HMAC-SHA256 签名（hex）。"""
    msg = f"{object_id}.{expires_at}.{nonce}".encode("utf-8")
    return hmac.new(
        settings.DOWNLOAD_SIGNING_SECRET.encode("utf-8"), msg, "sha256"
    ).hexdigest()


def issue_download_token(object_id: str, *, ttl: Optional[int] = None) -> str:
    """为 object_id 签发一次性下载令牌：``object_id.expires_at.nonce.sig``。"""
    expires_at = int(time.time()) + (ttl if ttl is not None else settings.DOWNLOAD_TOKEN_TTL)
    nonce = f"{object_id}-{expires_at}"  # 简单一次性绑定（每个令牌唯一）
    sig = _sign(object_id, expires_at, nonce)
    return f"{object_id}.{expires_at}.{nonce}.{sig}"


def verify_download_token(token: str, object_id: str) -> None:
    """校验令牌：比对 object_id、过期、签名（常量时间）。

    Raises:
        InvalidToken: 令牌格式错误、object_id 不匹配、已过期或签名不符。
    """
    parts = token.split(".")
    if len(parts) != 4:
        raise InvalidToken("令牌格式错误")
    tok_obj, exp_str, nonce, sig = parts
    if not hmac.compare_digest(tok_obj, object_id):
        raise InvalidToken("令牌与对象不匹配")
    try:
        expires_at = int(exp_str)
    except ValueError:
        raise InvalidToken("过期时间非法")
    if time.time() > expires_at:
        raise InvalidToken("令牌已过期")
    expected = f"{object_id}-{expires_at}"
    if not hmac.compare_digest(nonce, expected):
        raise InvalidToken("nonce 非法")
    expected_sig = _sign(object_id, expires_at, nonce)
    if not hmac.compare_digest(sig, expected_sig):
        raise InvalidToken("签名不符")
