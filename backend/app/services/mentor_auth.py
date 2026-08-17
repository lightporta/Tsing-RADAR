"""导师邮箱验证码登录：限频、日上限、digest 存储与会话绑定。

- 验证码只存 SHA-256 摘要（code_digest），不留明文；
- 登录 = 把当前 Web 会话（identity_sessions.session_id）绑定到 mentor_accounts，
  不新增会话表/cookie；登出即解绑。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email_verification_code import EmailVerificationCode
from app.models.mentor_account import MentorAccount, STATUS_UNCLAIMED
from app.services.email_sender import send_code_email

TSINGHUA_EMAIL_SUFFIX = "@tsinghua.edu.cn"
PURPOSE_MENTOR_LOGIN = "mentor_login"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def normalize_mentor_email(email: str) -> str:
    """校验为清华邮箱并归一化（小写）。"""
    normalized = email.strip().casefold()
    if (
        len(normalized) > 100
        or "@" not in normalized
        or not normalized.endswith(TSINGHUA_EMAIL_SUFFIX)
    ):
        raise HTTPException(status_code=422, detail="仅支持清华邮箱（@tsinghua.edu.cn）")
    return normalized


def send_email_code(db: Session, *, email: str) -> dict:
    """签发验证码：同邮箱限频、日上限；只落库摘要并在日志/邮件中发送明文。"""
    normalized = normalize_mentor_email(email)
    now = _now()
    last = (
        db.query(EmailVerificationCode)
        .filter(EmailVerificationCode.email == normalized)
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    if (
        last is not None
        and last.used_at is None
        and _as_utc(last.expires_at) > now
        and now - _as_utc(last.created_at)
        < timedelta(seconds=settings.MENTOR_CODE_RESEND_SECONDS)
    ):
        raise HTTPException(
            status_code=429,
            detail="验证码发送过于频繁，请稍后再试",
        )
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == normalized,
            EmailVerificationCode.created_at >= day_start,
        )
        .count()
    )
    if sent_today >= settings.MENTOR_CODE_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="今日验证码发送次数已达上限",
        )
    code = _generate_code()
    record = EmailVerificationCode(
        id=str(uuid.uuid4()),
        email=normalized,
        purpose=PURPOSE_MENTOR_LOGIN,
        code_digest=_digest(code),
        expires_at=now + timedelta(seconds=settings.MENTOR_CODE_TTL_SECONDS),
        attempts=0,
    )
    db.add(record)
    db.commit()
    send_code_email(email=normalized, code=code, purpose=PURPOSE_MENTOR_LOGIN)
    return {"status": "sent", "expires_in": settings.MENTOR_CODE_TTL_SECONDS}


def verify_email_code(db: Session, *, email: str, code: str) -> None:
    """校验最新未用验证码；失败计数超限后该码作废。"""
    normalized = normalize_mentor_email(email)
    now = _now()
    record = (
        db.query(EmailVerificationCode)
        .filter(EmailVerificationCode.email == normalized)
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    if (
        record is None
        or record.used_at is not None
        or _as_utc(record.expires_at) <= now
    ):
        raise HTTPException(
            status_code=422,
            detail="验证码不存在或已过期，请重新获取",
        )
    record.attempts = (record.attempts or 0) + 1
    if record.attempts > settings.MENTOR_CODE_MAX_ATTEMPTS:
        record.used_at = now
        db.commit()
        raise HTTPException(
            status_code=422,
            detail="验证码尝试次数过多，请重新获取",
        )
    if not hmac.compare_digest(record.code_digest, _digest(code.strip())):
        db.commit()
        raise HTTPException(status_code=422, detail="验证码错误")
    record.used_at = now
    db.commit()


def login_mentor(db: Session, *, email: str, code: str, session_id: str) -> MentorAccount:
    """验证码通过后建立/复用导师账号并绑定当前 Web 会话。"""
    normalized = normalize_mentor_email(email)
    verify_email_code(db, email=normalized, code=code)
    now = _now()
    account = (
        db.query(MentorAccount)
        .filter(MentorAccount.email == normalized)
        .one_or_none()
    )
    if account is None:
        account = MentorAccount(
            account_id=str(uuid.uuid4()),
            email=normalized,
            subject_id=f"mnt_{uuid.uuid4().hex}",
            status=STATUS_UNCLAIMED,
            email_verified_at=now,
            bound_session_id=session_id,
        )
        db.add(account)
    else:
        account.email_verified_at = now
        account.bound_session_id = session_id
        account.updated_at = now
    db.commit()
    db.refresh(account)
    return account


def logout_mentor(db: Session, *, session_id: str) -> None:
    """解除当前 Web 会话与导师账号的绑定。"""
    db.query(MentorAccount).filter(
        MentorAccount.bound_session_id == session_id
    ).update({MentorAccount.bound_session_id: None})
    db.commit()


def get_mentor_account_by_session(
    db: Session, *, session_id: str
) -> MentorAccount | None:
    """按 Web 会话绑定查询导师账号；未绑定时返回 None。"""
    return (
        db.query(MentorAccount)
        .filter(MentorAccount.bound_session_id == session_id)
        .one_or_none()
    )
