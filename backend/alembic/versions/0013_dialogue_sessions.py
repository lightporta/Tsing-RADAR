"""v2.5 对话模式状态表：dialogue_sessions（简历分步采集等跨轮状态）。

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dialogue_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_dialogue_sessions_student_id",
        "dialogue_sessions",
        ["student_id"],
    )
    op.create_index(
        "ix_dialogue_sessions_mode",
        "dialogue_sessions",
        ["mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_dialogue_sessions_mode", table_name="dialogue_sessions")
    op.drop_index("ix_dialogue_sessions_student_id", table_name="dialogue_sessions")
    op.drop_table("dialogue_sessions")
