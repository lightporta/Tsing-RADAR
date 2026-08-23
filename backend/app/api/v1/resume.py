"""A6 真实私有简历生成与兼容站内投递路由。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_idempotency_key, get_mutating_principal
from app.db.session import get_db
from app.schemas.resume import ResumeGenerateRequest, ResumeSubmitRequest
from app.services.applications import (
    create_in_app_application,
    public_application_item,
)
from app.services.artifact_generation import create_resume_artifact
from app.services.identity import Principal
from app.services.private_documents import public_document_item

router = APIRouter()


@router.post("/resume/generate")
def resume_generate(
    req: ResumeGenerateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    """确定性生成真实 PDF/DOCX；不调用外部模型，也不发送文件。"""
    document = create_resume_artifact(
        db,
        owner_subject_id=principal.subject_id,
        channel=principal.channel,
        request=req,
        idempotency_key=idempotency_key,
    )
    return public_document_item(document)


@router.post("/resume/submit")
def resume_submit(
    req: ResumeSubmitRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    """兼容入口，与 /applications 共用站内投递应用服务。"""
    application = create_in_app_application(
        db,
        subject_id=principal.subject_id,
        recruit_id=req.recruit_id,
        document_id=req.document_id,
        confirmed=req.confirm_in_app_only,
        idempotency_key=idempotency_key,
    )
    return public_application_item(application)
