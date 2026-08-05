"""评价反馈 Pydantic 模型。"""

from typing import Optional

from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    student_id: str
    advisor_id: str
    rating: int  # 1 正向 / -1 负向
    comment: Optional[str] = None
