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
from app.services.idempotency import (
    begin_idempotency,
    complete_idempotency,
    fail_idempotency,
)
from app.services.identity import Principal
from app.services.content_moderation import assert_apply_method_allowed
from app.services.recruitment_public import (
    advisor_brief,
    get_public_recruitment,
    list_public_recruitments,
)

router = APIRouter()
PROJECT_TIMEZONE = ZoneInfo("Asia/Shanghai")


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
    data = {
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
    # 立体化扩展字段（作者视角全量返回，含 None 值便于编辑回填）
    for field in (
        "location",
        "quota",
        "compensation",
        "duration",
        "apply_method",
        "tags",
        "advisor_id",
    ):
        data[field] = getattr(record, field, None)
    return data


def _submission_values(request: RecruitmentCreateRequest) -> dict:
    return {
        "type": request.type,
        "title": request.title,
        "req": request.req,
        "major": request.major,
        "deadline": request.deadline.isoformat(),
        "is_urgent": request.is_urgent,
        "location": request.location,
        "quota": request.quota,
        "compensation": request.compensation,
        "duration": request.duration,
        "apply_method": request.apply_method,
        "tags": request.tags,
        "advisor_id": request.advisor_id,
    }


def _assert_current_deadline(deadline: date) -> datetime:
    now = datetime.now(PROJECT_TIMEZONE)
    if deadline < now.date():
        raise HTTPException(status_code=422, detail="截止日期不能早于今天")
    return now


@router.get("/recruitments")
def list_recruitments(
    urgent: Optional[bool] = None,
    tag: Optional[str] = None,
    advisor_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    result, withheld = list_public_recruitments(db, urgent_only=urgent is True)
    # 可选筛选在公开口径之上叠加收窄，不改变既有过滤语义
    if tag:
        result = [item for item in result if tag in (item.get("tags") or [])]
    if advisor_id:
        result = [
            item for item in result if item.get("advisor_id") == advisor_id
        ]
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


def _related_recruitments(db: Session, current: dict) -> list[dict]:
    """相关招募：同标签优先、同专业板块次之，取前 3 条（公开口径内）。"""
    records, _ = list_public_recruitments(db)
    current_tags = set(current.get("tags") or [])

    def _score(item: dict) -> int | None:
        if item.get("recruit_id") == current.get("recruit_id"):
            return None
        score = 2 * len(current_tags & set(item.get("tags") or []))
        if item.get("major") and item.get("major") == current.get("major"):
            score += 1
        return score

    scored = [
        (score, item)
        for item in records
        if (score := _score(item)) is not None
    ]
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("deadline") or "")))
    return [item for _, item in scored[:3]]


@router.get("/recruitments/{recruit_id}")
def get_recruitment_detail(
    recruit_id: str,
    db: Session = Depends(get_db),
):
    """公开招募详情：与列表同一过滤口径（未过审/下架/过期一律 404）。"""
    record = get_public_recruitment(db, recruit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="招募不存在或未公开")
    advisor = None
    if record.get("advisor_id"):
        advisor = advisor_brief(str(record["advisor_id"]))
    return {
        "data": {
            **record,
            "advisor": advisor,
            "related": _related_recruitments(db, record),
        }
    }


@router.post("/recruitments")
def publish_recruitment(
    request: RecruitmentCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    now = _assert_current_deadline(request.deadline)
    assert_apply_method_allowed(request.apply_method)
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
    assert_apply_method_allowed(request.apply_method)
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
        record.location = request.location
        record.quota = request.quota
        record.compensation = request.compensation
        record.duration = request.duration
        record.apply_method = request.apply_method
        record.tags = request.tags
        record.advisor_id = request.advisor_id
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
