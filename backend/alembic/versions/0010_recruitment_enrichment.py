"""招募立体化：七个可空扩展字段（全部向后兼容，不动既有行）。

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 追加列全部 nullable，既有数据零迁移成本
    op.add_column("recruitments", sa.Column("location", sa.String(60), nullable=True))
    op.add_column("recruitments", sa.Column("quota", sa.String(20), nullable=True))
    op.add_column(
        "recruitments", sa.Column("compensation", sa.String(60), nullable=True)
    )
    op.add_column("recruitments", sa.Column("duration", sa.String(40), nullable=True))
    op.add_column(
        "recruitments", sa.Column("apply_method", sa.String(200), nullable=True)
    )
    op.add_column("recruitments", sa.Column("tags", sa.JSON(), nullable=True))
    op.add_column("recruitments", sa.Column("advisor_id", sa.String(20), nullable=True))
    op.create_index("ix_recruitments_advisor_id", "recruitments", ["advisor_id"])


def downgrade() -> None:
    op.drop_index("ix_recruitments_advisor_id", table_name="recruitments")
    for column in (
        "advisor_id",
        "tags",
        "apply_method",
        "duration",
        "compensation",
        "quota",
        "location",
    ):
        op.drop_column("recruitments", column)
