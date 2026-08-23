"""服务端幂等键预留、请求指纹绑定与并发重放。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.idempotency import IdempotencyRecord

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_WAIT_SECONDS = 15.0
UNEXPECTED_FAILURE_DETAIL = "幂等操作失败；请使用新的幂等键重新发起"


@dataclass(frozen=True)
class IdempotencyClaim:
    record: IdempotencyRecord
    replayed: bool
    attempt_token: str | None


def validate_idempotency_key(value: str | None) -> str:
    if value is None or not _KEY_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Idempotency-Key 必填，且须为 8–128 位字母、数字或 . _ : -"
            ),
        )
    return value


def _keyed_digest(value: str, *, purpose: str) -> str:
    return hmac.new(
        settings.SESSION_HMAC_SECRET.encode("utf-8"),
        f"{purpose}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def request_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _keyed_digest(canonical, purpose="idempotency-request")


def idempotency_key_digest(operation: str, key: str) -> str:
    return _keyed_digest(
        f"{operation}:{key}",
        purpose="idempotency-key",
    )


def _attempt_digest(attempt_token: str) -> str:
    return _keyed_digest(
        attempt_token,
        purpose="idempotency-attempt",
    )


def _lookup(
    db: Session,
    *,
    owner_subject_id: str,
    operation: str,
    key_digest: str,
) -> IdempotencyRecord | None:
    return (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.owner_subject_id == owner_subject_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key_digest == key_digest,
        )
        .one_or_none()
    )


def _assert_same_request(
    record: IdempotencyRecord,
    fingerprint: str,
) -> None:
    if not hmac.compare_digest(record.request_fingerprint, fingerprint):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key 已绑定到不同请求",
        )


def _raise_recorded_failure(record: IdempotencyRecord) -> None:
    body = record.response_body if isinstance(record.response_body, dict) else {}
    raise HTTPException(
        status_code=record.response_status or status.HTTP_409_CONFLICT,
        detail=body.get("detail", "此前同一幂等请求已失败"),
    )


def _fail_stale_processing(
    db: Session,
    *,
    owner_subject_id: str,
    operation: str,
    key_digest: str,
) -> bool:
    """Atomically recover an idempotency key abandoned by a crashed worker.

    This is intentionally request-driven: no background scheduler is required
    for safety.  The next same-key retry changes a sufficiently old processing
    row into a stable, privacy-safe failure.  A caller may then use a new key
    to retry the operation without deleting or manually editing database rows.
    """

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(
        seconds=settings.IDEMPOTENCY_PROCESSING_TTL_SECONDS
    )
    result = db.execute(
        update(IdempotencyRecord)
        .execution_options(synchronize_session=False)
        .where(
            IdempotencyRecord.owner_subject_id == owner_subject_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key_digest == key_digest,
            IdempotencyRecord.status == "processing",
            IdempotencyRecord.updated_at < stale_before,
        )
        .values(
            status="failed",
            response_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            response_body={
                "detail": (
                    "此前幂等操作处理超时，已安全标记为失败；"
                    "请使用新的幂等键重试"
                )
            },
            attempt_digest=_attempt_digest(secrets.token_urlsafe(32)),
            completed_at=now,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    return True


def begin_idempotency(
    db: Session,
    *,
    owner_subject_id: str,
    operation: str,
    key: str,
    payload: Any,
) -> IdempotencyClaim:
    validated_key = validate_idempotency_key(key)
    key_digest = idempotency_key_digest(operation, validated_key)
    fingerprint = request_fingerprint(payload)
    attempt_token = secrets.token_urlsafe(32)
    record = IdempotencyRecord(
        idempotency_id=str(uuid.uuid4()),
        owner_subject_id=owner_subject_id,
        operation=operation,
        key_digest=key_digest,
        request_fingerprint=fingerprint,
        attempt_digest=_attempt_digest(attempt_token),
        status="processing",
    )
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
        return IdempotencyClaim(
            record=record,
            replayed=False,
            attempt_token=attempt_token,
        )
    except IntegrityError:
        db.rollback()

    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        db.rollback()
        existing = _lookup(
            db,
            owner_subject_id=owner_subject_id,
            operation=operation,
            key_digest=key_digest,
        )
        if existing is not None:
            _assert_same_request(existing, fingerprint)
            if existing.status == "completed":
                return IdempotencyClaim(
                    record=existing,
                    replayed=True,
                    attempt_token=None,
                )
            if existing.status == "failed":
                _raise_recorded_failure(existing)
            if _fail_stale_processing(
                db,
                owner_subject_id=owner_subject_id,
                operation=operation,
                key_digest=key_digest,
            ):
                # Re-read the persisted failure so all same-key callers receive
                # exactly the same status and privacy-safe response body.
                continue
        if time.monotonic() >= deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一幂等请求仍在处理中，请稍后以同一键重试",
                headers={"Retry-After": "1"},
            )
        time.sleep(0.025)


def complete_idempotency(
    db: Session,
    *,
    record: IdempotencyRecord,
    attempt_token: str | None,
    resource_type: str | None,
    resource_id: str | None,
    response_status: int = 200,
    response_body: dict | None = None,
    commit: bool = True,
) -> None:
    if not attempt_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="幂等尝试缺少有效租约，操作已回滚",
        )
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(IdempotencyRecord)
        .execution_options(synchronize_session=False)
        .where(
            IdempotencyRecord.idempotency_id == record.idempotency_id,
            IdempotencyRecord.status == "processing",
            IdempotencyRecord.attempt_digest
            == _attempt_digest(attempt_token),
        )
        .values(
            status="completed",
            resource_type=resource_type,
            resource_id=resource_id,
            response_status=response_status,
            response_body=response_body,
            completed_at=now,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="幂等尝试租约已失效，业务写入已回滚",
        )
    if commit:
        db.commit()


def fail_idempotency(
    db: Session,
    *,
    record_id: str,
    attempt_token: str | None,
    exc: Exception,
    commit: bool = True,
) -> bool:
    db.rollback()
    if not attempt_token:
        return False
    if isinstance(exc, HTTPException):
        response_status = exc.status_code
        detail = str(exc.detail)
    else:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = UNEXPECTED_FAILURE_DETAIL
    now = datetime.now(timezone.utc)
    try:
        result = db.execute(
            update(IdempotencyRecord)
            .execution_options(synchronize_session=False)
            .where(
                IdempotencyRecord.idempotency_id == record_id,
                IdempotencyRecord.status == "processing",
                IdempotencyRecord.attempt_digest
                == _attempt_digest(attempt_token),
            )
            .values(
                status="failed",
                response_status=response_status,
                response_body={"detail": detail},
                completed_at=now,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            return False
        if commit:
            db.commit()
        return True
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="幂等状态无法可靠持久化，操作已停止",
        ) from exc
