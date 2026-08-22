"""兴趣探索 API：活动兴趣题 → 候选研究方向 → 写回画像。

面向研究方向不明确的用户（修改说明 §6）：
- 先提供容易回答的活动兴趣选择题（O*NET Interest Profiler 思路，
  改写为研究场景）；
- 候选方向由确定性映射生成（GLM 不参与、不改变结果）；
- 用户单选或多选候选方向后写回画像 research_interests，
  走既有匹配管线继续推荐导师。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_student, get_mutating_student
from app.db.session import get_db
from app.schemas.interest_exploration import (
    ActivityQuestionResponse,
    InterestExplorationApplyRequest,
    InterestExplorationSuggestionRequest,
    InterestExplorationSuggestionResponse,
)
from app.schemas.interview import InterviewStateResponse, StudentPortraitPatch
from app.services.interview import (
    InterviewAccessError,
    InterviewConflictError,
    InterviewNotFoundError,
    patch_profile,
    state_response,
)
from app.services.interest_exploration import (
    UnknownActivityError,
    UnknownDirectionError,
    activity_question,
    direction_labels_for_keys,
    suggest_direction_candidates,
)

router = APIRouter(prefix="/interest-exploration")


@router.get("/question", response_model=ActivityQuestionResponse)
def get_activity_question(
    _student_id: str = Depends(get_current_student),
):
    """返回活动兴趣选择题定义（静态内容，无状态）。"""
    return activity_question()


@router.post(
    "/suggestions",
    response_model=InterestExplorationSuggestionResponse,
)
def suggest_directions(
    request: InterestExplorationSuggestionRequest,
    _student_id: str = Depends(get_current_student),
):
    """从活动选择确定性推导候选研究方向（含详细介绍）。"""
    try:
        return suggest_direction_candidates(request.activities)
    except UnknownActivityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_id}/apply",
    response_model=InterviewStateResponse,
)
def apply_directions(
    session_id: str,
    request: InterestExplorationApplyRequest,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    """把用户选定的候选方向写回画像，继续推荐导师。"""
    try:
        labels = direction_labels_for_keys(request.direction_keys)
    except UnknownDirectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    patch = {
        "expected_version": request.expected_version,
        "research_interests": labels,
        "interest_statement": (
            "由兴趣探索选择的候选方向：" + "、".join(labels)
        ),
        "activity_interests": request.activities,
    }
    try:
        session = patch_profile(
            db,
            session_id=session_id,
            patch=StudentPortraitPatch.model_validate(patch),
            student_id=student_id,
        )
    except (
        InterviewNotFoundError,
        InterviewAccessError,
        InterviewConflictError,
    ) as exc:
        if isinstance(exc, InterviewNotFoundError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        if isinstance(exc, InterviewAccessError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return state_response(session)
