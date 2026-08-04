"""隐私安全的 A6 产物审计写入。

调用方只能提供枚举式事件字段；此接口没有任意 metadata 字段，避免误写正文、
原文件名、联系方式或原始 bearer/idempotency token。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.artifact_audit import ArtifactAuditEvent


def add_artifact_event(
    db: Session,
    *,
    owner_subject_id: str,
    operation: str,
    event_type: str,
    outcome: str,
    reason_code: str,
    document_id: str | None = None,
    idempotency_key_digest: str | None = None,
    scan_method: str | None = None,
) -> ArtifactAuditEvent:
    event = ArtifactAuditEvent(
        event_id=str(uuid.uuid4()),
        owner_subject_id=owner_subject_id,
        operation=operation,
        idempotency_key_digest=idempotency_key_digest,
        document_id=document_id,
        event_type=event_type,
        outcome=outcome,
        reason_code=reason_code,
        scan_method=scan_method,
    )
    db.add(event)
    return event


def commit_artifact_event(
    db: Session,
    **fields,
) -> ArtifactAuditEvent:
    """单独持久化失败前事件；审计不可写时安全动作失败关闭。"""

    try:
        event = add_artifact_event(db, **fields)
        db.commit()
        db.refresh(event)
        return event
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="安全审计暂不可用，文件操作已停止",
        ) from exc


def validation_reason(exc: HTTPException) -> tuple[str, str]:
    detail = str(exc.detail)
    if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        return "scan_unavailable", "scanner_unavailable"
    if exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
        return "parse_rejected", "parse_budget_exceeded"
    if any(
        marker in detail
        for marker in ("反病毒", "主动内容", "宏", "嵌入对象", "ActiveX")
    ):
        return "scan_rejected", "unsafe_content"
    return "parse_rejected", "document_parse_rejected"
