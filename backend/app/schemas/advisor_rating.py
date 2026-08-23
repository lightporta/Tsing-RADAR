"""学生评价体系 M1 的 Pydantic 模型（六维纯分数，不含文字依据）。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.constants import TRAIT_KEYS

# 在组时长：半年内 / 半年到两年 / 两年以上 / 组外（旁听、合作等）
PeriodLiteral = Literal["0.5y", "0.5-2y", "2y+", "outside"]


class RatingSubmitRequest(BaseModel):
    """评分提交：六维键恰好齐全、每项 1-5 整数；M1 不开放文字依据。"""

    model_config = ConfigDict(extra="forbid")

    scores: dict[str, int] = Field(..., description="六维评分 1-5")
    period_in_group: PeriodLiteral | None = None

    @field_validator("scores")
    @classmethod
    def validate_scores(cls, v: dict[str, int]) -> dict[str, int]:
        required = set(TRAIT_KEYS)
        if set(v) != required:
            raise ValueError("scores 必须恰好包含六维键")
        if any(not 1 <= val <= 5 for val in v.values()):
            raise ValueError("每项评分必须在 1-5 之间")
        return v


class RatingSummaryOut(BaseModel):
    """聚合摘要：value 为 None 表示该维暂无样本（诚实空态）。"""

    advisor_id: str
    dimensions: dict[str, dict[str, float | int | str | None]]
    total_n: int
    last_collected_at: str | None
