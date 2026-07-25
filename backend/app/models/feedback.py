"""feedback 反馈表（文档表 7）。"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid


class Feedback(Base):
    __tablename__ = "feedback"

    feedback_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(20), index=True)
    advisor_id = Column(String(20), index=True)
    rating = Column(Integer)  # 1=赞，-1=踩
    comment = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
