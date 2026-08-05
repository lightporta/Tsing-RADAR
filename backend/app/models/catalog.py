"""招生目录关系（catalog_links）。

只表述「出现在某年度官方目录」这一事实，不推断「当前一定招生」「有名额」。
身份消歧通过 identity_resolution_status 标记。
"""

from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CatalogLink(Base):
    """招生目录事实关联表。"""

    __tablename__ = "catalog_links"

    catalog_link_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    catalog_snapshot_id: Mapped[Optional[str]] = mapped_column(String(100))
    academic_year: Mapped[Optional[str]] = mapped_column(String(4))
    catalog_type: Mapped[Optional[str]] = mapped_column(String(50))  # doctoral_regular/...
    department_id: Mapped[Optional[str]] = mapped_column(String(36))  # entities.entity_id (organization)
    program_id: Mapped[Optional[str]] = mapped_column(String(36))
    direction_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("directions.direction_id")
    )
    advisor_or_group_id: Mapped[Optional[str]] = mapped_column(String(36))  # 目录标签实体
    resolved_entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.entity_id")
    )
    identity_resolution_status: Mapped[str] = mapped_column(
        String(20), default="unresolved"
    )  # verified/conflicted/unresolved
    relation_claim_id: Mapped[Optional[str]] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_catalog_links_year", "academic_year"),
        Index("ix_catalog_links_resolved", "resolved_entity_id"),
        Index("ix_catalog_links_status", "identity_resolution_status"),
    )
