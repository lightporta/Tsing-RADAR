"""证据化数据治理 Schema。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceType(str, Enum):
    PUBLIC_FACT = "public_fact"
    AUTHORIZED_SUBMISSION = "authorized_submission"
    AUTHORIZED_MESSAGE = "authorized_message"
    AGGREGATE_EVALUATION = "aggregate_evaluation"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    EXPIRED = "expired"
    DISPUTED = "disputed"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class PublicationStatus(str, Enum):
    RESTRICTED = "restricted"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class AuthorizationBasis(str, Enum):
    PUBLIC_SOURCE = "public_source"
    EXPLICIT_CONSENT = "explicit_consent"
    INSTITUTIONAL_AUTHORIZATION = "institutional_authorization"
    LEGACY_SEED = "legacy_seed"
    NONE = "none"


class TakedownStatus(str, Enum):
    ACTIVE = "active"
    REQUESTED = "requested"
    TAKEN_DOWN = "taken_down"


class QuarantineReason(str, Enum):
    UNSOURCED_FACT = "unsourced_fact"
    UNSUPPORTED_SUBJECTIVE_METRIC = "unsupported_subjective_metric"
    PERSONAL_DATA_REQUIRES_AUTHORIZATION = "personal_data_requires_authorization"
    TIME_SENSITIVE_DATA_REQUIRES_VERIFICATION = (
        "time_sensitive_data_requires_verification"
    )
    LEGACY_FIELD_REQUIRES_REVIEW = "legacy_field_requires_review"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必须包含时区")
    return value


class ProvenanceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID | None = None
    source_type: SourceType
    source_ref: str = Field(min_length=1)
    captured_at: datetime
    verification_status: VerificationStatus
    consent_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    method: str | None = None
    method_version: str | None = None
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    sample_size: int | None = Field(default=None, ge=0)
    privacy_threshold: int | None = Field(default=None, ge=1)

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "captured_at")

    @model_validator(mode="after")
    def validate_source_contract(self) -> "ProvenanceEntry":
        if self.source_type == SourceType.PUBLIC_FACT:
            parsed = urlsplit(self.source_ref)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("public_fact 必须引用绝对 HTTP(S) 来源")
        if self.source_type in {
            SourceType.AUTHORIZED_SUBMISSION,
            SourceType.AUTHORIZED_MESSAGE,
        } and not self.consent_id:
            raise ValueError("授权提交或私域消息必须提供 consent_id")
        if self.source_type == SourceType.AGGREGATE_EVALUATION:
            required = (
                self.method,
                self.method_version,
                self.observed_from,
                self.observed_to,
                self.sample_size,
                self.privacy_threshold,
            )
            if any(value is None for value in required):
                raise ValueError("聚合评价必须提供方法、版本、时间窗、样本量和隐私阈值")
            if self.sample_size < self.privacy_threshold:
                raise ValueError("聚合评价样本量未达到隐私阈值")
        return self


class PublicCitation(BaseModel):
    """面向客户端的最小证据引用，不包含授权标识或内部来源定位。"""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    citation_type: Literal[
        "public_url",
        "authorized_evidence",
        "aggregate_evidence",
        "reviewed_inference",
    ]
    citation: str
    source_url: str | None = None
    captured_at: datetime
    confidence: float = Field(ge=0, le=1)


def public_citation(
    entry: ProvenanceEntry,
    *,
    context: str,
) -> PublicCitation:
    """把内部 provenance 投影为不可回推私域引用的客户端 citation。"""
    if entry.evidence_id is None:
        raise ValueError(f"{context} 缺少入库时生成的随机 evidence_id")
    evidence_id = f"ev_{entry.evidence_id.hex}"
    if entry.source_type == SourceType.PUBLIC_FACT:
        return PublicCitation(
            evidence_id=evidence_id,
            citation_type="public_url",
            citation=entry.source_ref,
            source_url=entry.source_ref,
            captured_at=entry.captured_at,
            confidence=entry.confidence,
        )
    labels = {
        SourceType.AUTHORIZED_SUBMISSION: (
            "authorized_evidence",
            "已授权且经审核的提交材料",
        ),
        SourceType.AUTHORIZED_MESSAGE: (
            "authorized_evidence",
            "已授权且经审核的私域消息",
        ),
        SourceType.AGGREGATE_EVALUATION: (
            "aggregate_evidence",
            "达到隐私阈值且经审核的聚合证据",
        ),
        SourceType.INFERENCE: (
            "reviewed_inference",
            "带来源且经审核的推断",
        ),
    }
    citation_type, citation = labels.get(
        entry.source_type,
        ("reviewed_inference", "经审核的证据"),
    )
    return PublicCitation(
        evidence_id=evidence_id,
        citation_type=citation_type,
        citation=citation,
        captured_at=entry.captured_at,
        confidence=entry.confidence,
    )


class AuthorizationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basis: AuthorizationBasis
    consent_id: str | None = None
    scope: list[str] = Field(default_factory=list)
    authorized_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_authorization(self) -> "AuthorizationMetadata":
        if self.basis == AuthorizationBasis.EXPLICIT_CONSENT:
            if not self.consent_id or self.authorized_at is None:
                raise ValueError("explicit_consent 必须提供 consent_id 与 authorized_at")
        if self.authorized_at is not None:
            _require_aware(self.authorized_at, "authorized_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "authorization.expires_at")
        return self


class TakedownMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TakedownStatus = TakedownStatus.ACTIVE
    requested_at: datetime | None = None
    effective_at: datetime | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_takedown(self) -> "TakedownMetadata":
        if self.requested_at is not None:
            _require_aware(self.requested_at, "requested_at")
        if self.effective_at is not None:
            _require_aware(self.effective_at, "effective_at")
        if self.status == TakedownStatus.TAKEN_DOWN and self.effective_at is None:
            raise ValueError("taken_down 必须提供 effective_at")
        return self


class RecordGovernance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    publication_status: PublicationStatus
    created_at: datetime
    updated_at: datetime
    verified_at: datetime | None = None
    expires_at: datetime | None = None
    authorization: AuthorizationMetadata
    takedown: TakedownMetadata = Field(default_factory=TakedownMetadata)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "RecordGovernance":
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.verified_at is not None:
            _require_aware(self.verified_at, "verified_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at 不得早于 created_at")
        if self.publication_status == PublicationStatus.PUBLISHED:
            if self.review_status != ReviewStatus.VERIFIED:
                raise ValueError("published 记录必须已审核")
            if self.verified_at is None:
                raise ValueError("published 记录必须提供 verified_at")
            if self.authorization.basis in {
                AuthorizationBasis.LEGACY_SEED,
                AuthorizationBasis.NONE,
            }:
                raise ValueError("legacy/none 授权基础不得发布")
        return self

    def is_publishable(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (
            self.review_status == ReviewStatus.VERIFIED
            and self.publication_status == PublicationStatus.PUBLISHED
            and self.takedown.status == TakedownStatus.ACTIVE
            and (self.expires_at is None or self.expires_at > now)
            and (
                self.authorization.expires_at is None
                or self.authorization.expires_at > now
            )
        )


class QuarantinedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: QuarantineReason
    quarantined_at: datetime
    legacy_pointer: str = Field(min_length=1)
    value_retained: Literal[False] = False

    @field_validator("quarantined_at")
    @classmethod
    def quarantined_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "quarantined_at")


class GovernedMentorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    advisor_id: str = Field(min_length=1, max_length=20)
    fields: dict[str, Any]
    provenance: dict[str, list[ProvenanceEntry]]
    governance: RecordGovernance
    quarantined_fields: dict[str, QuarantinedField] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_field_evidence(self) -> "GovernedMentorRecord":
        missing = set(self.fields) - set(self.provenance)
        if missing:
            raise ValueError(f"字段缺少 provenance: {sorted(missing)}")
        overlap = set(self.fields) & set(self.quarantined_fields)
        if overlap:
            raise ValueError(f"字段不能同时公开候选与隔离: {sorted(overlap)}")
        if self.governance.publication_status == PublicationStatus.PUBLISHED:
            missing_evidence_ids = [
                f"{field_name}[{index}]"
                for field_name, entries in self.provenance.items()
                for index, entry in enumerate(entries)
                if entry.evidence_id is None
            ]
            if missing_evidence_ids:
                raise ValueError(
                    "published 来源必须持久化随机 evidence_id: "
                    f"{missing_evidence_ids}"
                )
        return self

    def _publishable_fields(
        self, now: datetime | None = None
    ) -> tuple[dict[str, Any], dict[str, list[ProvenanceEntry]]] | None:
        if not self.governance.is_publishable(now):
            return None
        publishable_fields: dict[str, Any] = {}
        verified_provenance: dict[str, list[ProvenanceEntry]] = {}
        for field_name, value in self.fields.items():
            entries = self.provenance.get(field_name, [])
            verified_entries = [
                entry
                for entry in entries
                if entry.verification_status == VerificationStatus.VERIFIED
                and entry.source_type != SourceType.UNKNOWN
            ]
            if not verified_entries:
                continue
            publishable_fields[field_name] = value
            verified_provenance[field_name] = verified_entries
        if "name" not in publishable_fields:
            return None
        return publishable_fields, verified_provenance

    def to_public_dict(self, now: datetime | None = None) -> dict[str, Any] | None:
        """返回面向客户端的字段与脱敏 citation。"""
        publishable = self._publishable_fields(now)
        if publishable is None:
            return None
        publishable_fields, verified_provenance = publishable
        public_provenance = {
            field_name: [
                public_citation(
                    entry,
                    context=f"mentor:{self.advisor_id}:{field_name}:{index}",
                ).model_dump(mode="json", exclude_none=True)
                for index, entry in enumerate(entries)
            ]
            for field_name, entries in verified_provenance.items()
        }
        return {
            "advisor_id": self.advisor_id,
            **publishable_fields,
            "provenance": public_provenance,
            "data_status": {
                "review_status": self.governance.review_status.value,
                "verified_at": self.governance.verified_at.isoformat()
                if self.governance.verified_at
                else None,
                "expires_at": self.governance.expires_at.isoformat()
                if self.governance.expires_at
                else None,
            },
        }

    def to_internal_match_dict(
        self, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """仅供服务端匹配使用；不得从列表、散点或匹配响应直接返回。"""
        publishable = self._publishable_fields(now)
        if publishable is None:
            return None
        publishable_fields, verified_provenance = publishable
        return {
            "advisor_id": self.advisor_id,
            **publishable_fields,
            "provenance": {
                field_name: [
                    entry.model_dump(mode="json", exclude_none=True)
                    for entry in entries
                ]
                for field_name, entries in verified_provenance.items()
            },
        }


class DatasetSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["legacy_seed"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_record_count: int = Field(ge=0)
    raw_retained: Literal[False] = False


class MentorDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    generated_at: datetime
    source: DatasetSource
    records: list[GovernedMentorRecord]

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "generated_at")
