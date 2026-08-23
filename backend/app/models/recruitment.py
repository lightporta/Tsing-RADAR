"""recruitments 招募表（含 A2 授权、审核、过期与下架元数据）。"""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid


class Recruitment(Base):
    __tablename__ = "recruitments"

    recruit_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    publisher_id = Column(String(64), nullable=False, index=True)
    publisher_type = Column(String(20))  # advisor / senior
    type = Column(String(20))  # 实习 / 科研助理 / 招生
    title = Column(String(200))
    req = Column(Text)
    major = Column(String(100))
    deadline = Column(Date)
    is_urgent = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    takedown_at = Column(DateTime(timezone=True), nullable=True)
    review_status = Column(String(20), nullable=False, default="pending_review")
    publication_status = Column(String(20), nullable=False, default="restricted")
    authorization_basis = Column(String(40), nullable=False, default="none")
    consent_id = Column(String(100), nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    governance = Column(JSON, nullable=False, default=dict)
    quarantined_fields = Column(JSON, nullable=False, default=dict)
    # —— 立体化扩展（全部可空，向后兼容；迁移 0010）——
    location = Column(String(60), nullable=True)  # 工作地点
    quota = Column(String(20), nullable=True)  # 名额
    compensation = Column(String(60), nullable=True)  # 待遇说明
    duration = Column(String(40), nullable=True)  # 周期
    apply_method = Column(String(200), nullable=True)  # 投递方式（禁联系方式直发）
    tags = Column(JSON, nullable=True)  # 标签列表，最多 10 个
    advisor_id = Column(String(20), nullable=True, index=True)  # 关联导师
