"""match_records 匹配历史表（文档表 3）。"""

import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class MatchRecord(Base):
    __tablename__ = "match_records"

    # SQLite 兼容：用 String 而非原生 UUID（生产期 PostgreSQL 自动迁移）
    record_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(20), ForeignKey("students.student_id"), index=True)
    advisor_id = Column(String(20), ForeignKey("advisors.advisor_id"), index=True)
    synergy_score = Column(Float)
    match_reason = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
