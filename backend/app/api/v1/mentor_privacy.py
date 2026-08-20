"""导师隐私控制 API：可见性策略与下线/隐藏申请。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    MentorPrincipal,
    get_mentor_principal,
    get_mutating_mentor_principal,
)
from app.db.session import get_db
from app.models.takedown_request import TakedownRequest
from app.schemas.mentor import TakedownSubmitRequest, VisibilityUpdateRequest
from app.services.mentor_privacy import (
    get_privacy_status,
    submit_takedown,
    update_visibility,
)

router = APIRouter(prefix="/mentor/privacy")


@router.get("")
def privacy_status(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    return get_privacy_status(db, account=mentor.account)


@router.patch("/visibility")
def patch_visibility(
    request: VisibilityUpdateRequest,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    """字段展示策略即时生效（仅导师端/管理端展示层）。"""
    return update_visibility(
        db, account=mentor.account, visibility=request.visibility
    )


@router.get("/takedowns")
def my_takedowns(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    records = (
        db.query(TakedownRequest)
        .filter(TakedownRequest.account_id == mentor.account.account_id)
        .order_by(TakedownRequest.created_at.desc())
        .all()
    )
    return {
        "data": [
            {
                "req_id": item.req_id,
                "reason": item.reason,
                "scope": item.scope,
                "field_name": item.field_name,
                "status": item.status,
                "admin_note": item.admin_note,
                "created_at": (
                    item.created_at.isoformat() if item.created_at else None
                ),
                "decided_at": (
                    item.decided_at.isoformat() if item.decided_at else None
                ),
            }
            for item in records
        ]
    }


@router.post("/takedowns")
def request_takedown(
    request: TakedownSubmitRequest,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    item = submit_takedown(
        db,
        account=mentor.account,
        reason=request.reason,
        scope=request.scope,
        field_name=request.field_name,
    )
    return {
        "req_id": item.req_id,
        "scope": item.scope,
        "status": item.status,
    }
