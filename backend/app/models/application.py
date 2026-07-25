"""applications 投递表（文档表 6）。"""

from sqlalchemy import Column, DateTime, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class Application(Base):
    __tablename__ = "applications"

    app_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    recruit_id = Column(String(36), index=True)
    student_id = Column(String(20), index=True)
    resume_id = Column(String(36))
    status = Column(String(20), default="待处理")  # 待处理/已读/通过/拒绝
    created_at = Column(DateTime, server_default=func.now())
