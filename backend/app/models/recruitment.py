"""recruitments 招募表（文档表 5）。"""

from sqlalchemy import Boolean, Column, Date, DateTime, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid


class Recruitment(Base):
    __tablename__ = "recruitments"

    recruit_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    publisher_id = Column(String(20), index=True)
    publisher_type = Column(String(20))  # advisor / senior
    type = Column(String(20))  # 实习 / 科研助理 / 招生
    title = Column(String(200))
    req = Column(Text)
    major = Column(String(100))
    deadline = Column(Date)
    is_urgent = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
