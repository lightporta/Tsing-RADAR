"""受控 PDF/DOCX 验证、扫描、解析与私有对象存储。"""

from __future__ import annotations

import hashlib
import hmac
import io
import multiprocessing
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from fastapi import HTTPException, UploadFile, status
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.application import Application
from app.models.private_document import (
    ArtifactDeliveryGrant,
    DeletedArtifactTombstone,
    PrivateDocument,
)
from app.services.file_scanning import (
    ScanUnavailableError,
    UnsafeContentError,
    scan_payload,
)
from app.services.artifact_audit import (
    add_artifact_event,
    commit_artifact_event,
    validation_reason,
)
from app.services.object_storage import (
    ObjectStorageError,
    get_object_store,
    get_object_store_for_backend,
)
from app.services.document_locking import lock_private_document

_ALLOWED_MEDIA = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_DOCX_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_MAX_DOCX_ENTRIES = 256
_MAX_DOCX_UNCOMPRESSED = 40 * 1024 * 1024


def _pdf_parse_worker(
    payload: bytes,
    max_pages: int,
    max_page_chars: int,
    max_total_chars: int,
    connection,
) -> None:
    """在可终止子进程中解析不可信 PDF，避免主服务被解压流长期占用。"""

    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted:
            connection.send(("invalid", "encrypted"))
            return
        if len(reader.pages) > max_pages:
            connection.send(("budget", "page_count"))
            return
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            if len(text) > max_page_chars:
                connection.send(("budget", "page_text"))
                return
            total += len(text)
            if total > max_total_chars:
                connection.send(("budget", "total_text"))
                return
            parts.append(text)
        connection.send(("ok", "\n".join(parts).strip()))
    except Exception:
        connection.send(("invalid", "parse_error"))
    finally:
        connection.close()


def safe_original_name(filename: str | None) -> tuple[str, str]:
    if not filename:
        raise HTTPException(status_code=422, detail="文件名不能为空")
    leaf = Path(filename.replace("\\", "/")).name
    extension = Path(leaf).suffix.lower()
    if extension not in _ALLOWED_MEDIA:
        raise HTTPException(status_code=415, detail="仅支持 PDF 或 DOCX")
    stem = re.sub(r"[^\w\u4e00-\u9fff .()-]", "_", Path(leaf).stem).strip(" .")
    if not stem:
        stem = "document"
    return f"{stem[:160]}{extension}", extension


async def _read_limited(upload: UploadFile) -> bytes:
    payload = await upload.read(settings.PRIVATE_UPLOAD_MAX_BYTES + 1)
    if len(payload) > settings.PRIVATE_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件超过大小限制",
        )
    if not payload:
        raise HTTPException(status_code=422, detail="文件内容为空")
    return payload


def _extract_pdf(payload: bytes) -> str:
    if not payload.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="PDF magic 与扩展名不一致")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_pdf_parse_worker,
        args=(
            payload,
            settings.PDF_MAX_PAGES,
            settings.PDF_MAX_PAGE_TEXT_CHARS,
            settings.PDF_MAX_EXTRACTED_TEXT_CHARS,
            child,
        ),
        daemon=True,
    )
    try:
        process.start()
        child.close()
        if not parent.poll(settings.PDF_PARSE_TIMEOUT_SECONDS):
            process.terminate()
            process.join(timeout=1)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="PDF 解析工作量超过安全预算",
            )
        try:
            result_type, result = parent.recv()
        except EOFError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="PDF 解压或解析进程超出安全预算",
            ) from exc
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if result_type == "ok":
            return result
        if result_type == "budget":
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"PDF 超过安全解析预算：{result}",
            )
        raise HTTPException(status_code=422, detail="PDF 无法安全解析")
    finally:
        parent.close()
        child.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)


def _extract_docx(payload: bytes) -> str:
    if not payload.startswith(b"PK"):
        raise HTTPException(status_code=415, detail="DOCX magic 与扩展名不一致")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            if (
                len(infos) > _MAX_DOCX_ENTRIES
                or sum(item.file_size for item in infos) > _MAX_DOCX_UNCOMPRESSED
                or "[Content_Types].xml" not in names
                or "word/document.xml" not in names
            ):
                raise ValueError("invalid package")
            for item in infos:
                path = Path(item.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("unsafe zip path")
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="DOCX 无法安全解析") from exc
    return "\n".join(
        node.text or "" for node in root.iter(_DOCX_TEXT_TAG)
    ).strip()


def validate_and_extract_document(
    *,
    payload: bytes,
    filename: str,
    media_type: str,
) -> tuple[str, str, str, object]:
    safe_name, extension = safe_original_name(filename)
    expected_media = _ALLOWED_MEDIA[extension]
    if media_type.lower() != expected_media:
        raise HTTPException(status_code=415, detail="文件 MIME 与扩展名不一致")
    try:
        scan = scan_payload(payload, extension)
    except UnsafeContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScanUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="文件扫描服务不可用，已停止接收文件",
        ) from exc
    extracted = (
        _extract_pdf(payload)
        if extension == ".pdf"
        else _extract_docx(payload)
    )
    return safe_name, extension, extracted, scan


def store_private_artifact(
    db: Session,
    *,
    owner_subject_id: str,
    original_name: str,
    payload: bytes,
    media_type: str,
    document_kind: str,
    extracted_text: str,
    scan_result,
    source_session_id: str | None = None,
    generation_context: dict | None = None,
    user_confirmed_at: datetime | None = None,
    commit: bool = True,
) -> PrivateDocument:
    safe_name, extension = safe_original_name(original_name)
    expected_media = _ALLOWED_MEDIA[extension]
    if media_type != expected_media:
        raise HTTPException(status_code=415, detail="文件 MIME 与扩展名不一致")
    object_store = get_object_store()
    object_key = f"objects/{uuid.uuid4().hex}{extension}"
    try:
        object_store.put_bytes(object_key, payload, media_type)
        document = PrivateDocument(
            document_id=str(uuid.uuid4()),
            owner_subject_id=owner_subject_id,
            original_name=safe_name,
            stored_name=object_key,
            extension=extension,
            media_type=expected_media,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            status="ready",
            extracted_text=extracted_text,
            document_kind=document_kind,
            object_backend=object_store.backend_name,
            scan_status=scan_result.status,
            scan_method=scan_result.method,
            scan_checked_at=scan_result.checked_at,
            source_session_id=source_session_id,
            generation_context=generation_context or {},
            user_confirmed_at=user_confirmed_at,
        )
        db.add(document)
        if commit:
            db.commit()
            db.refresh(document)
        else:
            db.flush()
        return document
    except Exception:
        try:
            object_store.delete(object_key)
        except ObjectStorageError:
            pass
        db.rollback()
        raise


def discard_private_artifact_object(document: PrivateDocument | None) -> None:
    if document is None:
        return
    try:
        get_object_store_for_backend(document.object_backend).delete(
            document.stored_name
        )
    except ObjectStorageError:
        pass


async def save_private_document(
    db: Session,
    *,
    upload: UploadFile,
    owner_subject_id: str,
) -> PrivateDocument:
    scan_method = (
        "clamav-instream-plus-structural-v1"
        if settings.FILE_SCAN_MODE == "clamav"
        else "builtin-structural-signature-v1-not-full-antivirus"
    )
    try:
        payload = await _read_limited(upload)
    except HTTPException:
        commit_artifact_event(
            db,
            owner_subject_id=owner_subject_id,
            operation="upload_document",
            event_type="upload_rejected",
            outcome="rejected",
            reason_code="compressed_size_limit_or_empty",
            scan_method=scan_method,
        )
        raise
    try:
        safe_name, _extension, extracted, scan = validate_and_extract_document(
            payload=payload,
            filename=upload.filename or "",
            media_type=(upload.content_type or "").lower(),
        )
    except HTTPException as exc:
        event_type, reason_code = validation_reason(exc)
        commit_artifact_event(
            db,
            owner_subject_id=owner_subject_id,
            operation="upload_document",
            event_type=event_type,
            outcome="rejected",
            reason_code=reason_code,
            scan_method=scan_method,
        )
        raise

    document: PrivateDocument | None = None
    try:
        document = store_private_artifact(
            db,
            owner_subject_id=owner_subject_id,
            original_name=safe_name,
            payload=payload,
            media_type=(upload.content_type or "").lower(),
            document_kind="upload",
            extracted_text=extracted,
            scan_result=scan,
            commit=False,
        )
        add_artifact_event(
            db,
            owner_subject_id=owner_subject_id,
            operation="upload_document",
            document_id=document.document_id,
            event_type="scan_completed",
            outcome="success",
            reason_code="scan_clean",
            scan_method=scan.method,
        )
        add_artifact_event(
            db,
            owner_subject_id=owner_subject_id,
            operation="upload_document",
            document_id=document.document_id,
            event_type="upload_completed",
            outcome="success",
            reason_code="private_object_stored",
            scan_method=scan.method,
        )
        db.commit()
        db.refresh(document)
        return document
    except Exception as exc:
        db.rollback()
        discard_private_artifact_object(document)
        if isinstance(exc, HTTPException):
            raise
        commit_artifact_event(
            db,
            owner_subject_id=owner_subject_id,
            operation="upload_document",
            document_id=document.document_id if document else None,
            event_type="upload_failed",
            outcome="failed",
            reason_code="private_store_failed",
            scan_method=scan.method,
        )
        raise


def delete_private_document_file(document: PrivateDocument) -> None:
    get_object_store_for_backend(document.object_backend).delete(
        document.stored_name
    )


def delete_private_document_consistently(
    db: Session,
    *,
    document: PrivateDocument,
    idempotency_key_digest: str | None = None,
) -> None:
    """Delete an artifact through a retry-safe three-phase state machine.

    Phase 1 commits the non-deliverable ``deleting`` state and removes all
    outstanding grants before object I/O.  A storage failure therefore cannot
    leave a ready-looking row or usable grant.  Phase 3 deletes metadata only
    after object deletion and records a minimal tombstone for idempotent owner
    retries.  If the final commit fails, the committed ``deleting`` row remains
    and a retry converges because object deletion is idempotent.
    """

    document_id = document.document_id
    owner_subject_id = document.owner_subject_id
    locked = lock_private_document(db, document_id)
    if locked is None or locked.owner_subject_id != owner_subject_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if locked.status not in {"ready", "deleting", "delete_failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档状态已变化，请刷新后重试",
        )
    active_application = (
        db.query(Application)
        .filter(
            Application.resume_id == document_id,
            Application.status != "withdrawn",
        )
        .first()
    )
    if active_application is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档仍被站内投递记录引用",
        )
    locked.status = "deleting"
    document = locked
    db.query(ArtifactDeliveryGrant).filter(
        ArtifactDeliveryGrant.document_id == document.document_id
    ).delete(synchronize_session=False)
    add_artifact_event(
        db,
        owner_subject_id=document.owner_subject_id,
        operation="delete_document",
        idempotency_key_digest=idempotency_key_digest,
        document_id=document.document_id,
        event_type="delete_started",
        outcome="started",
        reason_code="delivery_disabled_before_object_delete",
        scan_method=document.scan_method,
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="删除尚未开始，请安全重试",
        ) from exc

    try:
        delete_private_document_file(document)
    except ObjectStorageError as exc:
        # The phase-1 commit already made the artifact non-deliverable and
        # removed its grants.  Preserve metadata for diagnosis and retry.
        persisted = db.get(PrivateDocument, document.document_id)
        if persisted is not None:
            persisted.status = "delete_failed"
            add_artifact_event(
                db,
                owner_subject_id=persisted.owner_subject_id,
                operation="delete_document",
                idempotency_key_digest=idempotency_key_digest,
                document_id=persisted.document_id,
                event_type="delete_failed",
                outcome="failed",
                reason_code="object_delete_failed",
                scan_method=persisted.scan_method,
            )
            try:
                db.commit()
            except Exception:
                # Remaining in the committed ``deleting`` state is also safe.
                db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="对象删除失败，文件已停止交付，可安全重试",
        ) from exc

    persisted = db.get(PrivateDocument, document.document_id)
    if persisted is None:
        return
    db.query(ArtifactDeliveryGrant).filter(
        ArtifactDeliveryGrant.document_id == persisted.document_id
    ).delete(synchronize_session=False)
    if db.get(DeletedArtifactTombstone, persisted.document_id) is None:
        db.add(
            DeletedArtifactTombstone(
                document_id=persisted.document_id,
                owner_subject_id=persisted.owner_subject_id,
                deleted_at=datetime.now(timezone.utc),
            )
        )
    add_artifact_event(
        db,
        owner_subject_id=persisted.owner_subject_id,
        operation="delete_document",
        idempotency_key_digest=idempotency_key_digest,
        document_id=persisted.document_id,
        event_type="delete_completed",
        outcome="success",
        reason_code="object_metadata_and_grants_removed",
        scan_method=persisted.scan_method,
    )
    db.delete(persisted)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        commit_artifact_event(
            db,
            owner_subject_id=document.owner_subject_id,
            operation="delete_document",
            idempotency_key_digest=idempotency_key_digest,
            document_id=document.document_id,
            event_type="delete_failed",
            outcome="failed",
            reason_code="metadata_cleanup_failed",
            scan_method=document.scan_method,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="对象已删除，元数据清理待安全重试",
        ) from exc


def read_private_document_bytes(document: PrivateDocument) -> bytes:
    if (
        document.size_bytes <= 0
        or document.size_bytes > settings.OBJECT_STORAGE_MAX_READ_BYTES
    ):
        raise ObjectStorageError("私有对象声明大小超出读取预算")
    payload = get_object_store_for_backend(document.object_backend).get_bytes(
        document.stored_name,
        max_bytes=document.size_bytes,
    )
    if len(payload) != document.size_bytes:
        raise ObjectStorageError("私有对象大小与元数据不一致")
    if not hmac.compare_digest(
        hashlib.sha256(payload).hexdigest(),
        document.sha256,
    ):
        raise ObjectStorageError("私有对象摘要与元数据不一致")
    return payload


def public_document_item(document: PrivateDocument) -> dict:
    return {
        "document_id": document.document_id,
        "original_name": document.original_name,
        "media_type": document.media_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "status": document.status,
        "document_kind": document.document_kind,
        "scan_status": document.scan_status,
        "scan_scope": (
            "full_antivirus"
            if document.scan_method.startswith("clamav-")
            else "structural_signature_only"
        ),
        "scan_checked_at": document.scan_checked_at,
        "text_preview": (document.extracted_text or "")[:500],
        "created_at": document.created_at,
    }
