"""招募评论相关 Pydantic 模型。

作者身份只来自服务端会话，客户端不得自报；徽章由服务端按
author_label / is_op 计算。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=500)
    parent_id: str | None = Field(default=None, max_length=36)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("评论内容不能为空")
        return cleaned


class CommentReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("举报原因不能为空")
        return cleaned
