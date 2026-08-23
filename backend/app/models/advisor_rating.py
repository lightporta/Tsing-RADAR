"""学生评价体系 M1：advisor_ratings 评分表 + advisor_rating_summary 物化聚合表。"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.db.base import Base
from app.models.match_record import _uuid


class AdvisorRating(Base):
    """单条六维匿名评分；一人一导师仅一条，rater_principal 永不出服务端。"""

    __tablename__ = "advisor_ratings"

    rating_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    advisor_id = Column(String(20), nullable=False, index=True)
    rater_principal = Column(String(64), nullable=False, index=True)
    rater_verified = Column(Boolean, nullable=False, default=False)
    period_in_group = Column(String(20), nullable=True)
    scores = Column(JSON, nullable=False)
    evidence = Column(Text, nullable=True)
    review_status = Column(String(20), nullable=False, default="pending_review")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "advisor_id",
            "rater_principal",
            name="uq_one_rating_per_rater",
        ),
    )


class AdvisorRatingSummary(Base):
    """按导师物化的贝叶斯聚合结果；审核通过时重算，读取零计算。"""

    __tablename__ = "advisor_rating_summary"

    advisor_id = Column(String(20), primary_key=True)
    acumen_value = Column(Float, nullable=True)
    acumen_n = Column(Integer, nullable=False, default=0)
    network_value = Column(Float, nullable=True)
    network_n = Column(Integer, nullable=False, default=0)
    mentorship_value = Column(Float, nullable=True)
    mentorship_n = Column(Integer, nullable=False, default=0)
    tolerance_value = Column(Float, nullable=True)
    tolerance_n = Column(Integer, nullable=False, default=0)
    funding_value = Column(Float, nullable=True)
    funding_n = Column(Integer, nullable=False, default=0)
    efficiency_value = Column(Float, nullable=True)
    efficiency_n = Column(Integer, nullable=False, default=0)
    last_collected_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
