"""Mentor service: email-code accounts, claims, field edits, takedowns, profiles

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 导师账号：邮箱验证码登录后绑定到复用中的 Web 会话（bound_session_id）。
    op.create_table(
        "mentor_accounts",
        sa.Column("account_id", sa.String(36), primary_key=True),
        sa.Column("advisor_id", sa.String(20), nullable=True),
        sa.Column("email", sa.String(100), nullable=False, unique=True),
        sa.Column("subject_id", sa.String(64), nullable=False, unique=True),
        # 当前绑定到哪个 Web 会话（复用 identity_sessions，不新增会话表/cookie）
        sa.Column("bound_session_id", sa.String(36), nullable=True, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_mentor_accounts_advisor_id",
        "mentor_accounts",
        ["advisor_id"],
    )

    # 邮箱验证码：只存 SHA-256 摘要，不留明文；含限频/过期/重试计数字段。
    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_email_verification_codes_email",
        "email_verification_codes",
        ["email"],
    )

    # 档案认领申请与审批记录（唯一候选可自动绑定，多候选转人工审批）。
    op.create_table(
        "mentor_claims",
        sa.Column("claim_id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey(
                "mentor_accounts.account_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("advisor_id", sa.String(20), nullable=True),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("factor_used", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_mentor_claims_account_id",
        "mentor_claims",
        ["account_id"],
    )

    # 导师档案字段级编辑申请（逐字段进审批流）。
    op.create_table(
        "mentor_profile_edits",
        sa.Column("edit_id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey(
                "mentor_accounts.account_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("advisor_id", sa.String(20), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_mentor_profile_edits_account_id",
        "mentor_profile_edits",
        ["account_id"],
    )
    op.create_index(
        "ix_mentor_profile_edits_advisor_id",
        "mentor_profile_edits",
        ["advisor_id"],
    )

    # 隐私下线/字段隐藏申请（full 整档下线 / field 单字段隐藏）。
    op.create_table(
        "takedown_requests",
        sa.Column("req_id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey(
                "mentor_accounts.account_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("advisor_id", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_takedown_requests_account_id",
        "takedown_requests",
        ["account_id"],
    )
    op.create_index(
        "ix_takedown_requests_advisor_id",
        "takedown_requests",
        ["advisor_id"],
    )

    # 导师档案覆盖层：过审自述字段 + 字段展示策略 + 整档下线时间戳。
    op.create_table(
        "mentor_profiles",
        sa.Column("profile_id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey(
                "mentor_accounts.account_id",
                ondelete="CASCADE",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("advisor_id", sa.String(20), nullable=False, unique=True),
        sa.Column("self_claims", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.JSON(), nullable=False),
        sa.Column("takedown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("mentor_profiles")
    op.drop_index("ix_takedown_requests_advisor_id", table_name="takedown_requests")
    op.drop_index("ix_takedown_requests_account_id", table_name="takedown_requests")
    op.drop_table("takedown_requests")
    op.drop_index(
        "ix_mentor_profile_edits_advisor_id",
        table_name="mentor_profile_edits",
    )
    op.drop_index(
        "ix_mentor_profile_edits_account_id",
        table_name="mentor_profile_edits",
    )
    op.drop_table("mentor_profile_edits")
    op.drop_index("ix_mentor_claims_account_id", table_name="mentor_claims")
    op.drop_table("mentor_claims")
    op.drop_index(
        "ix_email_verification_codes_email",
        table_name="email_verification_codes",
    )
    op.drop_table("email_verification_codes")
    op.drop_index("ix_mentor_accounts_advisor_id", table_name="mentor_accounts")
    op.drop_table("mentor_accounts")
