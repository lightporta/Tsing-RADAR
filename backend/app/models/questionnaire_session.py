"""questionnaire_sessions 持久化访谈与结构化画像表。"""

from sqlalchemy import JSON, Column, DateTime, Integer, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class QuestionnaireSession(Base):
    __tablename__ = "questionnaire_sessions"

    session_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(64), nullable=False, index=True)
    messages = Column(JSON, nullable=False, default=list)
    portrait = Column(JSON, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="in_progress")
    current_question_id = Column(String(50), nullable=True)
    answered_dimensions = Column(JSON, nullable=False, default=list)
    profile_version = Column(Integer, nullable=False, default=1)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
