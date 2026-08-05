"""研究方向（directions / entity_directions）。

三层结构：level_1（一级） → level_2（二级） → specific_topic（具体题目）。
通过 entity_directions 关联到实体，并标记 direction_scope 区分证据强度。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Direction(Base):
    """研究方向字典表（去重的方向记录）。"""

    __tablename__ = "directions"

    direction_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    level_1: Mapped[str] = mapped_column(String(100), nullable=False)
    level_2: Mapped[Optional[str]] = mapped_column(String(100))
    specific_topic: Mapped[str] = mapped_column(String(500), nullable=False)
    application_context: Mapped[Optional[str]] = mapped_column(Text)
    method_or_technology: Mapped[Optional[str]] = mapped_column(Text)
    normalization_version: Mapped[Optional[str]] = mapped_column(String(20))

    __table_args__ = (
        Index("ix_directions_level1", "level_1"),
        Index("ix_directions_level2", "level_2"),
        Index("ix_directions_topic", "specific_topic"),
    )


class EntityDirection(Base):
    """实体-方向关系表。

    direction_scope:
      - current_official: 当前官方主页/院系页明确列出
      - catalog_only: 仅出现在招生目录
      - historical: 历史研究方向
      - publication_signal_only: 仅由论文信号推断
    """

    __tablename__ = "entity_directions"

    entity_direction_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )
    direction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("directions.direction_id", ondelete="CASCADE")
    )
    direction_scope: Mapped[Optional[str]] = mapped_column(String(30))
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claim_id: Mapped[Optional[str]] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_entity_directions_entity", "entity_id"),
        Index("ix_entity_directions_direction", "direction_id"),
        Index("ix_entity_directions_scope", "direction_scope"),
    )
