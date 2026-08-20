"""兴趣探索（活动兴趣题 → 候选研究方向）Schema。

设计约束（修改说明 §6）：
- 题型参考 O*NET Interest Profiler 的活动兴趣思路，改写为研究场景；
- 候选方向由确定性映射生成，GLM 只作表达增强、不改变结果；
- 用户单选或多选候选方向后写回画像，继续推荐导师。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActivityOption(BaseModel):
    """研究场景活动选项（容易回答的多选题）。"""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    description: str


class ActivityQuestionResponse(BaseModel):
    """活动兴趣选择题定义（前端渲染用）。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal["activity-interests-v1"] = "activity-interests-v1"
    prompt: str
    options: list[ActivityOption]
    min_selections: int
    max_selections: int


class InterestExplorationSuggestionRequest(BaseModel):
    """用户选择的活动键集合（1—8 个）。"""

    model_config = ConfigDict(extra="forbid")

    activities: list[str] = Field(min_length=1, max_length=8)

    @field_validator("activities")
    @classmethod
    def normalize_activities(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in normalized:
                normalized.append(item)
        if not normalized:
            raise ValueError("至少选择一个活动")
        return normalized


class DirectionCandidate(BaseModel):
    """候选研究方向（含详细介绍与命中活动）。"""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    description: str
    matched_activities: list[ActivityOption]
    match_score: int = Field(ge=1)


class InterestExplorationSuggestionResponse(BaseModel):
    """确定性映射生成的候选研究方向列表。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal["activity-interests-v1"] = "activity-interests-v1"
    basis: Literal["deterministic_activity_mapping"] = (
        "deterministic_activity_mapping"
    )
    candidates: list[DirectionCandidate] = Field(max_length=5)
    hint: str


class InterestExplorationApplyRequest(BaseModel):
    """用户选定的候选方向（单选或多选）写回画像。"""

    model_config = ConfigDict(extra="forbid")

    direction_keys: list[str] = Field(min_length=1, max_length=8)
    activities: list[str] = Field(default_factory=list, max_length=8)
    expected_version: int = Field(ge=1)

    @field_validator("direction_keys")
    @classmethod
    def normalize_directions(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in normalized:
                normalized.append(item)
        if not normalized:
            raise ValueError("至少选择一个候选方向")
        return normalized

    @field_validator("activities")
    @classmethod
    def normalize_activities(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in normalized:
                normalized.append(item)
        return normalized
