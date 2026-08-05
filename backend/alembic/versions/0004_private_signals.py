"""私域信号层（D 级来源，学生反馈聚合）。

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05

物理隔离设计：
  - 与公开层（entities/claims/sources）严格分表
  - 仅通过 entity_id 外键关联到公开层（不反向暴露私域字段）
  - consent_id / source_ref / comment_text 永不进入任何公开接口
  - 聚合规则：sample_count < 3 不形成信号；3-5 标注「样本较少」

跨方言：全部 ORM，无 MySQL 专属语法。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 私域反馈原文（D 级，永不公开）────────────────────────────────
    op.create_table(
        "private_feedback_raw",
        sa.Column("feedback_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("consent_id", sa.String(100)),  # 授权编号，永不外泄
        sa.Column("source_ref", sa.String(200)),   # 私域内部引用，永不外泄
        sa.Column("rating", sa.Integer),
        sa.Column("comment_text", sa.Text),        # 原文，永不外泄
        sa.Column("collector_role_id", sa.String(100)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_status", sa.String(20), server_default="pending_review"),
        sa.Column("publication_status", sa.String(20), server_default="withheld"),
    )
    op.create_index("ix_pfr_entity", "private_feedback_raw", ["entity_id"])
    op.create_index("ix_pfr_consent", "private_feedback_raw", ["consent_id"])
    op.create_index("ix_pfr_status", "private_feedback_raw", ["review_status", "publication_status"])

    # ── 私域聚合信号（达到门槛后才可被派生层消费）──────────────────────
    op.create_table(
        "private_signals",
        sa.Column("signal_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("signal_type", sa.String(50)),
        sa.Column("aggregate_value", sa.Float),
        sa.Column("sample_count", sa.Integer, server_default="0"),
        sa.Column("sample_window_from", sa.DateTime(timezone=True)),
        sa.Column("sample_window_until", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.Float),
        sa.Column("aggregation_version", sa.String(20)),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_status", sa.String(20), server_default="pending_review"),
        sa.Column("publication_status", sa.String(20), server_default="withheld"),
    )
    op.create_index("ix_ps_entity", "private_signals", ["entity_id"])
    op.create_index("ix_ps_type", "private_signals", ["signal_type"])
    op.create_index("ix_ps_status", "private_signals", ["review_status", "publication_status"])


def downgrade() -> None:
    op.drop_index("ix_ps_status", table_name="private_signals")
    op.drop_index("ix_ps_type", table_name="private_signals")
    op.drop_index("ix_ps_entity", table_name="private_signals")
    op.drop_table("private_signals")

    op.drop_index("ix_pfr_status", table_name="private_feedback_raw")
    op.drop_index("ix_pfr_consent", table_name="private_feedback_raw")
    op.drop_index("ix_pfr_entity", table_name="private_feedback_raw")
    op.drop_table("private_feedback_raw")
