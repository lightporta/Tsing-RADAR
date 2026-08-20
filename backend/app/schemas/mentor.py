"""导师服务相关 Pydantic 模型。

身份与权限一律来自服务端会话，客户端不得自报。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmailCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=100)


class MentorLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=100)
    code: str = Field(min_length=6, max_length=6)


class ClaimSubmitRequest(BaseModel):
    """认领时复述候选的 name/department，服务端重新匹配验证，防任意认领。"""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=50)
    department: str = Field(min_length=0, max_length=50)

    @field_validator("candidate_id", "name")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned


class FieldEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1, max_length=50)
    new_value: str = Field(min_length=1, max_length=4000)

    @field_validator("field_name", "new_value")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned


class VisibilityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: dict[str, bool]


class TakedownSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=2000, default="")
    scope: Literal["full", "field"]
    field_name: str | None = Field(default=None, max_length=50)


class MentorReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewer")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("审批人不能为空")
        return cleaned
