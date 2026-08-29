"""招募评论区：recruitment_comments 表（两级评论 + 分级审核 + 软删保楼层）。

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recruitment_comments",
        sa.Column("comment_id", sa.String(36), primary_key=True),
        sa.Column("recruit_id", sa.String(36), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),  # 仅两级
        sa.Column("author_principal", sa.String(64), nullable=False),
        sa.Column(
            "author_label",
            sa.String(20),
            nullable=False,
            server_default="student",
        ),
        sa.Column("is_op", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        # 审核历史（action/reviewer/reason/reviewed_at），与招募审核同构
        sa.Column("governance", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_recruitment_comments_recruit_id",
        "recruitment_comments",
        ["recruit_id"],
    )
    op.create_index(
        "ix_recruitment_comments_parent_id",
        "recruitment_comments",
        ["parent_id"],
    )
    op.create_index(
        "ix_recruitment_comments_author_principal",
        "recruitment_comments",
        ["author_principal"],
    )

    # 点赞去重表：每主体每评论一次（唯一约束兜底并发重放）
    op.create_table(
        "recruitment_comment_likes",
        sa.Column("like_id", sa.String(36), primary_key=True),
        sa.Column("comment_id", sa.String(36), nullable=False),
        sa.Column("principal", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "comment_id", "principal", name="uq_comment_like_once"
        ),
    )
    op.create_index(
        "ix_recruitment_comment_likes_comment_id",
        "recruitment_comment_likes",
        ["comment_id"],
    )
    op.create_index(
        "ix_recruitment_comment_likes_principal",
        "recruitment_comment_likes",
        ["principal"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recruitment_comment_likes_principal",
        table_name="recruitment_comment_likes",
    )
    op.drop_index(
        "ix_recruitment_comment_likes_comment_id",
        table_name="recruitment_comment_likes",
    )
    op.drop_table("recruitment_comment_likes")
    op.drop_index(
        "ix_recruitment_comments_author_principal",
        table_name="recruitment_comments",
    )
    op.drop_index(
        "ix_recruitment_comments_parent_id",
        table_name="recruitment_comments",
    )
    op.drop_index(
        "ix_recruitment_comments_recruit_id",
        table_name="recruitment_comments",
    )
    op.drop_table("recruitment_comments")
