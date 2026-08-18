"""管理员导师审批 API（X-Admin-Token 鉴权）。"""

from fastapi import APIRouter, Depends, HTTPException
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
from app.services.artifact_audit import add_artifact_event
from app.services.recruitment_comments import (
    CommentReviewError,
    list_review_queue,
    review_comment,
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


# —— 招募评论审核（与导师审核同一鉴权与请求模型；治理历史写评论行）——


@router.get("/comments")
def admin_comments(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    return {"data": list_review_queue(db, status_filter=status)}


@router.post("/comments/{comment_id}/review")
def admin_review_comment(
    comment_id: str,
    request: MentorReviewRequest,
    db: Session = Depends(get_db),
):
    reason = (request.note or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="审核说明不能为空")
    try:
        record = review_comment(
            db,
            comment_id=comment_id,
            action=request.action,
            reviewer=request.reviewer,
            reason=reason,
        )
    except CommentReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 审计只写枚举式事件字段，不写评论正文
    add_artifact_event(
        db,
        owner_subject_id=f"admin:{request.reviewer}",
        operation="recruitment_comment",
        event_type="published" if request.action == "approve" else "hidden",
        outcome="success",
        reason_code="admin_review",
    )
    db.commit()
    return {
        "comment_id": record.comment_id,
        "review_status": record.review_status,
    }
