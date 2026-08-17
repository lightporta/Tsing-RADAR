"""管理员导师审批 API（X-Admin-Token 鉴权）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import verify_admin
from app.db.session import get_db
from app.schemas.mentor import MentorReviewRequest
from app.services.admin_reviews import (
    list_claims,
    list_edits,
    list_takedowns,
    review_claim,
    review_edit,
    review_takedown,
)

router = APIRouter(prefix="/admin/mentor", dependencies=[Depends(verify_admin)])


@router.get("/claims")
def admin_claims(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    return {"data": list_claims(db, status_filter=status)}


@router.post("/claims/{claim_id}/review")
def admin_review_claim(
    claim_id: str,
    request: MentorReviewRequest,
    db: Session = Depends(get_db),
):
    return review_claim(
        db,
        claim_id=claim_id,
        action=request.action,
        reviewer=request.reviewer,
        note=request.note,
    )


@router.get("/profile-edits")
def admin_profile_edits(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    return {"data": list_edits(db, status_filter=status)}


@router.post("/profile-edits/{edit_id}/review")
def admin_review_profile_edit(
    edit_id: str,
    request: MentorReviewRequest,
    db: Session = Depends(get_db),
):
    return review_edit(
        db,
        edit_id=edit_id,
        action=request.action,
        reviewer=request.reviewer,
        note=request.note,
    )


@router.get("/takedowns")
def admin_takedowns(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    return {"data": list_takedowns(db, status_filter=status)}


@router.post("/takedowns/{req_id}/review")
def admin_review_takedown(
    req_id: str,
    request: MentorReviewRequest,
    db: Session = Depends(get_db),
):
    return review_takedown(
        db,
        req_id=req_id,
        action=request.action,
        reviewer=request.reviewer,
        note=request.note,
    )
