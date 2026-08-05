"""招聘/招生机会（opportunities）。

动态事实表，必须有 valid_until（截止时间）和 opportunity_status（open/closed/...）。
过期或状态未明的机会不会出现在公开接口。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Opportunity(Base):
    """机会实体表（phd / master / postdoc / ra / internship / visiting_student / summer_research）。"""

    __tablename__ = "opportunities"

    opportunity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )
    opportunity_type: Mapped[Optional[str]] = mapped_column(String(30))
    title: Mapped[Optional[str]] = mapped_column(Text)
    target_stage: Mapped[Optional[str]] = mapped_column(String(50))
    direction_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("directions.direction_id")
    )
    location: Mapped[Optional[str]] = mapped_column(String(200))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opportunity_status: Mapped[str] = mapped_column(String(30), default="unknown")
    application_channel: Mapped[Optional[str]] = mapped_column(Text)
    claim_id: Mapped[Optional[str]] = mapped_column(String(36))
    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    publication_status: Mapped[str] = mapped_column(String(20), default="withheld")

    __table_args__ = (
        Index("ix_opportunities_entity", "entity_id"),
        Index("ix_opportunities_status", "opportunity_status", "publication_status"),
        Index("ix_opportunities_valid", "valid_until"),
    )
