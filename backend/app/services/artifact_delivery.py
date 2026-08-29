"""A6 短时签名下载与清小搭平台转存授权。"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from urllib.parse import quote

from fastapi import HTTPException, status
from fastapi.responses import Response
from sqlalchemy import case, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.private_document import ArtifactDeliveryGrant, PrivateDocument
from app.models.idempotency import IdempotencyRecord
from app.services.artifact_audit import add_artifact_event, commit_artifact_event
from app.services.idempotency import (
    begin_idempotency,
    complete_idempotency,
    fail_idempotency,
)
from app.services.identity import Principal
from app.services.object_storage import ObjectStorageError
from app.services.private_documents import read_private_document_bytes


@dataclass(frozen=True)
class IssuedDeliveryGrant:
    download_url: str
    expires_at: datetime
    audience: str


@dataclass(frozen=True)
class RedeemedArtifact:
    document: PrivateDocument
    payload: bytes


def artifact_download_response(redeemed: RedeemedArtifact) -> Response:
    document = redeemed.document
    ascii_name = re_safe_ascii_filename(document.original_name)
    encoded_name = quote(document.original_name, safe="")
    return Response(
        content=redeemed.payload,
        media_type=document.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{encoded_name}"
            ),
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Content-Length": str(len(redeemed.payload)),
            "X-Artifact-SHA256": document.sha256,
        },
    )


def re_safe_ascii_filename(value: str) -> str:
    sanitized = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "._- ")
        else "_"
        for character in value
    ).strip(" .")
    return sanitized[:160] or "download"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _keyed_digest(value: str, *, purpose: str) -> str:
    return hmac.new(
        settings.ARTIFACT_SIGNING_SECRET.encode("utf-8"),
        f"{purpose}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _make_token(grant_id: str, nonce: str | None = None) -> str:
    nonce = nonce or secrets.token_urlsafe(32)
    unsigned = f"v1.{grant_id}.{nonce}"
    signature = _keyed_digest(unsigned, purpose="artifact-url")
    return f"{unsigned}.{signature}"


# —— 雷达图轻量签名令牌 ——
# 雷达图由已发布的公开评分确定性渲染，不落对象存储、不走私有文档管线；
# 令牌即凭证（HMAC 签名 + 短时过期），与附件令牌共用签名密钥但用途域独立。

_RADAR_ADVISOR_ID_PATTERN = re.compile(r"[A-Za-z0-9_\-]{1,64}")


def issue_radar_chart_token(
    advisor_id: str, *, ttl_seconds: int | None = None
) -> tuple[str, datetime]:
    """为公开评分雷达图签发短时令牌；返回 (token, expires_at)。"""
    normalized = (advisor_id or "").strip()
    if not _RADAR_ADVISOR_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="advisor_id 非法"
        )
    ttl = settings.QXD_ATTACHMENT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    expires_epoch = int(expires_at.timestamp())
    unsigned = f"v1.{normalized}.{expires_epoch}"
    signature = _keyed_digest(unsigned, purpose="radar-url")
    return f"{unsigned}.{signature}", expires_at


def redeem_radar_chart_token(token: str) -> str:
    """校验雷达图令牌；有效返回 advisor_id，篡改返回 404、过期返回 410。"""
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="雷达图链接不存在"
        )
    _, advisor_id, expires_epoch_text, signature = parts
    if not _RADAR_ADVISOR_ID_PATTERN.fullmatch(advisor_id) or not expires_epoch_text.isdigit():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="雷达图链接不存在"
        )
    unsigned = f"v1.{advisor_id}.{expires_epoch_text}"
    expected = _keyed_digest(unsigned, purpose="radar-url")
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="雷达图链接不存在"
        )
    expires_at = datetime.fromtimestamp(int(expires_epoch_text), tz=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="雷达图链接已过期"
        )
    return advisor_id


def _validate_public_base_url() -> str:
    raw = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="清小搭附件交付尚未配置公网 HTTPS 根地址",
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="清小搭附件交付尚未配置公网 HTTPS 根地址",
        )
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="清小搭附件交付尚未配置公网 HTTPS 根地址",
        ) from exc
    if (
        host == "localhost"
        or "." not in host
        or host.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="清小搭附件交付尚未配置公网 HTTPS 根地址",
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        test_domain = (
            host in {"example.com", "example.net", "example.org", "example.edu"}
            or host.endswith(
                (
                    ".example.com",
                    ".example.net",
                    ".example.org",
                    ".example.edu",
                    ".example",
                    ".test",
                    ".invalid",
                )
            )
        )
        if test_domain and not (
            settings.DEBUG and settings.ALLOW_TEST_PUBLIC_BASE_URL
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="清小搭附件交付尚未配置真实公网 HTTPS 根地址",
            )
    else:
        if not address.is_global:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="清小搭附件交付根地址不得指向非公网 IP",
            )
    return raw


def assert_qxd_delivery_ready() -> None:
    _validate_public_base_url()


def issue_delivery_grant(
    db: Session,
    *,
    document: PrivateDocument,
    principal: Principal,
    audience: str,
    confirmed: bool,
    idempotency_key: str,
) -> IssuedDeliveryGrant:
    if document.owner_subject_id != principal.subject_id:
        raise HTTPException(status_code=403, detail="无权交付该文件")
    if document.status != "ready" or document.scan_status != "clean":
        raise HTTPException(
            status_code=409,
            detail="文件尚未通过当前扫描策略，不能交付",
        )

    if audience == "web_private":
        if principal.channel != "web" or not principal.persistent:
            raise HTTPException(status_code=403, detail="Web 私有下载会话无效")
        ttl_seconds = settings.WEB_DOWNLOAD_TTL_SECONDS
        max_downloads = 1
        url_prefix = "/api/artifacts/download"
    elif audience == "qxd_platform":
        if principal.channel != "qxd" or not principal.persistent:
            raise HTTPException(
                status_code=403,
                detail="缺少可验证终端用户身份，不能生成清小搭附件",
            )
        if document.document_kind != "match_report":
            raise HTTPException(
                status_code=422,
                detail="清小搭短时公开转存只允许已确认生成的匹配报告",
            )
        ttl_seconds = settings.QXD_ATTACHMENT_TTL_SECONDS
        max_downloads = 3
        url_prefix = f"{_validate_public_base_url()}/v1/attachments"
    else:
        raise HTTPException(status_code=422, detail="未知交付受众")

    operation = f"issue_delivery_grant:{audience}"
    claim = begin_idempotency(
        db,
        owner_subject_id=principal.subject_id,
        operation=operation,
        key=idempotency_key,
        payload={
            "document_id": document.document_id,
            "audience": audience,
            "confirmed": confirmed,
        },
    )
    if claim.replayed:
        grant = db.get(ArtifactDeliveryGrant, claim.record.resource_id)
        if grant is None or grant.owner_subject_id != principal.subject_id:
            raise HTTPException(status_code=410, detail="此前交付授权已不可用")
        if not grant.token_nonce:
            raise HTTPException(status_code=410, detail="此前交付授权无法安全重放")
        return IssuedDeliveryGrant(
            download_url=(
                f"{url_prefix}/{_make_token(grant.grant_id, grant.token_nonce)}"
            ),
            expires_at=grant.expires_at,
            audience=audience,
        )

    if not confirmed:
        exc = HTTPException(
            status_code=422,
            detail="生成下载链接前必须明确确认本次交付",
        )
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
            commit=False,
        )
        commit_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation=operation,
            idempotency_key_digest=claim.record.key_digest,
            document_id=document.document_id,
            event_type="grant_rejected",
            outcome="rejected",
            reason_code="explicit_confirmation_missing",
            scan_method=document.scan_method,
        )
        raise exc

    grant_id = str(uuid.uuid4())
    token_nonce = secrets.token_urlsafe(32)
    token = _make_token(grant_id, token_nonce)
    expires_at = _now() + timedelta(seconds=ttl_seconds)
    grant = ArtifactDeliveryGrant(
        grant_id=grant_id,
        document_id=document.document_id,
        owner_subject_id=principal.subject_id,
        audience=audience,
        token_digest=_keyed_digest(token, purpose="artifact-token"),
        token_nonce=token_nonce,
        expires_at=expires_at,
        max_downloads=max_downloads,
        use_count=0,
        confirmed_at=_now(),
        revoked=False,
    )
    try:
        db.execute(
            update(ArtifactDeliveryGrant)
            .where(
                ArtifactDeliveryGrant.document_id == document.document_id,
                ArtifactDeliveryGrant.audience == audience,
                ArtifactDeliveryGrant.revoked.is_(False),
            )
            .values(revoked=True)
            .execution_options(synchronize_session=False)
        )
        db.add(grant)
        db.flush()
        add_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation=operation,
            idempotency_key_digest=claim.record.key_digest,
            document_id=document.document_id,
            event_type="grant_issued",
            outcome="success",
            reason_code=f"{audience}_short_lived_grant",
            scan_method=document.scan_method,
        )
        complete_idempotency(
            db,
            record=claim.record,
            attempt_token=claim.attempt_token,
            resource_type="artifact_delivery_grant",
            resource_id=grant_id,
            commit=False,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        conflict = HTTPException(
            status_code=409,
            detail="文件状态已变化，不能创建交付授权",
        )
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=conflict,
            commit=False,
        )
        commit_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation=operation,
            idempotency_key_digest=claim.record.key_digest,
            document_id=document.document_id,
            event_type="grant_rejected",
            outcome="failed",
            reason_code="grant_concurrency_conflict",
            scan_method=document.scan_method,
        )
        raise conflict from exc
    except Exception as exc:
        db.rollback()
        fail_idempotency(
            db,
            record_id=claim.record.idempotency_id,
            attempt_token=claim.attempt_token,
            exc=exc,
            commit=False,
        )
        commit_artifact_event(
            db,
            owner_subject_id=principal.subject_id,
            operation=operation,
            idempotency_key_digest=claim.record.key_digest,
            document_id=document.document_id,
            event_type="grant_rejected",
            outcome="failed",
            reason_code="grant_issue_failed",
            scan_method=document.scan_method,
        )
        raise
    return IssuedDeliveryGrant(
        download_url=f"{url_prefix}/{token}",
        expires_at=expires_at,
        audience=audience,
    )


def _grant_idempotency_digest(
    db: Session,
    grant_id: str,
) -> str | None:
    record = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.resource_type == "artifact_delivery_grant",
            IdempotencyRecord.resource_id == grant_id,
        )
        .one_or_none()
    )
    return record.key_digest if record else None


def _audit_grant_rejection(
    db: Session,
    *,
    grant: ArtifactDeliveryGrant,
    document: PrivateDocument | None,
    reason_code: str,
) -> None:
    commit_artifact_event(
        db,
        owner_subject_id=grant.owner_subject_id,
        operation=f"redeem_delivery_grant:{grant.audience}",
        idempotency_key_digest=_grant_idempotency_digest(db, grant.grant_id),
        document_id=grant.document_id,
        event_type="grant_rejected",
        outcome="rejected",
        reason_code=reason_code,
        scan_method=document.scan_method if document else None,
    )


def redeem_delivery_token(
    db: Session,
    *,
    token: str,
    audience: str,
    principal: Principal | None,
) -> RedeemedArtifact:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        raise HTTPException(status_code=404, detail="下载授权不存在")
    _, grant_id, nonce, signature = parts
    unsigned = f"v1.{grant_id}.{nonce}"
    expected_signature = _keyed_digest(unsigned, purpose="artifact-url")
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=404, detail="下载授权不存在")

    grant = db.get(ArtifactDeliveryGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=410, detail="下载授权已过期或已使用")
    if grant.audience != audience:
        _audit_grant_rejection(
            db,
            grant=grant,
            document=db.get(PrivateDocument, grant.document_id),
            reason_code="audience_mismatch",
        )
        raise HTTPException(status_code=410, detail="下载授权已过期或已使用")

    if audience == "web_private":
        if (
            principal is None
            or principal.channel != "web"
            or principal.subject_id != grant.owner_subject_id
        ):
            _audit_grant_rejection(
                db,
                grant=grant,
                document=db.get(PrivateDocument, grant.document_id),
                reason_code="principal_mismatch",
            )
            raise HTTPException(status_code=403, detail="下载授权不属于当前会话")
    elif principal is not None:
        _audit_grant_rejection(
            db,
            grant=grant,
            document=db.get(PrivateDocument, grant.document_id),
            reason_code="audience_session_mismatch",
        )
        raise HTTPException(status_code=403, detail="公开转存端点不接受会话混用")

    document = db.get(PrivateDocument, grant.document_id)
    if (
        document is None
        or document.owner_subject_id != grant.owner_subject_id
        or document.status != "ready"
        or document.scan_status != "clean"
    ):
        _audit_grant_rejection(
            db,
            grant=grant,
            document=document,
            reason_code="document_not_deliverable",
        )
        raise HTTPException(status_code=410, detail="文件不可交付")

    now = _now()
    token_digest = _keyed_digest(token, purpose="artifact-token")
    consumed = db.execute(
        update(ArtifactDeliveryGrant)
        .where(
            ArtifactDeliveryGrant.grant_id == grant_id,
            ArtifactDeliveryGrant.token_digest == token_digest,
            ArtifactDeliveryGrant.audience == audience,
            ArtifactDeliveryGrant.revoked.is_(False),
            ArtifactDeliveryGrant.expires_at > now,
            ArtifactDeliveryGrant.use_count
            < ArtifactDeliveryGrant.max_downloads,
        )
        .values(
            use_count=ArtifactDeliveryGrant.use_count + 1,
            revoked=case(
                (
                    ArtifactDeliveryGrant.use_count + 1
                    >= ArtifactDeliveryGrant.max_downloads,
                    True,
                ),
                else_=False,
            ),
            last_downloaded_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        _audit_grant_rejection(
            db,
            grant=grant,
            document=document,
            reason_code="expired_revoked_or_consumed",
        )
        raise HTTPException(status_code=410, detail="下载授权已过期或已使用")
    add_artifact_event(
        db,
        owner_subject_id=grant.owner_subject_id,
        operation=f"redeem_delivery_grant:{audience}",
        idempotency_key_digest=_grant_idempotency_digest(db, grant.grant_id),
        document_id=document.document_id,
        event_type="grant_consumed",
        outcome="consumed",
        reason_code="download_quota_atomically_consumed",
        scan_method=document.scan_method,
    )
    db.commit()

    # 明确采用 burn-on-read-failure：原子消费后再读取对象。对象缺失、存储
    # 故障或完整性不一致都会消耗本次额度，并统一返回不可交付，不泄露后端细节。
    try:
        payload = read_private_document_bytes(document)
    except ObjectStorageError as exc:
        _audit_grant_rejection(
            db,
            grant=grant,
            document=document,
            reason_code="object_read_failed_after_consumption",
        )
        raise HTTPException(status_code=410, detail="文件当前不可交付") from exc
    if (
        len(payload) != document.size_bytes
        or hashlib.sha256(payload).hexdigest() != document.sha256
    ):
        _audit_grant_rejection(
            db,
            grant=grant,
            document=document,
            reason_code="object_integrity_failed_after_consumption",
        )
        raise HTTPException(status_code=410, detail="文件当前不可交付")
    commit_artifact_event(
        db,
        owner_subject_id=grant.owner_subject_id,
        operation=f"redeem_delivery_grant:{audience}",
        idempotency_key_digest=_grant_idempotency_digest(db, grant.grant_id),
        document_id=document.document_id,
        event_type="grant_redeemed",
        outcome="success",
        reason_code="artifact_bytes_delivered",
        scan_method=document.scan_method,
    )
    return RedeemedArtifact(document=document, payload=payload)
