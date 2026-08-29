"""管理员审批聚合：认领 / 字段编辑 / 下线隐藏 三条审批流 + 审计。

每个决定都写 artifact_audit_events 审计事件（枚举字段，不含正文/联系方式）。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.mentor_claim import MentorClaim
from app.models.mentor_profile_edit import MentorProfileEdit
from app.models.takedown_request import TakedownRequest
from app.services.artifact_audit import add_artifact_event
from app.services.mentor_claim import approve_claim, reject_claim
from app.services.mentor_privacy import decide_takedown
from app.services.mentor_profile import apply_field_edit

_CLAIM_ACTION = "mentor_review"
_REVIEWER_PREFIX = "admin"


def _reviewer_identity(reviewer: str) -> str:
    value = (reviewer or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="审批人不能为空")
    return f"{_REVIEWER_PREFIX}:{value}"


def _audit(
    db: Session,
    *,
    reviewer: str,
    event_type: str,
    outcome: str,
    reason_code: str,
) -> None:
    add_artifact_event(
        db,
        owner_subject_id=reviewer,
        operation=_CLAIM_ACTION,
        event_type=event_type,
        outcome=outcome,
        reason_code=reason_code,
    )


def list_claims(db: Session, *, status_filter: str | None = None) -> list[dict]:
    query = db.query(MentorClaim).order_by(MentorClaim.created_at.asc())
    if status_filter:
        query = query.filter(MentorClaim.status == status_filter)
    return [
        {
            "claim_id": item.claim_id,
            "advisor_id": item.advisor_id,
            "candidate_json": item.candidate_json,
            "factor_used": item.factor_used,
            "status": item.status,
            "admin_note": item.admin_note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in query.all()
    ]


def list_edits(db: Session, *, status_filter: str | None = None) -> list[dict]:
    query = db.query(MentorProfileEdit).order_by(MentorProfileEdit.created_at.asc())
    if status_filter:
        query = query.filter(MentorProfileEdit.status == status_filter)
    return [
        {
            "edit_id": item.edit_id,
            "account_id": item.account_id,
            "advisor_id": item.advisor_id,
            "field_name": item.field_name,
            "old_value": item.old_value,
            "new_value": item.new_value,
            "status": item.status,
            "admin_note": item.admin_note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in query.all()
    ]


def list_takedowns(db: Session, *, status_filter: str | None = None) -> list[dict]:
    query = db.query(TakedownRequest).order_by(TakedownRequest.created_at.asc())
    if status_filter:
        query = query.filter(TakedownRequest.status == status_filter)
    return [
        {
            "req_id": item.req_id,
            "account_id": item.account_id,
            "advisor_id": item.advisor_id,
            "reason": item.reason,
            "scope": item.scope,
            "field_name": item.field_name,
            "status": item.status,
            "admin_note": item.admin_note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in query.all()
    ]


def review_claim(
    db: Session, *, claim_id: str, action: str, reviewer: str, note: str | None
) -> dict:
    reviewer_id = _reviewer_identity(reviewer)
    if action == "approve":
        claim = approve_claim(db, claim_id=claim_id, reviewer=reviewer_id, note=note)
        _audit(
            db,
            reviewer=reviewer_id,
            event_type="mentor_claim_approve",
            outcome="success",
            reason_code="claim_approved",
        )
    elif action == "reject":
        claim = reject_claim(db, claim_id=claim_id, reviewer=reviewer_id, note=note)
        _audit(
            db,
            reviewer=reviewer_id,
            event_type="mentor_claim_reject",
            outcome="success",
            reason_code="claim_rejected",
        )
    else:
        raise HTTPException(status_code=422, detail="action 必须为 approve 或 reject")
    db.commit()
    return {"claim_id": claim.claim_id, "status": claim.status}


def review_edit(
    db: Session, *, edit_id: str, action: str, reviewer: str, note: str | None
) -> dict:
    reviewer_id = _reviewer_identity(reviewer)
    if action == "approve":
        edit = apply_field_edit(
            db,
            edit_id=edit_id,
            reviewer=reviewer_id,
            approve=True,
            note=note,
        )
        _audit(
            db,
            reviewer=reviewer_id,
            event_type="mentor_edit_approve",
            outcome="success",
            reason_code="field_edit_approved",
        )
    elif action == "reject":
        edit = apply_field_edit(
            db,
            edit_id=edit_id,
            reviewer=reviewer_id,
            approve=False,
            note=note,
        )
        _audit(
            db,
            reviewer=reviewer_id,
            event_type="mentor_edit_reject",
            outcome="success",
            reason_code="field_edit_rejected",
        )
    else:
        raise HTTPException(status_code=422, detail="action 必须为 approve 或 reject")
    db.commit()
    return {"edit_id": edit.edit_id, "status": edit.status}


def review_takedown(
    db: Session, *, req_id: str, action: str, reviewer: str, note: str | None
) -> dict:
    reviewer_id = _reviewer_identity(reviewer)
    if action == "approve":
        request = decide_takedown(
            db,
            req_id=req_id,
            reviewer=reviewer_id,
            approve=True,
            note=note,
        )
        _audit(
            db,
            reviewer=reviewer_id,
            event_type="mentor_takedown_approve",
            outcome="success",
            reason_code="takedown_approved",
        )
    elif action == "reject":
        request = decide_takedown(
            db,
            req_id=req_id,
            reviewer=reviewer_id,
            approve=False,
            note=note,
        )
        _audit(
            db,
            reviewer=reviewer_id,
            event_type="mentor_takedown_reject",
            outcome="success",
            reason_code="takedown_rejected",
        )
    else:
        raise HTTPException(status_code=422, detail="action 必须为 approve 或 reject")
    db.commit()
    return {"req_id": request.req_id, "status": request.status}
