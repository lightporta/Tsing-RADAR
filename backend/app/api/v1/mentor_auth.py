"""导师邮箱验证码登录 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    MentorPrincipal,
    get_current_principal,
    get_mentor_principal,
    get_mutating_principal,
)
from app.db.session import get_db
from app.schemas.mentor import EmailCodeRequest, MentorLoginRequest
from app.services.identity import Principal
from app.services.mentor_auth import (
    get_mentor_account_by_session,
    login_mentor,
    logout_mentor,
    send_email_code,
)

router = APIRouter(prefix="/mentor/auth")


@router.get("/status")
def mentor_auth_status(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """登录状态：任意 Web 会话可查（匿名返回未登录）。"""
    account = get_mentor_account_by_session(
        db, session_id=principal.auth_session_id
    )
    if account is None:
        return {"logged_in": False}
    return {
        "logged_in": True,
        "email": account.email,
        "status": account.status,
        "advisor_id": account.advisor_id,
    }


@router.post("/email-code")
def request_email_code(
    request: EmailCodeRequest,
    principal: Principal = Depends(get_mutating_principal),
    db: Session = Depends(get_db),
):
    """发送验证码；只落库摘要，明文仅进日志/邮件（console 模式）。"""
    return send_email_code(db, email=request.email)


@router.post("/login")
def mentor_login(
    request: MentorLoginRequest,
    principal: Principal = Depends(get_mutating_principal),
    db: Session = Depends(get_db),
):
    """验证码通过后把当前 Web 会话绑定到导师账号。"""
    account = login_mentor(
        db,
        email=request.email,
        code=request.code,
        session_id=principal.auth_session_id,
    )
    return {
        "logged_in": True,
        "email": account.email,
        "status": account.status,
        "advisor_id": account.advisor_id,
    }


@router.post("/logout")
def mentor_logout(
    principal: Principal = Depends(get_mutating_principal),
    db: Session = Depends(get_db),
):
    """解除当前会话绑定（未绑定也幂等成功）。"""
    logout_mentor(db, session_id=principal.auth_session_id)
    return {"logged_in": False}
