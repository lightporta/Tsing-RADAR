"""评价反馈路由。"""

import uuid

from fastapi import APIRouter, HTTPException

from app.schemas.feedback import FeedbackRequest
from app.services.memory_store import FEEDBACK_STORE

router = APIRouter()


@router.post("/feedback")
def feedback(req: FeedbackRequest):
    """提交评价（点赞/踩 + 评论），存入全局列表。"""
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating 必须为 1 或 -1")
    feedback_id = f"fb_{uuid.uuid4().hex[:8]}"
    FEEDBACK_STORE.append(
        {
            "feedback_id": feedback_id,
            "student_id": req.student_id,
            "advisor_id": req.advisor_id,
            "rating": req.rating,
            "comment": req.comment,
        }
    )
    return {"feedback_id": feedback_id, "status": "recorded"}
