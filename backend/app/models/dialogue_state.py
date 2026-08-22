"""dialogue_sessions 对话模式状态表（v2.5 纯对话扩展）。

访谈状态机（questionnaire_sessions）之外的多轮对话模式（简历分步采集、
简历润色待粘贴、定向优化等）使用本表持久化中间状态；与访谈共用会话键
推导（sessionId/主体派生），保证同一通对话内跨轮续接、进程重启不丢。
"""

from sqlalchemy import JSON, Column, DateTime, Integer, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class DialogueSession(Base):
    __tablename__ = "dialogue_sessions"

    session_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(64), nullable=False, index=True)
    mode = Column(String(30), nullable=False, index=True)
    state = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
