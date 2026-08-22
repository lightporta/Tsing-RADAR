"""v4.3.0 阶段五：导师收藏表 mentor_favorites（幂等收藏）。

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mentor_favorites",
        sa.Column(
            "favorite_id", sa.String(36), primary_key=True
        ),
        sa.Column("student_id", sa.String(64), nullable=False, index=True),
        sa.Column("advisor_id", sa.String(64), nullable=False, index=True),
        # 展示用去规范化姓名（收藏时来自匹配上下文；advisor_id 为权威键）
        sa.Column("advisor_name", sa.String(120), nullable=False, default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "student_id", "advisor_id", name="uq_mentor_favorites_pair"
        ),
    )


def downgrade() -> None:
    op.drop_table("mentor_favorites")
