"""学生评价路由：提交受 CSRF + 幂等键约束；读取端点只读且脱敏。

隐私红线：任何响应不暴露 rater_principal；列表仅返回在组时长、
认证徽章与时间（不返回单人分数，避免反推打分人）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_principal,
    get_idempotency_key,
    get_mutating_principal,
)
from app.db.session import get_db
from app.models.advisor_rating import AdvisorRating
from app.schemas.advisor_rating import RatingSubmitRequest
from app.services.advisor_rating import (
    REVIEW_APPROVED,
    apply_display_threshold,
    get_summary,
    submit_rating,
)
from app.services.artifact_audit import add_artifact_event
from app.services.constants import TRAIT_KEYS
from app.services.idempotency import (
    begin_idempotency,
    complete_idempotency,
    fail_idempotency,
)
from app.services.identity import Principal

router = APIRouter()


def _empty_summary(advisor_id: str) -> dict:
    """诚实空态：结构完整、全零值，不伪造任何样本。"""
    return {
        "advisor_id": advisor_id,
        "dimensions": {
            key: {"value": None, "n": 0} for key in TRAIT_KEYS
        },
        "total_n": 0,
        "last_collected_at": None,
    }


@router.post("/advisors/{advisor_id}/ratings")
def submit_advisor_rating(
    advisor_id: str,
    request: RatingSubmitRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    payload = {
        "advisor_id": advisor_id,
        "scores": request.scores,
        "period_in_group": request.period_in_group,
    }
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="submit_advisor_rating",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        record = submit_rating(
            db,
            advisor_id=advisor_id,
            rater_principal=principal.subject_id,
            scores=request.scores,
            period_in_group=request.period_in_group,
        )
        # 审计只记录枚举式事件字段，不写评分正文
        add_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation="submit_advisor_rating",
            event_type="advisor_rating_submitted",
            outcome="success",
            reason_code="rating_recorded",
        )
        response = {
            "rating_id": record.rating_id,
            "advisor_id": advisor_id,
            "review_status": record.review_status,
        }
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="advisor_rating",
            resource_id=record.rating_id,
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


def _apply_display_threshold(summary: dict) -> dict:
    """主观雷达展示门槛（与 services.advisor_rating.apply_display_threshold 同口径）。

    防止低样本暴露与操纵（如 1-2 人打分即可反推个体）；n 保留用于
    前端展示「样本不足」提示。
    """
    return apply_display_threshold(summary)


@router.get("/advisors/{advisor_id}/ratings/summary")
def get_rating_summary(
    advisor_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    summary = get_summary(db, advisor_id)
    if summary is None:
        return _empty_summary(advisor_id)
    return _apply_display_threshold(summary)


@router.get("/advisors/{advisor_id}/ratings")
def list_approved_ratings(
    advisor_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows = (
        db.query(AdvisorRating)
        .filter(
            AdvisorRating.advisor_id == advisor_id,
            AdvisorRating.review_status == REVIEW_APPROVED,
        )
        .order_by(AdvisorRating.created_at.desc())
        .all()
    )
    # 脱敏列表：仅在组时长 + 认证徽章 + 时间；不暴露打分人与单人分数
    return {
        "data": [
            {
                "period_in_group": row.period_in_group,
                "rater_verified": bool(row.rater_verified),
                "created_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
            }
            for row in rows
        ]
    }


@router.get("/ratings/mine")
def my_ratings(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows = (
        db.query(AdvisorRating)
        .filter(AdvisorRating.rater_principal == principal.subject_id)
        .order_by(AdvisorRating.created_at.desc())
        .all()
    )
    return {
        "data": [
            {
                "rating_id": row.rating_id,
                "advisor_id": row.advisor_id,
                "scores": row.scores,
                "period_in_group": row.period_in_group,
                "review_status": row.review_status,
                "created_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
            }
            for row in rows
        ]
    }
