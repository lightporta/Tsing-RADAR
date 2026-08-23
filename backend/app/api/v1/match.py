"""A4 证据化综合匹配路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_mutating_student
from app.db.session import get_db
from app.schemas.matching import MatchRequest
from app.services.interview import InterviewConflictError
from app.services.match_application import run_confirmed_match

router = APIRouter()


@router.post("/match")
def match_mentor(
    req: MatchRequest,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    """只用服务端已确认画像执行 A4 匹配，忽略旧客户端画像覆盖字段。"""
    if not req.session_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="匹配前必须完成并确认学生画像",
        )
    try:
        outcome = run_confirmed_match(
            db,
            session_id=req.session_id,
            student_id=student_id,
            ranking=req.ranking,
        )
    except InterviewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if outcome.status == "needs_clarification":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "needs_clarification",
                "message": outcome.message,
                "questions": outcome.questions,
            },
        )
    return {
        "data": outcome.items,
        "status": outcome.status,
        "message": outcome.message,
        "meta": outcome.meta,
    }
