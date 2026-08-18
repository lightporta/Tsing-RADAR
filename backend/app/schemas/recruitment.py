"""招募相关 Pydantic 模型。"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 立体化扩展字段（全部可选，向后兼容；B-06 风格 max_length 全覆盖）
_OPTIONAL_TEXT_LIMITS = {
    "location": 60,
    "quota": 20,
    "compensation": 60,
    "duration": 40,
    "apply_method": 200,
    "advisor_id": 20,
}
_TAG_MAX_LENGTH = 20
_TAGS_MAX_COUNT = 10


class RecruitmentCreateRequest(BaseModel):
    """发布者身份只来自服务端会话，客户端不得自报。"""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=2, max_length=200)
    req: str = Field(min_length=2, max_length=4000)
    major: str = Field(min_length=1, max_length=100)
    deadline: date
    is_urgent: bool = False
    # —— 立体化扩展（全部可空）——
    location: Optional[str] = Field(default=None, max_length=60)
    quota: Optional[str] = Field(default=None, max_length=20)
    compensation: Optional[str] = Field(default=None, max_length=60)
    duration: Optional[str] = Field(default=None, max_length=40)
    apply_method: Optional[str] = Field(default=None, max_length=200)
    tags: Optional[list[str]] = Field(default=None, max_length=_TAGS_MAX_COUNT)
    advisor_id: Optional[str] = Field(default=None, max_length=20)

    @field_validator("type", "title", "req", "major")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned

    @field_validator(*_OPTIONAL_TEXT_LIMITS)
    @classmethod
    def trim_optional_text(cls, value: Optional[str]) -> Optional[str]:
        """可空文本统一去空白；空串归一为 None（不存空串）。"""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        """单标签 ≤20 字、去空白去重保序；空列表归一为 None。"""
        if value is None:
            return None
        cleaned: list[str] = []
        for tag in value:
            item = tag.strip()
            if not item:
                continue
            if len(item) > _TAG_MAX_LENGTH:
                raise ValueError(f"单个标签不能超过 {_TAG_MAX_LENGTH} 字")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned or None


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
    # 立体化扩展（缺省时序列化不含对应键，向后兼容旧客户端）
    location: Optional[str] = None
    quota: Optional[str] = None
    compensation: Optional[str] = None
    duration: Optional[str] = None
    apply_method: Optional[str] = None
    tags: Optional[list[str]] = None
    advisor_id: Optional[str] = None
