"""Web 匿名会话初始化与撤销。"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.identity import IdentitySession
from app.services.identity import (
    create_or_refresh_web_session,
    require_web_csrf,
    web_test_mode_status,
)

router = APIRouter(prefix="/session")
web_mode_router = APIRouter(prefix="/web-test-mode")


@web_mode_router.get("")
def web_test_mode():
    """网页免认证测试模式的公开状态（前端标注「未实名认证测试身份」）。"""
    return web_test_mode_status()


@router.get("")
def bootstrap_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    principal = create_or_refresh_web_session(db, request, response)
    return {
        "status": "ready",
        "channel": principal.channel,
        "persistent": principal.persistent,
    }


@router.delete("")
def revoke_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    principal = require_web_csrf(db, request)
    record = db.get(IdentitySession, principal.auth_session_id)
    if record is not None:
        record.revoked = True
        db.commit()
    response.delete_cookie(settings.WEB_SESSION_COOKIE, path="/")
    response.delete_cookie(settings.WEB_CSRF_COOKIE, path="/")
    return {"status": "revoked"}
