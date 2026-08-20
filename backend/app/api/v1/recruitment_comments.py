"""招募评论路由：写端点受 CSRF + 幂等键约束；列表只读且脱敏。

隐私红线：任何公开响应不暴露 author_principal；审计事件只写枚举式
字段，不写评论正文与联系方式明文。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_principal,
    get_idempotency_key,
    get_mutating_principal,
)
from app.db.session import get_db
from app.schemas.recruitment_comment import (
    CommentCreateRequest,
    CommentReportRequest,
)
from app.services.artifact_audit import add_artifact_event
from app.services.idempotency import (
    begin_idempotency,
    complete_idempotency,
    fail_idempotency,
)
from app.services.identity import Principal
from app.services.mentor_auth import get_mentor_account_by_session
from app.services.recruitment_comments import (
    create_comment,
    like_comment,
    list_comment_tree,
    report_comment,
    soft_delete_comment,
)

router = APIRouter()


def _author_label(db: Session, principal: Principal) -> str:
    """导师会话主体标记为 advisor；其余默认 student（徽章由服务端计算）。"""
    if principal.auth_session_id:
        account = get_mentor_account_by_session(
            db, session_id=principal.auth_session_id
        )
        if account is not None:
            return "advisor"
    return "student"


@router.get("/recruitments/{recruit_id}/comments")
def get_comment_tree(
    recruit_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return list_comment_tree(
        db,
        recruit_id=recruit_id,
        page=page,
        page_size=page_size,
        viewer=principal.subject_id,
    )


@router.post("/recruitments/{recruit_id}/comments")
def post_comment(
    recruit_id: str,
    request: CommentCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    payload = {
        "recruit_id": recruit_id,
        "parent_id": request.parent_id,
        "content": request.content,
    }
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="create_recruitment_comment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        record = create_comment(
            db,
            recruit_id=recruit_id,
            parent_id=request.parent_id,
            principal=principal.subject_id,
            author_label=_author_label(db, principal),
            content=request.content,
        )
        # 审计只记录枚举式事件字段，不写评论正文
        add_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation="recruitment_comment",
            event_type="submitted",
            outcome="success",
            reason_code=(
                "held_for_review"
                if record.review_status == "pending_review"
                else "posted_public"
            ),
        )
        response = {
            "comment_id": record.comment_id,
            "recruit_id": recruit_id,
            "review_status": record.review_status,
        }
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment_comment",
            resource_id=record.comment_id,
            response_body=response,
        )
        return response
    except Exception as exc:
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
        )
        raise


@router.post("/recruitments/{recruit_id}/comments/{comment_id}/like")
def like_comment_endpoint(
    recruit_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    payload = {"comment_id": comment_id}
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="like_recruitment_comment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        like_count = like_comment(
            db, comment_id=comment_id, principal=principal.subject_id
        )
        response = {"comment_id": comment_id, "like_count": like_count}
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment_comment",
            resource_id=comment_id,
            response_body=response,
        )
        return response
    except Exception as exc:
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
        )
        raise


@router.post("/recruitments/{recruit_id}/comments/{comment_id}/report")
def report_comment_endpoint(
    recruit_id: str,
    comment_id: str,
    request: CommentReportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    payload = {"comment_id": comment_id, "reason": request.reason}
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="report_recruitment_comment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        report_comment(
            db,
            comment_id=comment_id,
            principal=principal.subject_id,
            reason=request.reason,
        )
        # 举报即隐藏：审计记 hidden，不写正文与举报人信息之外的明文
        add_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation="recruitment_comment",
            event_type="hidden",
            outcome="success",
            reason_code="reported",
        )
        response = {"comment_id": comment_id, "review_status": "pending_review"}
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment_comment",
            resource_id=comment_id,
            response_body=response,
        )
        return response
    except Exception as exc:
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
        )
        raise


@router.delete("/recruitments/{recruit_id}/comments/{comment_id}")
def delete_comment_endpoint(
    recruit_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    payload = {"comment_id": comment_id}
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="delete_recruitment_comment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        soft_delete_comment(
            db, comment_id=comment_id, principal=principal.subject_id
        )
        add_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation="recruitment_comment",
            event_type="deleted",
            outcome="success",
            reason_code="author_soft_delete",
        )
        response = {"comment_id": comment_id, "deleted": True}
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment_comment",
            resource_id=comment_id,
            response_body=response,
        )
        return response
    except Exception as exc:
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
        )
        raise
