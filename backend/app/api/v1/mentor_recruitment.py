"""导师招募管理 API（专属端点，复用 Recruitment 表）。

- publisher_id = mentor_accounts.subject_id、publisher_type = advisor、
  authorization_basis = mentor_authorized；发布后仍进审核流；
- 不改动学生侧 recruitment.py 的公开列表合并逻辑。
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import (
    MentorPrincipal,
    get_mentor_principal,
    get_mutating_mentor_principal,
)
from app.db.session import get_db
from app.models.recruitment import Recruitment
from app.schemas.recruitment import (
    RecruitmentCreateRequest,
    RecruitmentUpdateRequest,
)
from app.services.mentor_profile import require_claimed

router = APIRouter(prefix="/mentor/recruitments")
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


def _item(record: Recruitment) -> dict:
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


def _assert_current_deadline(deadline: date) -> datetime:
    now = datetime.now(PROJECT_TIMEZONE)
    if deadline < now.date():
        raise HTTPException(status_code=422, detail="截止日期不能早于今天")
    return now


def _owner_record(db: Session, recruit_id: str, subject_id: str) -> Recruitment:
    record = db.get(Recruitment, recruit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="招募投稿不存在")
    if record.publisher_id != subject_id:
        raise HTTPException(status_code=403, detail="无权访问该招募投稿")
    return record


@router.get("")
def list_my_recruitments(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    records = (
        db.query(Recruitment)
        .filter(
            Recruitment.publisher_id == mentor.account.subject_id,
            Recruitment.publisher_type == "advisor",
            Recruitment.review_status != "withdrawn",
        )
        .order_by(Recruitment.created_at.desc())
        .all()
    )
    return {"data": [_item(item) for item in records]}


@router.post("")
def publish_mentor_recruitment(
    request: RecruitmentCreateRequest,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    advisor_id = require_claimed(mentor.account)
    now = _assert_current_deadline(request.deadline)
    record = Recruitment(
        publisher_id=mentor.account.subject_id,
        publisher_type="advisor",
        type=request.type,
        title=request.title,
        req=request.req,
        major=request.major,
        deadline=request.deadline,
        is_urgent=request.is_urgent,
        expires_at=datetime.combine(
            request.deadline, time.max, tzinfo=PROJECT_TIMEZONE
        ),
        review_status="pending_review",
        publication_status="restricted",
        authorization_basis="mentor_authorized",
        consent_id=None,
        provenance={},
        governance={
            "review_status": "pending_review",
            "publication_status": "restricted",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "publisher": {"type": "advisor", "advisor_id": advisor_id},
            "review_history": [],
        },
        quarantined_fields={},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "recruit_id": record.recruit_id,
        "status": "pending_review",
        "publication_status": "restricted",
    }


@router.patch("/{recruit_id}")
def update_mentor_recruitment(
    recruit_id: str,
    request: RecruitmentUpdateRequest,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    record = _owner_record(db, recruit_id, mentor.account.subject_id)
    if record.review_status not in {"pending_review", "rejected"}:
        raise HTTPException(status_code=409, detail="投稿状态已变化，请刷新后重试")
    now = _assert_current_deadline(request.deadline)
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
    record.expires_at = datetime.combine(
        request.deadline, time.max, tzinfo=PROJECT_TIMEZONE
    )
    record.review_status = "pending_review"
    record.publication_status = "restricted"
    record.authorization_basis = "mentor_authorized"
    record.verified_at = None
    record.takedown_at = None
    record.quarantined_fields = {}
    record.governance = governance
    record.updated_at = now
    db.commit()
    db.refresh(record)
    return {
        "recruit_id": record.recruit_id,
        "status": "pending_review",
        "publication_status": "restricted",
        "updated": True,
    }


@router.delete("/{recruit_id}")
def withdraw_mentor_recruitment(
    recruit_id: str,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    record = _owner_record(db, recruit_id, mentor.account.subject_id)
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
    db.commit()
    return {"status": "withdrawn", "recruit_id": recruit_id}
