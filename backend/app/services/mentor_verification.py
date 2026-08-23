"""导师校园卡人工审核（认领导师档案的前置身份审核）。

- 邮箱验证码只用于登录，不再视为导师身份认证；
- 校园卡支持 JPG/PNG/WebP/PDF，上传即扫描（builtin/ClamAV 同私有文档）；
- 管理员人工审核（审核人 + 审核说明必填）；
- 审核进入终态（approved/rejected）后立即清理私有材料对象，
  表内只保留哈希与状态等非正文元数据；
- 审计事件（mentor_campus_card_reviewed）不含正文。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.artifact_audit import ArtifactAuditEvent
from app.models.mentor_account import MentorAccount
from app.models.mentor_campus_card import (
    CARD_APPROVED,
    CARD_PENDING,
    CARD_REJECTED,
    MentorCampusCard,
)
from app.services.file_scanning import (
    ScanUnavailableError,
    UnsafeContentError,
    scan_payload,
)
from app.services.object_storage import (
    ObjectStorageError,
    get_object_store,
    get_object_store_for_backend,
)

# 校园卡支持的媒体类型与扩展名（修改说明 §1：JPG、PNG、WebP、PDF）
CAMPUS_CARD_MEDIA: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
MAX_CAMPUS_CARD_BYTES = 8 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _card_public_view(card: MentorCampusCard, *, account: MentorAccount) -> dict:
    return {
        "card_id": card.card_id,
        "status": card.status,
        "media_type": card.media_type,
        "size_bytes": card.size_bytes,
        "uploaded_at": card.uploaded_at.isoformat()
        if card.uploaded_at is not None
        else None,
        "reviewed_at": card.reviewed_at.isoformat()
        if card.reviewed_at is not None
        else None,
        "review_note": card.review_note if card.status != CARD_PENDING else None,
        "material_cleared": card.material_cleared_at is not None,
        "email": account.email,
    }


def _audit_event(
    db: Session,
    *,
    account: MentorAccount,
    operation: str,
    outcome: str,
    reason_code: str,
    card_id: str,
) -> None:
    # 审计不含正文：只有操作、结果与原因码
    db.add(
        ArtifactAuditEvent(
            event_id=str(uuid.uuid4()),
            owner_subject_id=account.subject_id,
            operation=operation,
            document_id=card_id,
            event_type="mentor_campus_card_reviewed",
            outcome=outcome,
            reason_code=reason_code,
        )
    )


def _delete_card_material(card: MentorCampusCard) -> None:
    if not card.object_key:
        return
    try:
        get_object_store_for_backend(card.object_backend or "local").delete(
            card.object_key
        )
    except ObjectStorageError:
        # 材料清理失败不阻断审核结果，但保留键以便人工重试
        return
    card.object_key = ""


def latest_card(db: Session, *, account_id: str) -> MentorCampusCard | None:
    return (
        db.query(MentorCampusCard)
        .filter(MentorCampusCard.account_id == account_id)
        .order_by(MentorCampusCard.uploaded_at.desc())
        .first()
    )


def campus_card_status(db: Session, *, account: MentorAccount) -> dict:
    card = latest_card(db, account_id=account.account_id)
    if card is None:
        return {
            "status": "none",
            "eligible_to_claim": False,
            "card": None,
        }
    return {
        "status": card.status,
        "eligible_to_claim": card.status == CARD_APPROVED,
        "card": _card_public_view(card, account=account),
    }


def campus_card_approved(db: Session, *, account_id: str) -> bool:
    card = latest_card(db, account_id=account_id)
    return card is not None and card.status == CARD_APPROVED


async def upload_campus_card(
    db: Session,
    *,
    account: MentorAccount,
    upload: UploadFile,
) -> dict:
    """上传校园卡（每账号至多一条待审记录，重复上传替换旧待审材料）。"""
    filename = Path(upload.filename or "").name.lower()
    extension = Path(filename).suffix.lower()
    expected_media = CAMPUS_CARD_MEDIA.get(extension)
    if expected_media is None:
        raise HTTPException(
            status_code=415,
            detail="校园卡仅支持 JPG、PNG、WebP 或 PDF",
        )
    payload = await upload.read()
    if not payload:
        raise HTTPException(status_code=422, detail="校园卡文件为空")
    if len(payload) > MAX_CAMPUS_CARD_BYTES:
        raise HTTPException(status_code=413, detail="校园卡文件不能超过 8 MB")
    if (upload.content_type or "").split(";")[0].strip() != expected_media:
        raise HTTPException(status_code=415, detail="文件 MIME 与扩展名不一致")
    try:
        scan = scan_payload(payload, extension)
    except UnsafeContentError as exc:
        raise HTTPException(status_code=422, detail=f"校园卡未通过安全扫描：{exc}")
    except ScanUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"扫描服务不可用：{exc}")

    # 替换旧待审记录（保留历史终态记录用于追溯）
    previous = latest_card(db, account_id=account.account_id)
    if previous is not None and previous.status == CARD_PENDING:
        _delete_card_material(previous)
        db.delete(previous)
        db.flush()

    object_store = get_object_store()
    object_key = f"campus-cards/{uuid.uuid4().hex}{extension}"
    try:
        object_store.put_bytes(object_key, payload, expected_media)
    except ObjectStorageError as exc:
        raise HTTPException(status_code=503, detail=f"校园卡存储失败：{exc}")

    card = MentorCampusCard(
        card_id=str(uuid.uuid4()),
        account_id=account.account_id,
        object_backend=object_store.backend_name,
        object_key=object_key,
        media_type=expected_media,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        status=CARD_PENDING,
    )
    db.add(card)
    db.commit()
    return {
        "status": CARD_PENDING,
        "card_id": card.card_id,
        "scan_method": scan.method,
    }


def list_campus_cards(
    db: Session, *, status_filter: str | None = None
) -> list[dict]:
    query = db.query(MentorCampusCard, MentorAccount).join(
        MentorAccount,
        MentorCampusCard.account_id == MentorAccount.account_id,
    )
    if status_filter:
        query = query.filter(MentorCampusCard.status == status_filter)
    rows = query.order_by(MentorCampusCard.uploaded_at.desc()).all()
    # 管理端队列不含对象键与文件正文；材料待审时才可见待审状态
    return [
        {
            "card_id": card.card_id,
            "status": card.status,
            "media_type": card.media_type,
            "size_bytes": card.size_bytes,
            "sha256": card.sha256,
            "uploaded_at": card.uploaded_at.isoformat()
            if card.uploaded_at is not None
            else None,
            "email": account.email,
            "account_status": account.status,
        }
        for card, account in rows
    ]


def review_campus_card(
    db: Session,
    *,
    card_id: str,
    action: str,
    reviewer: str,
    note: str,
) -> dict:
    """管理员人工审核；终态立即清理私有材料并写入不含正文的审计事件。"""
    card = db.get(MentorCampusCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="校园卡记录不存在")
    if card.status != CARD_PENDING:
        raise HTTPException(status_code=409, detail="该校园卡已完成审核")
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="审核动作必须是 approve/reject")
    cleaned_note = (note or "").strip()
    if not cleaned_note:
        raise HTTPException(status_code=422, detail="审核说明不能为空")

    account = (
        db.query(MentorAccount)
        .filter(MentorAccount.account_id == card.account_id)
        .one_or_none()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="校园卡关联的导师账号不存在")

    now = _now()
    card.status = CARD_APPROVED if action == "approve" else CARD_REJECTED
    card.reviewed_by = reviewer.strip()
    card.review_note = cleaned_note
    card.reviewed_at = now
    # 审核结束即清理私有材料（图片/PDF 对象）
    _delete_card_material(card)
    card.material_cleared_at = now

    _audit_event(
        db,
        account=account,
        operation="review_campus_card",
        outcome="approved" if action == "approve" else "rejected",
        reason_code=f"campus_card_{action}",
        card_id=card.card_id,
    )
    db.commit()
    return {
        "card_id": card.card_id,
        "status": card.status,
        "reviewed_by": card.reviewed_by,
        "material_cleared": card.material_cleared_at is not None,
    }
