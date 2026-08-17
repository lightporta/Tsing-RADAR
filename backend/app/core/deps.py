"""通用鉴权依赖；A5 不再接受客户端自报 student_id。"""

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.mentor_account import MentorAccount
from app.services.identity import Principal, require_web_csrf, require_web_principal
from app.services.idempotency import validate_idempotency_key
from app.services.mentor_auth import get_mentor_account_by_session


@dataclass(frozen=True)
class MentorPrincipal:
    """导师登录后的会话上下文：导师账号 + 底层 Web 会话主体。"""

    account: MentorAccount
    principal: Principal


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


def _mentor_account_or_401(
    principal: Principal, db: Session
) -> MentorAccount:
    account = get_mentor_account_by_session(
        db, session_id=principal.auth_session_id
    )
    if account is None:
        raise HTTPException(status_code=401, detail="导师会话未登录或已失效")
    return account


def get_mentor_principal(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> MentorPrincipal:
    """导师只读端点：Web 会话必须已绑定导师账号。"""
    return MentorPrincipal(
        account=_mentor_account_or_401(principal, db),
        principal=principal,
    )


def get_mutating_mentor_principal(
    principal: Principal = Depends(get_mutating_principal),
    db: Session = Depends(get_db),
) -> MentorPrincipal:
    """导师写端点：额外要求 CSRF 双提交校验。"""
    return MentorPrincipal(
        account=_mentor_account_or_401(principal, db),
        principal=principal,
    )


def get_idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    return validate_idempotency_key(value)
