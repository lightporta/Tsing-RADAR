"""questionnaire_sessions 问卷会话表（文档表 8）。"""

from sqlalchemy import JSON, Column, DateTime, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class QuestionnaireSession(Base):
    __tablename__ = "questionnaire_sessions"

    session_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(20), index=True)
    messages = Column(JSON)
    portrait = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
