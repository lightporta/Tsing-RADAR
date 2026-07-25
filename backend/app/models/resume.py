"""resumes 简历表（文档表 4）。"""

from sqlalchemy import JSON, Column, DateTime, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid


class Resume(Base):
    __tablename__ = "resumes"

    resume_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(20), index=True)
    title = Column(String(100))
    content = Column(JSON)
    polished_text = Column(Text)
    target_advisor_id = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())
