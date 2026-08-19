"""Governed evidence for the objective mentor radar.

This dataset is deliberately separate from the mentor directory.  Directory
facts can never be promoted into objective breadth or completeness claims by
inference.  The four dimensions are computed only from independently audited
public evidence; anonymous subjective ratings live in a strictly separate
pipeline (advisor ratings) and never enter this file.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须包含时区")
    return value


class ScoreDimension(str, Enum):
    """客观雷达四维：全部来自公开证据的计数/完整度，非主观评价。"""

    PROJECT_BREADTH = "project_breadth"
    TOPIC_BREADTH = "topic_breadth"
    CONTACT_COMPLETENESS = "contact_completeness"
    MATERIAL_COMPLETENESS = "material_completeness"


REQUIRED_SCORE_DIMENSIONS = frozenset(ScoreDimension)
NUMERIC_SCORE_DIMENSIONS = frozenset(ScoreDimension)


class ClaimReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ScoreReleaseStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ScoreEvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: UUID = Field(default_factory=uuid4)
    advisor_id: str = Field(min_length=1, max_length=100)
    dimension: ScoreDimension
    value: Any
    source_kind: Literal["official_public", "authorized_aggregate"]
    source_url: str = Field(min_length=1, max_length=2000)
    extracted_at: datetime
    valid_until: datetime
    method: str = Field(min_length=1, max_length=300)
    method_version: str = Field(min_length=1, max_length=100)
    sample_size: int | None = Field(default=None, ge=0)
    privacy_threshold: int | None = Field(default=None, ge=2)
    review_status: ClaimReviewStatus = ClaimReviewStatus.PENDING
    reviewer_id: str | None = Field(default=None, min_length=1, max_length=100)
    reviewed_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_claim(self) -> "ScoreEvidenceClaim":
        _aware(self.extracted_at, "extracted_at")
        _aware(self.valid_until, "valid_until")
        if self.valid_until <= self.extracted_at:
            raise ValueError("valid_until 必须晚于 extracted_at")
        parsed = urlsplit(self.source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("source_url 必须是绝对 HTTP(S) URL")
        # 客观四维全部为 0—100 数值（证据计数/完整度归一化，非主观打分）
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("客观维度必须提供 0—100 数值")
        if not 0 <= float(self.value) <= 100:
            raise ValueError("客观维度评分必须在 0—100 之间")
        if self.source_kind == "authorized_aggregate":
            if (
                self.sample_size is None
                or self.privacy_threshold is None
                or self.sample_size < self.privacy_threshold
            ):
                raise ValueError("授权聚合证据必须达到声明的隐私样本阈值")
        elif self.sample_size is not None or self.privacy_threshold is not None:
            raise ValueError("公开事实不得伪装成学生评价聚合")
        if self.review_status in {
            ClaimReviewStatus.APPROVED,
            ClaimReviewStatus.REJECTED,
        }:
            if not self.reviewer_id or self.reviewed_at is None:
                raise ValueError("审核结论必须包含审核人和审核时间")
        if self.reviewed_at is not None:
            _aware(self.reviewed_at, "reviewed_at")
        return self

    def is_current_approved(self, now: datetime) -> bool:
        return self.review_status == ClaimReviewStatus.APPROVED and self.valid_until > now


class MentorScoreRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: UUID = Field(default_factory=uuid4)
    version: int = Field(ge=1)
    status: ScoreReleaseStatus = ScoreReleaseStatus.DRAFT
    created_at: datetime
    published_at: datetime | None = None
    supersedes_release_id: UUID | None = None
    claims: list[ScoreEvidenceClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_release(self) -> "MentorScoreRelease":
        _aware(self.created_at, "created_at")
        if self.published_at is not None:
            _aware(self.published_at, "published_at")
        keys = [(claim.advisor_id, claim.dimension) for claim in self.claims]
        if len(keys) != len(set(keys)):
            raise ValueError("同一发布版本中 advisor/dimension 不得重复")
        if self.status == ScoreReleaseStatus.PUBLISHED:
            if self.published_at is None:
                raise ValueError("published 版本必须包含 published_at")
            if any(
                claim.review_status != ClaimReviewStatus.APPROVED
                for claim in self.claims
            ):
                raise ValueError("published 版本的每条维度 claim 都必须 approved")
        return self


class MentorScoreDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    releases: list[MentorScoreRelease] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def generated_at_aware(cls, value: datetime) -> datetime:
        return _aware(value, "generated_at")

    @model_validator(mode="after")
    def unique_versions(self) -> "MentorScoreDataset":
        versions = [release.version for release in self.releases]
        if len(versions) != len(set(versions)):
            raise ValueError("评分发布 version 不得重复")
        return self
