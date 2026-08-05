"""评价反馈模型；主体由服务端会话提供。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisor_id: str = Field(min_length=1, max_length=100)
    rating: int
    comment: Optional[str] = Field(default=None, max_length=1000)
