"""A6 私有匹配报告与 Web 短时签名下载。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_idempotency_key, get_mutating_principal
from app.db.session import get_db
from app.models.private_document import PrivateDocument
from app.schemas.artifacts import (
    ArtifactItem,
    DownloadGrantItem,
    DownloadGrantRequest,
    MatchReportArtifactRequest,
)
from app.services.artifact_delivery import (
    artifact_download_response,
    issue_delivery_grant,
    redeem_delivery_token,
)
from app.services.artifact_generation import create_match_report_artifact
from app.services.identity import Principal
from app.services.private_documents import public_document_item

router = APIRouter(prefix="/artifacts")


def _owned_artifact(
    db: Session,
    document_id: str,
    subject_id: str,
) -> PrivateDocument:
    document = db.get(PrivateDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    if document.owner_subject_id != subject_id:
        raise HTTPException(status_code=403, detail="无权访问该文件")
    return document


@router.post("/match-report", response_model=ArtifactItem)
def create_match_report(
    request: MatchReportArtifactRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    document, _outcome = create_match_report_artifact(
        db,
        owner_subject_id=principal.subject_id,
        channel=principal.channel,
        session_id=request.session_id,
        output_format=request.format,
        confirmed=request.confirm_generation,
        idempotency_key=idempotency_key,
    )
    return public_document_item(document)


@router.post(
    "/{document_id}/download-grant",
    response_model=DownloadGrantItem,
)
def create_private_download_grant(
    document_id: str,
    request: DownloadGrantRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
    idempotency_key: str = Depends(get_idempotency_key),
):
    document = _owned_artifact(db, document_id, principal.subject_id)
    issued = issue_delivery_grant(
        db,
        document=document,
        principal=principal,
        audience="web_private",
        confirmed=request.confirm_private_download,
        idempotency_key=idempotency_key,
    )
    return {
        "download_url": issued.download_url,
        "expires_at": issued.expires_at,
        "audience": issued.audience,
    }


@router.post("/download/{token}")
def download_private_artifact(
    token: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_mutating_principal),
):
    redeemed = redeem_delivery_token(
        db,
        token=token,
        audience="web_private",
        principal=principal,
    )
    return artifact_download_response(redeemed)
