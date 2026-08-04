"""评价反馈路由；身份与记录归属由服务端会话决定。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_mutating_principal
from app.db.session import get_db
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackRequest
from app.services.data_loader import load_mentors
from app.services.identity import Principal

router = APIRouter()


@router.post("/feedback")
def feedback(
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating 必须为 1 或 -1")
    public_ids = {
        str(item.get("advisor_id") or item.get("name"))
        for item in load_mentors()
    }
    if req.advisor_id not in public_ids:
        raise HTTPException(status_code=404, detail="未找到可公开评价的导师记录")
    record = Feedback(
        student_id=principal.subject_id,
        advisor_id=req.advisor_id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"feedback_id": record.feedback_id, "status": "recorded"}
