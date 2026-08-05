"""实体建模（entities / entity_names / relations）。

对应规范「导师身份与实体建模」一节，是导师/导师组/实验室/院系的统一身份层。
迁移文件：alembic/versions/0003_advisor_radar_schema.py
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Entity(Base):
    """实体主表：person / advisor_group / lab / organization。"""

    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # person/advisor_group/lab/organization
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_zh: Mapped[Optional[str]] = mapped_column(String(100))
    name_en: Mapped[Optional[str]] = mapped_column(String(200))
    identity_status: Mapped[str] = mapped_column(String(20), default="unresolved")  # unresolved/pending_review/verified/conflicted
    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    publication_status: Mapped[str] = mapped_column(String(20), default="withheld")  # withheld/published/rejected/withdrawn
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_entities_type", "entity_type"),
        Index("ix_entities_name", "display_name"),
        Index("ix_entities_status", "identity_status", "publication_status"),
    )


class EntityName(Base):
    """名称别名：official_zh / official_en / pinyin / abbreviation / historical。"""

    __tablename__ = "entity_names"

    name_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )
    name_type: Mapped[Optional[str]] = mapped_column(String(20))
    name_value: Mapped[Optional[str]] = mapped_column(String(200))
    claim_id: Mapped[Optional[str]] = mapped_column(String(36))
    is_primary: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_entity_names_entity", "entity_id"),
        Index("ix_entity_names_value", "name_value"),
    )


class Relation(Base):
    """实体关系：affiliated_with / member_of / leads / part_of / joint_appointment_with。"""

    __tablename__ = "relations"

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claim_id: Mapped[Optional[str]] = mapped_column(String(36))
    relation_status: Mapped[str] = mapped_column(String(20), default="active")

    __table_args__ = (
        Index("ix_relations_subject", "subject_entity_id"),
        Index("ix_relations_object", "object_entity_id"),
        Index("ix_relations_type", "relation_type"),
    )
