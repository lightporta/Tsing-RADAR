"""治理层（审核 / 问题 / 批次指标）。

对应规范第 3.3 节要求的 11_REVIEWS / 12_ISSUES / 13_BATCH_METRICS 三张表。
这三张表是发布门禁工作流的物理支撑：
  - reviews 记录每个对象经过的审核阶段（采集自检 → 同行复核 → 发布审批 → 独立审计）
  - issues 记录所有待核验问题与冲突
  - batch_metrics 记录批次级质量指标，是验收门槛的物化体现
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Review(Base):
    """审核记录（11_REVIEWS）。

    审核阶段（review_stage）：
      - collector_self_check：采集人员自检
      - peer_review：同行复核（不得与采集者相同）
      - publication_approval：发布审批
      - independent_audit：独立审计
    """

    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(30))  # batch / entity / claim / opportunity
    target_id: Mapped[str] = mapped_column(String(36))
    review_stage: Mapped[str] = mapped_column(String(30))
    reviewer_role_id: Mapped[Optional[str]] = mapped_column(String(100))
    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    # pending_review / in_review / verified / rejected
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[Optional[str]] = mapped_column(String(50))  # 拒绝时受控错误码
    note_sanitized: Mapped[Optional[str]] = mapped_column(Text)  # 简短说明，不得含私域
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_reviews_target", "target_type", "target_id"),
        Index("ix_reviews_stage", "review_stage"),
        Index("ix_reviews_status", "review_status"),
    )


class Issue(Base):
    """待核验问题（12_ISSUES）。

    issue_type 受控枚举（规范第 5.12 节）：
      identity_ambiguous / official_page_missing / source_unavailable /
      page_structure_changed / source_content_changed / field_missing /
      field_conflict / invalid_url / invalid_timestamp / invalid_hash /
      duplicate_entity / duplicate_claim / expired_opportunity /
      authorization_missing / privacy_risk / unsupported_inference
    """

    __tablename__ = "issues"

    issue_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(30))
    target_id: Mapped[Optional[str]] = mapped_column(String(36))
    issue_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    # blocking / high / medium / low（blocking 必须解决才能发布）
    issue_status: Mapped[str] = mapped_column(String(20), default="open")
    # open / resolved / accepted_missing / rejected
    assigned_role_id: Mapped[Optional[str]] = mapped_column(String(100))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_code: Mapped[Optional[str]] = mapped_column(String(50))
    note_sanitized: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_issues_target", "target_type", "target_id"),
        Index("ix_issues_type", "issue_type"),
        Index("ix_issues_severity", "severity", "issue_status"),
    )


class BatchMetric(Base):
    """批次质量指标（13_BATCH_METRICS）。

    metric_name 受控指标（规范第 5.13 节）：
      entity_count / verified_identity_count / published_candidate_count /
      claim_count / missing_required_field_count / orphan_reference_count /
      duplicate_entity_count / duplicate_claim_count / invalid_url_count /
      missing_timezone_count / invalid_hash_count / open_conflict_count /
      expired_opportunity_count / source_class_{A,B,C,D,E}_count /
      private_data_leak_count / collector_reviewer_overlap_count
    """

    __tablename__ = "batch_metrics"

    metric_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    metric_name: Mapped[str] = mapped_column(String(80))
    metric_value: Mapped[float] = mapped_column(Float)
    metric_denominator: Mapped[Optional[float]] = mapped_column(Float)
    # 比例指标的分母
    metric_status: Mapped[str] = mapped_column(String(20))
    # pass / fail / informational（fail 表示未通过门禁）
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method_version: Mapped[Optional[str]] = mapped_column(String(20))

    __table_args__ = (
        Index("ix_bm_batch", "batch_id"),
        Index("ix_bm_name", "metric_name"),
        Index("ix_bm_status", "metric_status"),
    )
