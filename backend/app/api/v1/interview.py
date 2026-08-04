"""A3 动态访谈、画像编辑与确认 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_student, get_mutating_student
from app.db.session import get_db
from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewConfirmRequest,
    InterviewCreateRequest,
    InterviewStateResponse,
    StudentPortraitPatch,
)
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

router = APIRouter(prefix="/interviews")


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
