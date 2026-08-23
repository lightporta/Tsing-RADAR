"""站内投递应用服务；只记录状态，不联系任何第三方。"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.private_document import PrivateDocument
from app.models.recruitment import Recruitment
from app.services.data_loader import load_mentors
from app.services.idempotency import (
    begin_idempotency,
    complete_idempotency,
    fail_idempotency,
)
from app.services.document_locking import lock_private_document


def _published_recruitment_ids(db: Session) -> set[str]:
    identifiers = {
        item["recruit_id"]
        for mentor in load_mentors()
        for item in (mentor.get("recruitments") or [])
        if item.get("recruit_id")
    }
    records = db.query(Recruitment).all()
    identifiers.update(
        record.recruit_id
        for record in records
        if record.review_status == "verified"
        and record.publication_status == "published"
        and record.takedown_at is None
    )
    return identifiers


def create_in_app_application(
    db: Session,
    *,
    subject_id: str,
    recruit_id: str,
    document_id: str,
    confirmed: bool,
    idempotency_key: str,
) -> Application:
    if not confirmed:
        raise HTTPException(
            status_code=422,
            detail="必须明确确认仅创建站内投递记录，不会向第三方发送文件",
        )
    claim = begin_idempotency(
        db,
        owner_subject_id=subject_id,
        operation="create_in_app_application",
        key=idempotency_key,
        payload={
            "recruit_id": recruit_id,
            "document_id": document_id,
            "confirm_in_app_only": confirmed,
        },
    )
    if claim.replayed:
        application = db.get(Application, claim.record.resource_id)
        if application is None or application.student_id != subject_id:
            raise HTTPException(status_code=410, detail="此前站内投递记录已不可用")
        return application

    try:
        if recruit_id not in _published_recruitment_ids(db):
            raise HTTPException(status_code=409, detail="目标招募未通过审核或已下架")

        document = lock_private_document(db, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="私有文档不存在")
        if document.owner_subject_id != subject_id:
            raise HTTPException(status_code=403, detail="无权使用该私有文档")
        if document.status != "ready" or document.scan_status != "clean":
            raise HTTPException(
                status_code=409,
                detail="文件已进入删除或未通过扫描，不能创建站内投递",
            )

        application = Application(
            app_id=str(uuid.uuid4()),
            recruit_id=recruit_id,
            student_id=subject_id,
            resume_id=document_id,
            status="submitted_in_app",
        )
        db.add(application)
        db.flush()
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="application",
            resource_id=application.app_id,
            commit=False,
        )
        db.commit()
        db.refresh(application)
        return application
    except IntegrityError as exc:
        db.rollback()
        conflict = HTTPException(
            status_code=409,
            detail="该文档已有有效站内投递记录",
        )
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=conflict,
        )
        raise conflict from exc
    except Exception as exc:
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
        )
        raise


def public_application_item(application: Application) -> dict:
    return {
        "app_id": application.app_id,
        "recruit_id": application.recruit_id,
        "document_id": application.resume_id,
        "status": application.status,
        "delivery": "in_app_only_no_external_delivery",
        "created_at": application.created_at,
        "updated_at": application.updated_at,
    }
