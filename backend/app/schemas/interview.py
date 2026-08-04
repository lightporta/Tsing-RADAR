"""A3 动态访谈、结构化学生画像与确认门 Schema。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class InterviewStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"


class InterviewDimension(str, Enum):
    RESEARCH_INTERESTS = "research_interests"
    RESEARCH_MODE = "research_mode"
    MENTORSHIP_STYLE = "mentorship_style"
    CAREER_ORIENTATION = "career_orientation"
    INNOVATION_RISK = "innovation_risk"
    HARD_CONSTRAINTS = "hard_constraints"


class HardConstraintField(str, Enum):
    LOCATION = "location"
    WEEKLY_COMMITMENT_DAYS = "weekly_commitment_days"
    DEGREE_STAGE = "degree_stage"
    LANGUAGE = "language"
    CONFIDENTIALITY = "confidentiality"
    GRADUATION_ARRANGEMENT = "graduation_arrangement"
    DEPARTMENT = "department"
    RESEARCH_TOPIC = "research_topic"
    ADVISOR_ID = "advisor_id"


class HardConstraintOperator(str, Enum):
    EQUALS = "equals"
    ONE_OF = "one_of"
    EXCLUDES = "excludes"
    CONTAINS = "contains"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class HardConstraint(BaseModel):
    """由用户在画像编辑/确认阶段确认的结构化硬约束。"""

    model_config = ConfigDict(extra="forbid")

    field: HardConstraintField
    operator: HardConstraintOperator
    value: list[str] = Field(min_length=1, max_length=12)
    source_text: str | None = Field(default=None, max_length=500)

    @field_validator("value")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in normalized:
                normalized.append(item)
        if not normalized:
            raise ValueError("硬约束 value 不得为空")
        return normalized

    @model_validator(mode="after")
    def validate_field_operator(self) -> "HardConstraint":
        if self.operator in {
            HardConstraintOperator.MINIMUM,
            HardConstraintOperator.MAXIMUM,
        }:
            if self.field != HardConstraintField.WEEKLY_COMMITMENT_DAYS:
                raise ValueError("minimum/maximum 仅适用于 weekly_commitment_days")
            if len(self.value) != 1:
                raise ValueError("数值硬约束只能提供一个值")
            try:
                number = float(self.value[0])
            except ValueError as exc:
                raise ValueError("每周投入天数必须是数值") from exc
            if not 0 <= number <= 7:
                raise ValueError("每周投入天数必须在 0 到 7 之间")
        return self


class DraftHardConstraint(BaseModel):
    """自然语言解析草案；用户确认前不得进入硬过滤。"""

    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(default_factory=lambda: str(uuid4()))
    source_text: str = Field(min_length=1, max_length=500)
    proposed_constraint: HardConstraint | None = None
    parsing_confidence: float = Field(ge=0, le=1)
    confirmation_prompt: str = Field(min_length=1, max_length=1000)


class StudentPortrait(BaseModel):
    """由学生回答或显式编辑得到的画像；不包含导师排序分数。"""

    model_config = ConfigDict(extra="forbid")

    research_interests: list[str] = Field(default_factory=list, max_length=8)
    interest_statement: str | None = Field(default=None, max_length=1000)
    research_mode: Literal["theory", "engineering", "mixed", "undecided"] | None = None
    mentorship_style: Literal[
        "high_guidance", "balanced", "autonomous", "undecided"
    ] | None = None
    career_orientation: Literal[
        "academic", "industry", "national_mission", "mixed", "undecided"
    ] | None = None
    innovation_risk: Literal["pioneering", "balanced", "mature", "undecided"] | None = None
    hard_constraints: list[HardConstraint] | None = Field(
        default=None, max_length=12
    )
    draft_hard_constraints: list[DraftHardConstraint] = Field(
        default_factory=list, max_length=12
    )
    unresolved_hard_constraints: list[str] | None = Field(
        default=None, max_length=12
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_constraints(cls, value: Any) -> Any:
        """旧会话的自然语言约束只迁入 unresolved，不做语义猜测。"""
        if not isinstance(value, dict):
            return value
        raw_constraints = value.get("hard_constraints")
        if isinstance(raw_constraints, list) and any(
            isinstance(item, str) for item in raw_constraints
        ):
            migrated = dict(value)
            legacy = [
                item.strip()
                for item in raw_constraints
                if isinstance(item, str) and item.strip()
            ]
            existing = migrated.get("unresolved_hard_constraints") or []
            migrated["hard_constraints"] = []
            migrated["unresolved_hard_constraints"] = list(
                dict.fromkeys([*existing, *legacy])
            )
            return migrated
        return value

    @field_validator("research_interests")
    @classmethod
    def normalize_interests(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("unresolved_hard_constraints")
    @classmethod
    def normalize_constraints(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in normalized:
                normalized.append(item)
        return normalized


class StudentPortraitPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    research_interests: list[str] | None = Field(default=None, max_length=8)
    interest_statement: str | None = Field(default=None, max_length=1000)
    research_mode: Literal["theory", "engineering", "mixed", "undecided"] | None = None
    mentorship_style: Literal[
        "high_guidance", "balanced", "autonomous", "undecided"
    ] | None = None
    career_orientation: Literal[
        "academic", "industry", "national_mission", "mixed", "undecided"
    ] | None = None
    innovation_risk: Literal["pioneering", "balanced", "mature", "undecided"] | None = None
    hard_constraints: list[HardConstraint] | None = Field(
        default=None, max_length=12
    )
    draft_hard_constraints: list[DraftHardConstraint] | None = Field(
        default=None, max_length=12
    )
    unresolved_hard_constraints: list[str] | None = Field(
        default=None, max_length=12
    )


class InterviewQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    dimension: InterviewDimension
    prompt: str
    answer_type: Literal["text", "single_choice"]
    options: list[InterviewQuestionOption] = Field(default_factory=list)
    information_goal: str


class InterviewMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    created_at: str


class InterviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_answer: str | None = Field(default=None, min_length=1, max_length=4000)


class InterviewAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=4000)


class InterviewConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class InterviewStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: InterviewStatus
    profile: StudentPortrait
    profile_version: int
    current_question: InterviewQuestion | None
    completed_dimensions: list[InterviewDimension]
    missing_dimensions: list[InterviewDimension]
    needs_confirmation: bool
    needs_clarification: bool
    clarification_questions: list[str]
    recommend_ready: bool
    assistant_message: str
    messages: list[InterviewMessage]
