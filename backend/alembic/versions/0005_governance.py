"""治理层（审核 / 问题 / 批次指标，对应规范第 3.3 节）。

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05

补齐发布门禁工作流所需的三张表：
  - reviews：审核记录（4 阶段审核链）
  - issues：待核验问题（含 blocking 严重度门禁）
  - batch_metrics：批次质量指标（验收门槛的物化体现）

跨方言：全部 ORM，无 MySQL 专属语法。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 11_REVIEWS：审核记录 ──────────────────────────────────────
    op.create_table(
        "reviews",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column("target_type", sa.String(30), nullable=False),  # batch/entity/claim/opportunity
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("review_stage", sa.String(30), nullable=False),
        # collector_self_check / peer_review / publication_approval / independent_audit
        sa.Column("reviewer_role_id", sa.String(100)),
        sa.Column("review_status", sa.String(20), server_default="pending_review"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reason_code", sa.String(50)),  # 拒绝时受控错误码
        sa.Column("note_sanitized", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reviews_target", "reviews", ["target_type", "target_id"])
    op.create_index("ix_reviews_stage", "reviews", ["review_stage"])
    op.create_index("ix_reviews_status", "reviews", ["review_status"])

    # ── 12_ISSUES：待核验问题 ─────────────────────────────────────
    op.create_table(
        "issues",
        sa.Column("issue_id", sa.String(36), primary_key=True),
        sa.Column("target_type", sa.String(30)),
        sa.Column("target_id", sa.String(36)),
        sa.Column("issue_type", sa.String(50), nullable=False),
        # identity_ambiguous / official_page_missing / source_unavailable / ...
        sa.Column("severity", sa.String(20), server_default="medium"),
        # blocking / high / medium / low
        sa.Column("issue_status", sa.String(20), server_default="open"),
        # open / resolved / accepted_missing / rejected
        sa.Column("assigned_role_id", sa.String(100)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_code", sa.String(50)),
        sa.Column("note_sanitized", sa.Text),
    )
    op.create_index("ix_issues_target", "issues", ["target_type", "target_id"])
    op.create_index("ix_issues_type", "issues", ["issue_type"])
    op.create_index("ix_issues_severity", "issues", ["severity", "issue_status"])

    # ── 13_BATCH_METRICS：批次质量指标 ────────────────────────────
    op.create_table(
        "batch_metrics",
        sa.Column("metric_id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("metric_value", sa.Float, nullable=False),
        sa.Column("metric_denominator", sa.Float),
        sa.Column("metric_status", sa.String(20), nullable=False),
        # pass / fail / informational
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method_version", sa.String(20)),
    )
    op.create_index("ix_bm_batch", "batch_metrics", ["batch_id"])
    op.create_index("ix_bm_name", "batch_metrics", ["metric_name"])
    op.create_index("ix_bm_status", "batch_metrics", ["metric_status"])


def downgrade() -> None:
    op.drop_index("ix_bm_status", table_name="batch_metrics")
    op.drop_index("ix_bm_name", table_name="batch_metrics")
    op.drop_index("ix_bm_batch", table_name="batch_metrics")
    op.drop_table("batch_metrics")

    op.drop_index("ix_issues_severity", table_name="issues")
    op.drop_index("ix_issues_type", table_name="issues")
    op.drop_index("ix_issues_target", table_name="issues")
    op.drop_table("issues")

    op.drop_index("ix_reviews_status", table_name="reviews")
    op.drop_index("ix_reviews_stage", table_name="reviews")
    op.drop_index("ix_reviews_target", table_name="reviews")
    op.drop_table("reviews")
