"""advisors 导师画像表（含 A2 数据治理元数据）。"""

from sqlalchemy import JSON, Column, DateTime, Float, String, Text, func

from app.db.base import Base


class Advisor(Base):
    __tablename__ = "advisors"

    advisor_id = Column(String(20), primary_key=True)  # 教职工工号
    name = Column(String(50), index=True)
    department = Column(String(50))
    field = Column(String(200))
    tags = Column(JSON)  # 研究方向标签
    profile_text = Column(Text)
    recent_papers = Column(JSON)
    contact_email = Column(String(50))
    office_loc = Column(String(50))
    radar_traits = Column(JSON, nullable=True)  # 仅存储已验证的聚合评价
    popularity = Column(Float, nullable=True)
    sector = Column(Float, nullable=True)

    provenance = Column(JSON, nullable=False, default=dict)
    governance = Column(JSON, nullable=False, default=dict)
    quarantined_fields = Column(JSON, nullable=False, default=dict)
    review_status = Column(String(20), nullable=False, default="pending_review")
    publication_status = Column(String(20), nullable=False, default="restricted")
    authorization_basis = Column(String(40), nullable=False, default="none")
    consent_id = Column(String(100), nullable=True)
    record_created_at = Column(DateTime(timezone=True), server_default=func.now())
    record_updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    verified_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    takedown_at = Column(DateTime(timezone=True), nullable=True)
