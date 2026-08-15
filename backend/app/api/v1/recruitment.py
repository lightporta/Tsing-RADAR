"""招募信息路由：投稿受 owner、审核状态与幂等键共同约束。"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_principal,
    get_idempotency_key,
    get_mutating_principal,
)
from app.db.session import get_db
from app.models.recruitment import Recruitment
from app.schemas.recruitment import (
    RecruitmentCreateRequest,
    RecruitmentUpdateRequest,
)
from app.services.data_loader import load_mentors
from app.services.idempotency import (
    begin_idempotency,
    complete_idempotency,
    fail_idempotency,
)
from app.services.identity import Principal

router = APIRouter()
PROJECT_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _deadline_is_past(value: object, *, today: date) -> bool:
    try:
        deadline = value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return deadline < today


def _public_record(record: Recruitment) -> dict:
    """数据库投稿只有审核发布后才调用；不暴露内部主体或 provenance。"""
    return {
        "recruit_id": record.recruit_id,
        "publisher_name": "经审核发布者",
        "publisher_type": record.publisher_type,
        "type": record.type,
        "title": record.title,
        "req": record.req,
        "major": record.major,
        "deadline": record.deadline,
        "is_urgent": record.is_urgent,
        "dept": "",
        "review_status": record.review_status,
        "publication_status": record.publication_status,
    }


def _last_review_reason(record: Recruitment) -> str | None:
    governance = record.governance if isinstance(record.governance, dict) else {}
    history = governance.get("review_history")
    if not isinstance(history, list) or not history:
        return None
    last = history[-1]
    if not isinstance(last, dict):
        return None
    return str(last.get("reason") or "").strip() or None


def _owner_record(db: Session, recruit_id: str, subject_id: str) -> Recruitment:
    record = db.get(Recruitment, recruit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="招募投稿不存在")
    if record.publisher_id != subject_id:
        raise HTTPException(status_code=403, detail="无权访问该招募投稿")
    return record


def _mine_record(record: Recruitment) -> dict:
    return {
        "recruit_id": record.recruit_id,
        "type": record.type,
        "title": record.title,
        "req": record.req,
        "major": record.major,
        "deadline": record.deadline.isoformat() if record.deadline else None,
        "is_urgent": bool(record.is_urgent),
        "review_status": record.review_status,
        "publication_status": record.publication_status,
        "review_reason": _last_review_reason(record),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _submission_values(request: RecruitmentCreateRequest) -> dict:
    return {
        "type": request.type,
        "title": request.title,
        "req": request.req,
        "major": request.major,
        "deadline": request.deadline.isoformat(),
        "is_urgent": request.is_urgent,
    }


def _assert_current_deadline(deadline: date) -> datetime:
    now = datetime.now(PROJECT_TIMEZONE)
    if deadline < now.date():
        raise HTTPException(status_code=422, detail="截止日期不能早于今天")
    return now


@router.get("/recruitments")
def list_recruitments(
    urgent: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    result = []
    now = datetime.now(PROJECT_TIMEZONE)
    for mentor in load_mentors():
        for recruitment in mentor.get("recruitments", []) or []:
            if _deadline_is_past(recruitment.get("deadline"), today=now.date()):
                continue
            if urgent is True and not recruitment.get("is_urgent", False):
                continue
            result.append(recruitment)
    published_db = (
        db.query(Recruitment)
        .filter(
            Recruitment.review_status == "verified",
            Recruitment.publication_status == "published",
            Recruitment.takedown_at.is_(None),
        )
        .all()
    )
    for record in published_db:
        if _deadline_is_past(record.deadline, today=now.date()):
            continue
        if urgent is True and not record.is_urgent:
            continue
        result.append(_public_record(record))
    withheld = (
        db.query(Recruitment)
        .filter(Recruitment.publication_status != "published")
        .count()
    )
    return {
        "data": result,
        "meta": {
            "published_records": len(result),
            "withheld_submissions": withheld,
            "policy": "verified_only",
        },
    }


@router.get("/recruitments/mine")
def list_my_recruitments(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    records = (
        db.query(Recruitment)
        .filter(
            Recruitment.publisher_id == principal.subject_id,
            Recruitment.review_status != "withdrawn",
        )
        .order_by(Recruitment.created_at.desc())
        .all()
    )
    return {"data": [_mine_record(item) for item in records]}


@router.post("/recruitments")
def publish_recruitment(
    request: RecruitmentCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    now = _assert_current_deadline(request.deadline)
    payload = _submission_values(request)
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="create_recruitment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        record = Recruitment(
            publisher_id=principal.subject_id,
            publisher_type="student_submission",
            **{key: value for key, value in payload.items() if key != "deadline"},
            deadline=request.deadline,
            expires_at=datetime.combine(request.deadline, time.max, tzinfo=PROJECT_TIMEZONE),
            review_status="pending_review",
            publication_status="restricted",
            authorization_basis="none",
            consent_id=None,
            provenance={},
            governance={
                "review_status": "pending_review",
                "publication_status": "restricted",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "review_history": [],
            },
            quarantined_fields={},
        )
        db.add(record)
        db.flush()
        response = {
            "recruit_id": record.recruit_id,
            "status": "pending_review",
            "publication_status": "restricted",
        }
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment",
            resource_id=record.recruit_id,
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


@router.patch("/recruitments/{recruit_id}")
def update_and_resubmit_recruitment(
    recruit_id: str,
    request: RecruitmentUpdateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    _owner_record(db, recruit_id, principal.subject_id)
    now = _assert_current_deadline(request.deadline)
    payload = {"recruit_id": recruit_id, **_submission_values(request)}
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="update_recruitment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        record = _owner_record(db, recruit_id, principal.subject_id)
        if record.review_status not in {"pending_review", "rejected"}:
            raise HTTPException(status_code=409, detail="投稿状态已变化，请刷新后重试")
        governance = dict(record.governance or {})
        governance.update(
            {
                "review_status": "pending_review",
                "publication_status": "restricted",
                "updated_at": now.isoformat(),
                "resubmitted_at": now.isoformat(),
            }
        )
        record.type = request.type
        record.title = request.title
        record.req = request.req
        record.major = request.major
        record.deadline = request.deadline
        record.is_urgent = request.is_urgent
        record.expires_at = datetime.combine(request.deadline, time.max, tzinfo=PROJECT_TIMEZONE)
        record.review_status = "pending_review"
        record.publication_status = "restricted"
        record.authorization_basis = "none"
        record.consent_id = None
        record.verified_at = None
        record.takedown_at = None
        record.quarantined_fields = {}
        record.governance = governance
        record.updated_at = now
        db.flush()
        response = {
            "recruit_id": recruit_id,
            "status": "pending_review",
            "publication_status": "restricted",
            "updated": True,
        }
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment",
            resource_id=recruit_id,
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


@router.delete("/recruitments/{recruit_id}")
def withdraw_recruitment(
    recruit_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    _owner_record(db, recruit_id, principal.subject_id)
    payload = {"recruit_id": recruit_id, "action": "withdraw"}
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation="withdraw_recruitment",
        key=idempotency_key,
        payload=payload,
    )
    if claim.replayed:
        return claim.record.response_body
    try:
        record = _owner_record(db, recruit_id, principal.subject_id)
        now = datetime.now(PROJECT_TIMEZONE)
        governance = dict(record.governance or {})
        governance.update(
            {
                "review_status": "withdrawn",
                "publication_status": "withdrawn",
                "withdrawn_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        )
        record.review_status = "withdrawn"
        record.publication_status = "withdrawn"
        record.takedown_at = now
        record.governance = governance
        record.updated_at = now
        db.flush()
        response = {"status": "withdrawn", "recruit_id": recruit_id}
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="recruitment",
            resource_id=recruit_id,
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
