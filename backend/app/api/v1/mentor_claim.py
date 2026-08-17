"""导师档案认领 API：候选查询、提交认领、我的认领历史。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    MentorPrincipal,
    get_mentor_principal,
    get_mutating_mentor_principal,
)
from app.db.session import get_db
from app.models.mentor_claim import MentorClaim
from app.schemas.mentor import ClaimSubmitRequest
from app.services.mentor_claim import find_candidates, submit_claim

router = APIRouter(prefix="/mentor/claim")


@router.get("/eligible")
def claim_eligible(
    name: str,
    department: str = "",
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    """按姓名/院系查询可认领候选（JSON 发行物 + advisors 表并集）。"""
    return {
        "data": find_candidates(db, name=name, department=department),
        "meta": {"basis": "published_resources_union_db_advisors"},
    }


@router.post("")
def claim_mentor(
    request: ClaimSubmitRequest,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    """提交认领；唯一候选自动绑定，多候选转人工审批。"""
    return submit_claim(
        db,
        account=mentor.account,
        candidate_id=request.candidate_id,
        name=request.name,
        department=request.department,
    )


@router.get("/history")
def my_claim_history(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    records = (
        db.query(MentorClaim)
        .filter(MentorClaim.account_id == mentor.account.account_id)
        .order_by(MentorClaim.created_at.desc())
        .all()
    )
    return {
        "data": [
            {
                "claim_id": item.claim_id,
                "advisor_id": item.advisor_id,
                "candidate_json": item.candidate_json,
                "factor_used": item.factor_used,
                "status": item.status,
                "admin_note": item.admin_note,
                "created_at": (
                    item.created_at.isoformat() if item.created_at else None
                ),
                "decided_at": (
                    item.decided_at.isoformat() if item.decided_at else None
                ),
            }
            for item in records
        ]
    }
