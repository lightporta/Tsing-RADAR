"""Advisor rating schema: ratings + summary materialized view.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 学生六维匿名评分：一人一导师一条（唯一约束），M1 仅存纯分数。
    op.create_table(
        "advisor_ratings",
        sa.Column("rating_id", sa.String(36), primary_key=True),
        sa.Column("advisor_id", sa.String(20), nullable=False),
        sa.Column("rater_principal", sa.String(64), nullable=False),
        sa.Column("rater_verified", sa.Boolean(), nullable=False),
        sa.Column("period_in_group", sa.String(20), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "advisor_id",
            "rater_principal",
            name="uq_one_rating_per_rater",
        ),
    )
    op.create_index(
        "ix_advisor_ratings_advisor_id",
        "advisor_ratings",
        ["advisor_id"],
    )
    op.create_index(
        "ix_advisor_ratings_rater_principal",
        "advisor_ratings",
        ["rater_principal"],
    )
    op.create_index(
        "ix_advisor_ratings_status",
        "advisor_ratings",
        ["review_status"],
    )

    # 物化聚合表：审核通过时重算，读取零计算（吸取 L-03 全量重算教训）。
    op.create_table(
        "advisor_rating_summary",
        sa.Column("advisor_id", sa.String(20), primary_key=True),
        sa.Column("acumen_value", sa.Float(), nullable=True),
        sa.Column("acumen_n", sa.Integer(), nullable=False),
        sa.Column("network_value", sa.Float(), nullable=True),
        sa.Column("network_n", sa.Integer(), nullable=False),
        sa.Column("mentorship_value", sa.Float(), nullable=True),
        sa.Column("mentorship_n", sa.Integer(), nullable=False),
        sa.Column("tolerance_value", sa.Float(), nullable=True),
        sa.Column("tolerance_n", sa.Integer(), nullable=False),
        sa.Column("funding_value", sa.Float(), nullable=True),
        sa.Column("funding_n", sa.Integer(), nullable=False),
        sa.Column("efficiency_value", sa.Float(), nullable=True),
        sa.Column("efficiency_n", sa.Integer(), nullable=False),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("advisor_rating_summary")
    op.drop_index("ix_advisor_ratings_status", table_name="advisor_ratings")
    op.drop_index(
        "ix_advisor_ratings_rater_principal",
        table_name="advisor_ratings",
    )
    op.drop_index(
        "ix_advisor_ratings_advisor_id",
        table_name="advisor_ratings",
    )
    op.drop_table("advisor_ratings")
