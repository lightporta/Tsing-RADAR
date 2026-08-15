"""招募相关 Pydantic 模型。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecruitmentCreateRequest(BaseModel):
    """发布者身份只来自服务端会话，客户端不得自报。"""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=2, max_length=200)
    req: str = Field(min_length=2, max_length=4000)
    major: str = Field(min_length=1, max_length=100)
    deadline: date
    is_urgent: bool = False

    @field_validator("type", "title", "req", "major")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned


class RecruitmentUpdateRequest(RecruitmentCreateRequest):
    """编辑后立即重新进入审核队列；不接受客户端自报审核状态。"""

    submit_for_review: Literal[True]


class RecruitmentItem(BaseModel):
    recruit_id: str
    publisher_name: str
    publisher_type: str
    type: str
    title: str
    req: str
    major: str
    deadline: date
    is_urgent: bool
    dept: str
    review_status: str
    publication_status: str
