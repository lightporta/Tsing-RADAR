"""A4 证据化匹配契约。

本模块只描述可验证的检索、排序与解释数据。导师事实仍由 A2 的
``GovernedMentorRecord`` 发布门控制；这里不会为缺失字段补默认事实。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.governance import (
    ProvenanceEntry,
    PublicCitation,
    SourceType,
    VerificationStatus,
)


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必须包含时区")
    return value


class RankingObjective(str, Enum):
    TOPIC_FIT = "topic_fit"
    RESEARCH_MODE_FIT = "research_mode_fit"
    MENTORSHIP_FIT = "mentorship_fit"
    CAREER_FIT = "career_fit"
    INNOVATION_FIT = "innovation_fit"
    OPPORTUNITY_FIT = "opportunity_fit"


class RankingWeights(BaseModel):
    """显式多目标权重；服务端只会在有证据的维度间重新归一化。"""

    model_config = ConfigDict(extra="forbid")

    topic_fit: float = Field(default=0.40, ge=0, le=1)
    research_mode_fit: float = Field(default=0.15, ge=0, le=1)
    mentorship_fit: float = Field(default=0.15, ge=0, le=1)
    career_fit: float = Field(default=0.10, ge=0, le=1)
    innovation_fit: float = Field(default=0.10, ge=0, le=1)
    opportunity_fit: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def require_non_zero_total(self) -> "RankingWeights":
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("多目标排序权重之和必须大于 0")
        return self


class RankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: RankingWeights = Field(default_factory=RankingWeights)
    recall_pool_size: int = Field(default=20, ge=1, le=100)
    result_limit: int = Field(default=5, ge=1, le=20)
    minimum_recall_score: float = Field(default=0.05, ge=0, le=1)


class MatchRequest(BaseModel):
    """匹配只使用服务端已确认画像。

    ``interest``、``portrait`` 与旧六维 ``weight`` 仅为旧客户端兼容字段；
    路由不会把它们用于匹配。可配置项只允许通过受校验的 ``ranking`` 传入。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    interest: str | None = Field(default=None, max_length=1000)
    portrait: dict[str, Any] | None = None
    weight: dict[str, float] | None = None


class OpportunitySignalType(str, Enum):
    PUBLICATION_OR_HIRING_GROWTH = "publication_or_hiring_growth"
    CROWDING = "crowding"
    FUNDING_OR_INFRASTRUCTURE = "funding_or_infrastructure"
    INDUSTRY_PULL = "industry_pull"
    MISSION_IMPORTANCE = "mission_importance"
    ENTRY_BARRIER = "entry_barrier"
    TRANSFERABILITY = "transferability"


class SourcedEvidenceClaim(BaseModel):
    """服务端内部结论及其完整来源；不得直接进入客户端响应。"""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=1000)
    sources: list[ProvenanceEntry] = Field(min_length=1)

    @field_validator("sources")
    @classmethod
    def require_verified_sources(
        cls, sources: list[ProvenanceEntry]
    ) -> list[ProvenanceEntry]:
        for source in sources:
            if (
                source.verification_status != VerificationStatus.VERIFIED
                or source.source_type == SourceType.UNKNOWN
            ):
                raise ValueError("证据结论只能引用 verified 且非 unknown 的来源")
        return sources


class EvidenceClaim(BaseModel):
    """面向客户端的结论，只包含脱敏 citation。"""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=1000)
    citations: list[PublicCitation] = Field(min_length=1)


class OpportunitySignal(BaseModel):
    """有方向、有观测窗、有失效时间的机会信号。

    ``effect`` 只表达该信号对“当前机会性”的有利/不利方向，不等同于热门度：
    -1 表示强反向，0 表示中性，1 表示强正向。
    """

    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=100)
    signal_type: OpportunitySignalType
    label: str = Field(min_length=1, max_length=200)
    effect: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    observed_from: datetime
    observed_to: datetime
    valid_until: datetime
    method: str = Field(min_length=1, max_length=200)
    method_version: str = Field(min_length=1, max_length=100)
    supporting_evidence: list[SourcedEvidenceClaim] = Field(min_length=1)
    counter_evidence: list[SourcedEvidenceClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_time_window(self) -> "OpportunitySignal":
        _require_aware(self.observed_from, "observed_from")
        _require_aware(self.observed_to, "observed_to")
        _require_aware(self.valid_until, "valid_until")
        if self.observed_to < self.observed_from:
            raise ValueError("observed_to 不得早于 observed_from")
        if self.valid_until < self.observed_to:
            raise ValueError("valid_until 不得早于 observed_to")
        return self


class ObjectiveBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: RankingObjective
    score: float | None = Field(default=None, ge=0, le=1)
    requested_weight: float = Field(ge=0, le=1)
    effective_weight: float = Field(ge=0, le=1)
    method: str
    evidence_fields: list[str] = Field(default_factory=list)
    evidence_coverage: float = Field(ge=0, le=1)
    evidence_confidence: float = Field(ge=0, le=1)
    conservative_contribution: float = Field(ge=0, le=1)


class MatchExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supporting_evidence: list[EvidenceClaim] = Field(default_factory=list)
    counter_evidence: list[EvidenceClaim] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    questions_to_verify: list[str] = Field(default_factory=list)


class PublicOpportunitySignal(BaseModel):
    """客户端机会信号视图；来源已经脱敏。"""

    model_config = ConfigDict(extra="forbid")

    signal_id: str
    signal_type: OpportunitySignalType
    label: str
    effect: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    observed_from: datetime
    observed_to: datetime
    valid_until: datetime
    method: str
    method_version: str
    supporting_evidence: list[EvidenceClaim]
    counter_evidence: list[EvidenceClaim]


class MatchedMentor(BaseModel):
    model_config = ConfigDict(extra="allow")

    advisor_id: str
    name: str
    score: float = Field(ge=0, le=100)
    fit_score: float = Field(ge=0, le=100)
    evidence_coverage: float = Field(ge=0, le=1)
    evidence_confidence: float = Field(ge=0, le=1)
    recall_score: float = Field(ge=0, le=1)
    score_breakdown: list[ObjectiveBreakdown]
    explanation: MatchExplanation
    opportunity_signals: list[PublicOpportunitySignal] = Field(
        default_factory=list
    )


class MatchPipelineMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "needs_clarification"]
    method_version: str
    retrieval_method: str
    retrieval_mode: str
    input_candidates: int = Field(ge=0)
    after_hard_constraints: int = Field(ge=0)
    recalled_candidates: int = Field(ge=0)
    ranked: int = Field(ge=0)
    applied_hard_constraints: list[str] = Field(default_factory=list)
    unresolved_hard_constraints: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    excluded_by_hard_constraints: int = Field(ge=0)
    constraint_trace: list[dict[str, Any]] = Field(default_factory=list)
    zero_result_reason: str | None = None
    ranking_config: RankingConfig
