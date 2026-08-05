"""私域信号（学生反馈聚合层，D 级来源）。

⚠️ 物理隔离原则：
  - 本表永不进入任何公开接口（/api/advisors、/api/mentors 等）
  - 本表永不进入公开层视图（advisors_public_view）
  - 永不写入 consent_id 原文、反馈者姓名、原始消息编号到任何对外响应
  - 聚合规则：少于 3 份独立样本不形成信号；3-5 份标注「样本较少」
  - 仅当 review_status='approved' 且 sample_count >= 3 时，才可作为派生信号
    被推荐算法（/api/match）以加权方式消费，且必须附 disclaimer

与公开层关系：
  - 公开层（entities/claims/sources）只有 A/B/C 级来源
  - 本私域层（private_signals/private_feedback_raw）只有 D 级来源
  - 两层物理分表，无外键关联公开 entity_id 之外的私域字段
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PrivateFeedbackRaw(Base):
    """私域反馈原文（D 级来源，永不公开）。

    存储的是从评价网/问卷等渠道采集的原始反馈，含 consent_id 用于合规审计，
    但 consent_id 本身绝不进入任何对外接口。
    """

    __tablename__ = "private_feedback_raw"

    feedback_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )  # 关联公开层的导师实体（只引用 ID，不反向暴露私域）
    consent_id: Mapped[Optional[str]] = mapped_column(String(100))  # 授权编号，永不外泄
    source_ref: Mapped[Optional[str]] = mapped_column(String(200))  # 私域来源内部引用，永不外泄
    rating: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5
    comment_text: Mapped[Optional[str]] = mapped_column(Text)  # 反馈原文，永不外泄
    collector_role_id: Mapped[Optional[str]] = mapped_column(String(100))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    publication_status: Mapped[str] = mapped_column(String(20), default="withheld")

    __table_args__ = (
        Index("ix_pfr_entity", "entity_id"),
        Index("ix_pfr_consent", "consent_id"),
        Index("ix_pfr_status", "review_status", "publication_status"),
    )


class PrivateSignal(Base):
    """私域信号聚合（D 级，达到门槛后可被派生层消费）。

    由 PrivateFeedbackRaw 聚合而来，不存原文，只存统计指标。
    当 sample_count >= 3 且 review_status='approved' 时，可被推荐算法加权使用。
    sample_count 3-5 时调用方必须标注「样本较少」。
    """

    __tablename__ = "private_signals"

    signal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("entities.entity_id", ondelete="CASCADE")
    )
    signal_type: Mapped[Optional[str]] = mapped_column(String(50))
    # signal_type 维度示例：
    #   mentorship_style_avg  - 指导风格平均分（1-5）
    #   communication_avg     - 沟通频率平均分
    #   recommend_rate        - 推荐率（推荐人数/总样本）
    #   workload_avg          - 工作量平均分
    aggregate_value: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_window_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sample_window_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    aggregation_version: Mapped[Optional[str]] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    publication_status: Mapped[str] = mapped_column(String(20), default="withheld")

    __table_args__ = (
        Index("ix_ps_entity", "entity_id"),
        Index("ix_ps_type", "signal_type"),
        Index("ix_ps_status", "review_status", "publication_status"),
    )
