"""导师档案与字段级编辑 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import (
    MentorPrincipal,
    get_mentor_principal,
    get_mutating_mentor_principal,
)
from app.db.session import get_db
from app.schemas.mentor import FieldEditRequest
from app.services.mentor_profile import (
    get_mentor_profile,
    list_my_edits,
    submit_field_edit,
)

router = APIRouter(prefix="/mentor")


@router.get("")
def mentor_me(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    """我的完整档案（导师端可见；含公开字段、过审自述与可见性策略）。"""
    return get_mentor_profile(db, account=mentor.account)


@router.get("/profile/edits")
def my_field_edits(
    mentor: MentorPrincipal = Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    return {"data": list_my_edits(db, account=mentor.account)}


@router.post("/profile/edits")
def submit_field_edit_endpoint(
    request: FieldEditRequest,
    mentor: MentorPrincipal = Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    edit = submit_field_edit(
        db,
        account=mentor.account,
        field_name=request.field_name,
        new_value=request.new_value,
    )
    return {
        "edit_id": edit.edit_id,
        "field_name": edit.field_name,
        "status": edit.status,
    }
