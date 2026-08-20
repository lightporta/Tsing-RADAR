"""Mentor campus card manual verification schema.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 导师校园卡人工审核：认领导师档案的前置身份审核。
    # 只存元数据与哈希；私有材料审核后由应用层清理对象存储。
    op.create_table(
        "mentor_campus_cards",
        sa.Column("card_id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("object_backend", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("material_cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mentor_campus_cards_account_id",
        "mentor_campus_cards",
        ["account_id"],
    )
    op.create_index(
        "ix_mentor_campus_cards_status",
        "mentor_campus_cards",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mentor_campus_cards_status",
        table_name="mentor_campus_cards",
    )
    op.drop_index(
        "ix_mentor_campus_cards_account_id",
        table_name="mentor_campus_cards",
    )
    op.drop_table("mentor_campus_cards")
