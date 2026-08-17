"""通用鉴权依赖；A5 不再接受客户端自报 student_id。"""

import hmac

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.identity import Principal, require_web_csrf, require_web_principal
from app.services.idempotency import validate_idempotency_key


async def verify_admin(
    admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> None:
    """Authenticate the local admin surface without logging/echoing secrets."""
    configured = settings.ADMIN_TOKEN
    if not configured:
        raise HTTPException(status_code=503, detail="管理员鉴权尚未配置")
    provided = (admin_token or "").encode("utf-8")
    expected = configured.encode("utf-8")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="管理员权限校验失败")


def get_current_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    return require_web_principal(db, request)


def get_mutating_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    return require_web_csrf(db, request)


def get_current_student(
    principal: Principal = Depends(get_current_principal),
) -> str:
    """兼容既有业务函数；值来自服务端会话，不来自请求头或请求体。"""
    return principal.subject_id


def get_mutating_student(
    principal: Principal = Depends(get_mutating_principal),
) -> str:
    return principal.subject_id


def get_idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    return validate_idempotency_key(value)
