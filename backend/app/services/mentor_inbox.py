"""导师意向中心：匹配记录聚合、投递列表与反馈汇总（学生侧一律匿名化）。

- 匹配记录按 advisor_id 聚合，不返回 student_id；
- 投递列表只返回申请时间/状态/简历摘要（不含 student_id/email/phone/original_name）；
- 反馈只返回正负计数，不暴露任何评论原文。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.feedback import Feedback
from app.models.match_record import MatchRecord
from app.models.private_document import PrivateDocument
from app.models.recruitment import Recruitment


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def matches_by_advisor(db: Session, *, advisor_id: str) -> dict:
    """按导师聚合匹配历史；学生身份不可见，仅保留记录级摘要。"""
    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.advisor_id == advisor_id)
        .order_by(MatchRecord.created_at.desc())
        .all()
    )
    return {
        "total": len(records),
        "recent": [
            {
                "record_id": item.record_id,
                "synergy_score": item.synergy_score,
                "match_reason": item.match_reason,
                "created_at": _iso(item.created_at),
            }
            for item in records[:10]
        ],
    }


def applications_by_mentor(db: Session, *, recruiter_subject_id: str) -> dict:
    """我发布的招募收到的站内投递；学生身份与联系方式不下发。"""
    recruit_ids = [
        item.recruit_id
        for item in db.query(Recruitment)
        .filter(Recruitment.publisher_id == recruiter_subject_id)
        .all()
    ]
    if not recruit_ids:
        return {"total": 0, "data": []}
    applications = (
        db.query(Application)
        .filter(Application.recruit_id.in_(recruit_ids))
        .order_by(Application.created_at.desc())
        .all()
    )
    resume_ids = {item.resume_id for item in applications if item.resume_id}
    documents = {}
    if resume_ids:
        documents = {
            item.document_id: item
            for item in db.query(PrivateDocument)
            .filter(PrivateDocument.document_id.in_(resume_ids))
            .all()
        }
    data: list[dict] = []
    for application in applications:
        document = documents.get(application.resume_id)
        data.append(
            {
                "app_id": application.app_id,
                "recruit_id": application.recruit_id,
                "status": application.status,
                "created_at": _iso(application.created_at),
                "resume": {
                    "present": document is not None,
                    "extension": document.extension if document else None,
                    "size_bytes": document.size_bytes if document else None,
                },
            }
        )
    return {"total": len(data), "data": data}


def feedback_summary(db: Session, *, advisor_id: str) -> dict:
    """导师收到的评价计数；评论正文不下发（防身份回推）。"""
    rows = db.query(Feedback).filter(Feedback.advisor_id == advisor_id).all()
    positive = sum(1 for item in rows if item.rating == 1)
    negative = sum(1 for item in rows if item.rating == -1)
    return {
        "total": len(rows),
        "positive": positive,
        "negative": negative,
    }
