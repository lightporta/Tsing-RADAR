"""A5 站内投递与状态 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_principal,
    get_idempotency_key,
    get_mutating_principal,
)
from app.db.session import get_db
from app.models.application import Application
from app.schemas.actions import (
    ApplicationCreateRequest,
    ApplicationItem,
    ApplicationUpdateRequest,
)
from app.services.applications import (
    create_in_app_application,
    public_application_item,
)
from app.services.identity import Principal

router = APIRouter(prefix="/applications")


def _owned_application(
    db: Session,
    app_id: str,
    subject_id: str,
) -> Application:
    application = db.get(Application, app_id)
    if application is None:
        raise HTTPException(status_code=404, detail="投递记录不存在")
    if application.student_id != subject_id:
        raise HTTPException(status_code=403, detail="无权访问该投递记录")
    return application


@router.post("", response_model=ApplicationItem)
def create_application(
    request: ApplicationCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    return public_application_item(
        create_in_app_application(
            db,
            subject_id=principal.subject_id,
            recruit_id=request.recruit_id,
            document_id=request.document_id,
            confirmed=request.confirm_in_app_only,
            idempotency_key=idempotency_key,
        )
    )


@router.get("", response_model=list[ApplicationItem])
def list_applications(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    records = (
        db.query(Application)
        .filter(Application.student_id == principal.subject_id)
        .order_by(Application.created_at.desc())
        .all()
    )
    return [public_application_item(item) for item in records]


@router.get("/{app_id}", response_model=ApplicationItem)
def get_application(
    app_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return public_application_item(
        _owned_application(db, app_id, principal.subject_id)
    )


@router.patch("/{app_id}", response_model=ApplicationItem)
def update_application(
    app_id: str,
    request: ApplicationUpdateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    application = _owned_application(db, app_id, principal.subject_id)
    if request.status != "withdrawn":
        raise HTTPException(status_code=422, detail="申请者只能撤回自己的站内投递")
    application.status = "withdrawn"
    db.commit()
    db.refresh(application)
    return public_application_item(application)


@router.delete("/{app_id}")
def delete_application(
    app_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    application = _owned_application(db, app_id, principal.subject_id)
    if application.status != "withdrawn":
        raise HTTPException(status_code=409, detail="请先撤回再删除投递记录")
    db.delete(application)
    db.commit()
    return {"status": "deleted"}
