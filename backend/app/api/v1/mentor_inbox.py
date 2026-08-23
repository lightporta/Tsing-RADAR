"""导师意向中心 API：匹配记录、投递列表与反馈汇总（学生侧匿名化）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import MentorPrincipal, get_mentor_principal
from app.db.session import get_db
from app.services.mentor_inbox import (
    applications_by_mentor,
    feedback_summary,
    matches_by_advisor,
)
from app.services.mentor_profile import require_claimed

router = APIRouter(prefix="/mentor/inbound")


@router.get("/matches")
def inbound_matches(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    advisor_id = require_claimed(mentor.account)
    return matches_by_advisor(db, advisor_id=advisor_id)


@router.get("/applications")
def inbound_applications(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    return applications_by_mentor(
        db, recruiter_subject_id=mentor.account.subject_id
    )


@router.get("/feedback")
def inbound_feedback(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    advisor_id = require_claimed(mentor.account)
    return feedback_summary(db, advisor_id=advisor_id)
