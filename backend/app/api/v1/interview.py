"""A3 动态访谈、画像编辑与确认 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_student, get_mutating_student
from app.db.session import get_db
from app.schemas.interview import (
    HardConstraintCapabilitiesResponse,
    InterviewAnswerRequest,
    InterviewConfirmRequest,
    InterviewCreateRequest,
    InterviewEnhancementRetryResponse,
    InterviewStateResponse,
    StudentPortraitPatch,
)
from app.services.data_loader import load_match_candidates
from app.services.interview import (
    InterviewAccessError,
    InterviewConflictError,
    InterviewNotFoundError,
    answer_session,
    confirm_profile,
    create_session,
    get_session,
    patch_profile,
    state_response,
)
from app.services.matching import hard_constraint_capabilities
from app.services.llm import enhance_interview_reply

router = APIRouter(prefix="/interviews")


@router.get(
    "/hard-constraint-capabilities",
    response_model=HardConstraintCapabilitiesResponse,
)
def get_hard_constraint_capabilities():
    """Describe only constraints supported by current verified mentor facts."""
    return hard_constraint_capabilities(load_match_candidates())


def _raise_interview_error(exc: Exception) -> None:
    if isinstance(exc, InterviewNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, InterviewAccessError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, InterviewConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.post("", response_model=InterviewStateResponse)
def start_interview(
    request: InterviewCreateRequest,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    session = create_session(db, student_id=student_id)
    if request.initial_answer:
        session = answer_session(
            db,
            session_id=session.session_id,
            answer=request.initial_answer,
            student_id=student_id,
        )
    return state_response(session)


@router.get("/{session_id}", response_model=InterviewStateResponse)
def get_interview(
    session_id: str,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_current_student),
):
    try:
        return state_response(get_session(db, session_id, student_id))
    except (InterviewNotFoundError, InterviewAccessError) as exc:
        _raise_interview_error(exc)


@router.post("/{session_id}/answers", response_model=InterviewStateResponse)
def submit_answer(
    session_id: str,
    request: InterviewAnswerRequest,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    try:
        session = answer_session(
            db,
            session_id=session_id,
            answer=request.answer,
            student_id=student_id,
        )
        return state_response(session)
    except (
        InterviewNotFoundError,
        InterviewAccessError,
        InterviewConflictError,
    ) as exc:
        _raise_interview_error(exc)


@router.post(
    "/{session_id}/enhancement-retry",
    response_model=InterviewEnhancementRetryResponse,
)
async def retry_interview_enhancement(
    session_id: str,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    """Retry GLM wording for the last completed turn without changing state."""
    try:
        session = get_session(db, session_id, student_id)
    except (InterviewNotFoundError, InterviewAccessError) as exc:
        _raise_interview_error(exc)
    messages = list(session.messages or [])
    assistant_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].get("role") == "assistant"
            and str(messages[index].get("content") or "").strip()
        ),
        None,
    )
    user_index = next(
        (
            index
            for index in range((assistant_index or 0) - 1, -1, -1)
            if messages[index].get("role") == "user"
            and str(messages[index].get("content") or "").strip()
        ),
        None,
    )
    if assistant_index is None or user_index is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "no_completed_interview_turn",
                "message": "当前会话还没有可重试增强的完整问答轮次。",
            },
        )
    enhancement = await enhance_interview_reply(
        user_message=str(messages[user_index]["content"]),
        fixed_reply=str(messages[assistant_index]["content"]),
    )
    if enhancement.status != "available" or not enhancement.text:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "glm_unavailable",
                "message": "GLM 暂不可用，访谈状态未改变，请稍后重试。",
                "retryable": True,
                "provider": "glm",
            },
        )
    return {
        "session_id": session_id,
        "text": enhancement.text,
        "provider": "glm",
        "status": "available",
    }


@router.patch("/{session_id}/profile", response_model=InterviewStateResponse)
def edit_profile(
    session_id: str,
    request: StudentPortraitPatch,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    try:
        return state_response(
            patch_profile(
                db,
                session_id=session_id,
                patch=request,
                student_id=student_id,
            )
        )
    except (
        InterviewNotFoundError,
        InterviewAccessError,
        InterviewConflictError,
    ) as exc:
        _raise_interview_error(exc)


@router.post("/{session_id}/confirm", response_model=InterviewStateResponse)
def confirm_interview_profile(
    session_id: str,
    request: InterviewConfirmRequest,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    try:
        return state_response(
            confirm_profile(
                db,
                session_id=session_id,
                expected_version=request.expected_version,
                student_id=student_id,
            )
        )
    except (
        InterviewNotFoundError,
        InterviewAccessError,
        InterviewConflictError,
    ) as exc:
        _raise_interview_error(exc)
