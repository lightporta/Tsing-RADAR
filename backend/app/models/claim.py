"""字段级证据（claims / sources）。

每条事实都通过 claim 引用一条 source，并附带两个 SHA-256（page / fragment）。
这是「可追溯」原则的物理实现：每条公开事实都能回到原始来源。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Source(Base):
    """来源元数据：source_class A/B/C/D/E 决定可信度与可见层。"""

    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_class: Mapped[str] = mapped_column(String(1), nullable=False)  # A/B/C/D/E
    source_type: Mapped[Optional[str]] = mapped_column(String(50))
    source_title: Mapped[Optional[str]] = mapped_column(Text)
    public_url: Mapped[Optional[str]] = mapped_column(Text)
    publisher: Mapped[Optional[str]] = mapped_column(String(200))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_content_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    snapshot_id: Mapped[Optional[str]] = mapped_column(String(100))
    access_status: Mapped[Optional[str]] = mapped_column(String(30))
    visibility: Mapped[str] = mapped_column(String(20), default="public")

    __table_args__ = (
        Index("ix_sources_class", "source_class"),
        Index("ix_sources_visibility", "visibility"),
    )


class Claim(Base):
    """字段级证据声明。

    subject_type + subject_id 指向被证明的对象（entity / relation / direction / catalog_link / opportunity / entity_name）。
    每条事实必须有 raw_text（原文摘录）和 fragment_sha256（片段指纹）。
    """

    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_id: Mapped[Optional[str]] = mapped_column(String(36))
    subject_type: Mapped[Optional[str]] = mapped_column(String(30))
    subject_id: Mapped[Optional[str]] = mapped_column(String(36))
    field_name: Mapped[Optional[str]] = mapped_column(String(100))
    normalized_value: Mapped[Optional[str]] = mapped_column(Text)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("sources.source_id")
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    page_content_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    fragment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[Optional[str]] = mapped_column(String(100))
    capture_method: Mapped[Optional[str]] = mapped_column(String(30))  # crawler/manual
    method_version: Mapped[Optional[str]] = mapped_column(String(20))
    normalization_version: Mapped[Optional[str]] = mapped_column(String(20))
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified")
    conflict_status: Mapped[str] = mapped_column(String(20), default="none")
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    publication_status: Mapped[str] = mapped_column(String(20), default="withheld")
    collector_role_id: Mapped[Optional[str]] = mapped_column(String(100))
    batch_id: Mapped[Optional[str]] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_claims_subject", "subject_type", "subject_id"),
        Index("ix_claims_field", "field_name"),
        Index("ix_claims_source", "source_id"),
        Index("ix_claims_status", "verification_status", "conflict_status", "publication_status"),
        Index("ix_claims_batch", "batch_id"),
    )
