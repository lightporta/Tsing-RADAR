"""A5 身份边界：Web opaque 会话与清小搭可验证终端用户 claim。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.identity import ExternalIdentity, IdentitySession


@dataclass(frozen=True)
class Principal:
    subject_id: str
    channel: str
    auth_session_id: str | None
    persistent: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _digest(value: str, *, purpose: str) -> str:
    return hmac.new(
        settings.SESSION_HMAC_SECRET.encode("utf-8"),
        f"{purpose}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _unauthorized(detail: str = "会话无效或已过期") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def create_or_refresh_web_session(
    db: Session,
    request: Request,
    response: Response,
) -> Principal:
    raw_token = request.cookies.get(settings.WEB_SESSION_COOKIE)
    record = None
    if raw_token:
        record = (
            db.query(IdentitySession)
            .filter(IdentitySession.token_digest == _digest(raw_token, purpose="web"))
            .one_or_none()
        )
        if record and (
            record.revoked
            or record.channel != "web"
            or _as_utc(record.expires_at) <= _now()
        ):
            record = None

    if record is None:
        raw_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        record = IdentitySession(
            session_id=str(uuid.uuid4()),
            subject_id=f"usr_{uuid.uuid4().hex}",
            channel="web",
            token_digest=_digest(raw_token, purpose="web"),
            csrf_digest=_digest(csrf_token, purpose="csrf"),
            expires_at=_now() + timedelta(seconds=settings.WEB_SESSION_TTL_SECONDS),
            revoked=False,
        )
        db.add(record)
    else:
        csrf_token = secrets.token_urlsafe(32)
        record.csrf_digest = _digest(csrf_token, purpose="csrf")
        record.last_seen_at = _now()
        record.expires_at = _now() + timedelta(
            seconds=settings.WEB_SESSION_TTL_SECONDS
        )
    db.commit()

    cookie_common = {
        "secure": settings.WEB_COOKIE_SECURE,
        "samesite": "lax",
        "path": "/",
        "max_age": settings.WEB_SESSION_TTL_SECONDS,
    }
    response.set_cookie(
        settings.WEB_SESSION_COOKIE,
        raw_token,
        httponly=True,
        **cookie_common,
    )
    response.set_cookie(
        settings.WEB_CSRF_COOKIE,
        csrf_token,
        httponly=False,
        **cookie_common,
    )
    return Principal(record.subject_id, "web", record.session_id, True)


def require_web_principal(db: Session, request: Request) -> Principal:
    raw_token = request.cookies.get(settings.WEB_SESSION_COOKIE)
    if not raw_token:
        raise _unauthorized("缺少 Web 匿名会话，请先初始化会话")
    record = (
        db.query(IdentitySession)
        .filter(IdentitySession.token_digest == _digest(raw_token, purpose="web"))
        .one_or_none()
    )
    if (
        record is None
        or record.revoked
        or record.channel != "web"
        or _as_utc(record.expires_at) <= _now()
    ):
        raise _unauthorized()
    record.last_seen_at = _now()
    db.commit()
    return Principal(record.subject_id, "web", record.session_id, True)


def require_web_csrf(db: Session, request: Request) -> Principal:
    principal = require_web_principal(db, request)
    cookie_token = request.cookies.get(settings.WEB_CSRF_COOKIE)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF 校验失败",
        )
    record = db.get(IdentitySession, principal.auth_session_id)
    if record is None or not hmac.compare_digest(
        record.csrf_digest,
        _digest(header_token, purpose="csrf"),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF 校验失败",
        )
    return principal


def resolve_qxd_principal(
    db: Session,
    *,
    external_claim: str | None,
    signature: str | None,
) -> Principal:
    """无 claim 时生成单请求主体；claim 不完整或伪造时失败关闭。"""
    if not external_claim and not signature:
        return Principal(f"qreq_{uuid.uuid4().hex}", "qxd", None, False)
    if not external_claim or not signature:
        raise _unauthorized("清小搭终端用户 claim 不完整")
    if len(external_claim) > 256:
        raise _unauthorized("清小搭终端用户 claim 无效")
    secret = settings.QXD_END_USER_SIGNING_SECRET
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="尚未配置清小搭终端用户 claim 验证",
        )
    expected = hmac.new(
        secret.encode("utf-8"),
        external_claim.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected):
        raise _unauthorized("清小搭终端用户 claim 签名无效")
    fingerprint = hmac.new(
        secret.encode("utf-8"),
        f"identity-map:{external_claim}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    mapping = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == "qxd",
            ExternalIdentity.claim_fingerprint == fingerprint,
        )
        .one_or_none()
    )
    if mapping is None:
        mapping = ExternalIdentity(
            mapping_id=str(uuid.uuid4()),
            provider="qxd",
            claim_fingerprint=fingerprint,
            subject_id=f"usr_{uuid.uuid4().hex}",
        )
        db.add(mapping)
    else:
        mapping.last_seen_at = _now()
    db.commit()
    return Principal(mapping.subject_id, "qxd", None, True)
