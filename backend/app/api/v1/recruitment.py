"""招募信息路由：新提交默认 restricted，审核前不可公开。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_principal, get_mutating_principal
from app.db.session import get_db
from app.models.recruitment import Recruitment
from app.schemas.recruitment import RecruitmentCreateRequest
from app.services.data_loader import load_mentors
from app.services.identity import Principal

router = APIRouter()
PROJECT_TIMEZONE = ZoneInfo("Asia/Shanghai")


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


@router.get("/recruitments")
def list_recruitments(
    urgent: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    result = []
    for mentor in load_mentors():
        for recruitment in mentor.get("recruitments", []) or []:
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
        .filter(Recruitment.publisher_id == principal.subject_id)
        .order_by(Recruitment.created_at.desc())
        .all()
    )
    return {
        "data": [
            {
                "recruit_id": item.recruit_id,
                "title": item.title,
                "review_status": item.review_status,
                "publication_status": item.publication_status,
                "created_at": item.created_at,
            }
            for item in records
        ]
    }


@router.post("/recruitments")
def publish_recruitment(
    request: RecruitmentCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    now = datetime.now(PROJECT_TIMEZONE)
    record = Recruitment(
        publisher_id=principal.subject_id,
        publisher_type="student_submission",
        type=request.type,
        title=request.title,
        req=request.req,
        major=request.major,
        deadline=request.deadline,
        is_urgent=request.is_urgent,
        expires_at=datetime.combine(
            request.deadline,
            time.max,
            tzinfo=PROJECT_TIMEZONE,
        ),
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


@router.delete("/recruitments/{recruit_id}")
def delete_recruitment(
    recruit_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    record = db.get(Recruitment, recruit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="招募投稿不存在")
    if record.publisher_id != principal.subject_id:
        raise HTTPException(status_code=403, detail="无权删除该招募投稿")
    if record.publication_status == "published":
        raise HTTPException(status_code=409, detail="已发布记录需走下架审核")
    db.delete(record)
    db.commit()
    return {"status": "deleted"}
