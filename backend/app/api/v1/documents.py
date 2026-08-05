"""A5 私有文件 API；仅返回当前主体可见的元数据，不提供公开 URL。"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_principal,
    get_idempotency_key,
    get_mutating_principal,
)
from app.db.session import get_db
from app.models.private_document import DeletedArtifactTombstone, PrivateDocument
from app.schemas.actions import DocumentDeleteRequest, DocumentItem
from app.services.idempotency import idempotency_key_digest
from app.services.identity import Principal
from app.services.private_documents import (
    delete_private_document_consistently,
    public_document_item,
    save_private_document,
)

router = APIRouter(prefix="/documents")


def _owned_document(
    db: Session,
    document_id: str,
    subject_id: str,
) -> PrivateDocument:
    document = db.get(PrivateDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if document.owner_subject_id != subject_id:
        raise HTTPException(status_code=403, detail="无权访问该文档")
    return document


@router.post("", response_model=DocumentItem)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    document = await save_private_document(
        db,
        upload=file,
        owner_subject_id=principal.subject_id,
    )
    return public_document_item(document)


@router.get("", response_model=list[DocumentItem])
def list_documents(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    records = (
        db.query(PrivateDocument)
        .filter(PrivateDocument.owner_subject_id == principal.subject_id)
        .order_by(PrivateDocument.created_at.desc())
        .all()
    )
    return [public_document_item(item) for item in records]


@router.get("/{document_id}", response_model=DocumentItem)
def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return public_document_item(
        _owned_document(db, document_id, principal.subject_id)
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    request: DocumentDeleteRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    if request.confirm_delete is not True:
        raise HTTPException(status_code=422, detail="必须明确确认删除私有文件")
    document = db.get(PrivateDocument, document_id)
    if document is None:
        tombstone = db.get(DeletedArtifactTombstone, document_id)
        if tombstone is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        if tombstone.owner_subject_id != principal.subject_id:
            raise HTTPException(status_code=403, detail="无权删除该文档")
        return {"status": "deleted", "idempotent": True}
    if document.owner_subject_id != principal.subject_id:
        raise HTTPException(status_code=403, detail="无权删除该文档")
    delete_private_document_consistently(
        db,
        document=document,
        idempotency_key_digest=idempotency_key_digest(
            "delete_document",
            idempotency_key,
        ),
    )
    return {"status": "deleted", "idempotent": False}
