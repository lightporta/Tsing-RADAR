"""Governed evidence for optional mentor score visualisations.

This dataset is deliberately separate from the mentor directory.  Directory
facts can never be promoted into personality, funding, popularity, sector or
compatibility claims by inference.
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
    TRAIT_ACUMEN = "trait_acumen"
    TRAIT_NETWORK = "trait_network"
    TRAIT_MENTORSHIP = "trait_mentorship"
    TRAIT_TOLERANCE = "trait_tolerance"
    TRAIT_FUNDING = "trait_funding"
    TRAIT_EFFICIENCY = "trait_efficiency"
    POPULARITY_INDEX = "popularity_index"
    SECTOR_ATTRIBUTE = "sector_attribute"
    COMPATIBILITY_RESEARCH_MODE = "compatibility_research_mode"
    COMPATIBILITY_MENTORSHIP_STYLE = "compatibility_mentorship_style"
    COMPATIBILITY_CAREER_ORIENTATION = "compatibility_career_orientation"
    COMPATIBILITY_INNOVATION_RISK = "compatibility_innovation_risk"


REQUIRED_SCORE_DIMENSIONS = frozenset(ScoreDimension)
NUMERIC_SCORE_DIMENSIONS = frozenset(
    {
        ScoreDimension.TRAIT_ACUMEN,
        ScoreDimension.TRAIT_NETWORK,
        ScoreDimension.TRAIT_MENTORSHIP,
        ScoreDimension.TRAIT_TOLERANCE,
        ScoreDimension.TRAIT_FUNDING,
        ScoreDimension.TRAIT_EFFICIENCY,
        ScoreDimension.POPULARITY_INDEX,
    }
)
COMPATIBILITY_VALUES = {
    ScoreDimension.COMPATIBILITY_RESEARCH_MODE: {
        "theory",
        "engineering",
        "mixed",
    },
    ScoreDimension.COMPATIBILITY_MENTORSHIP_STYLE: {
        "high_guidance",
        "balanced",
        "autonomous",
    },
    ScoreDimension.COMPATIBILITY_CAREER_ORIENTATION: {
        "academic",
        "industry",
        "national_mission",
        "mixed",
    },
    ScoreDimension.COMPATIBILITY_INNOVATION_RISK: {
        "pioneering",
        "balanced",
        "mature",
    },
}


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
        if self.dimension in NUMERIC_SCORE_DIMENSIONS:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError("评分维度必须提供 0—100 数值")
            if not 0 <= float(self.value) <= 100:
                raise ValueError("评分必须在 0—100 之间")
        elif self.dimension == ScoreDimension.SECTOR_ATTRIBUTE:
            if self.value not in {"state", "private"}:
                raise ValueError("sector_attribute 只能是 state/private")
        else:
            allowed = COMPATIBILITY_VALUES[self.dimension]
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("契合维度必须提供非空的已核验类别列表")
            normalized = {str(item) for item in self.value}
            if not normalized <= allowed:
                raise ValueError("契合维度包含未定义类别")
            self.value = sorted(normalized)
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
