"""A5 server-side identity, object ownership and private documents

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-30
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _orphan_legacy_owners(table: str, key: str, owner: str) -> None:
    """旧客户端身份不可信；迁移为不可登录的随机孤儿主体。"""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(f"SELECT {key} FROM {table}")  # noqa: S608 - 固定迁移常量
    ).fetchall()
    for (object_id,) in rows:
        connection.execute(
            sa.text(
                f"UPDATE {table} SET {owner} = :subject WHERE {key} = :object_id"
            ),  # noqa: S608 - 固定迁移常量
            {
                "subject": f"legacy_orphan_{uuid.uuid4().hex}",
                "object_id": object_id,
            },
        )


def upgrade() -> None:
    op.create_table(
        "identity_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_identity_sessions_subject_id", "identity_sessions", ["subject_id"])

    op.create_table(
        "external_identities",
        sa.Column("mapping_id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("claim_fingerprint", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider",
            "claim_fingerprint",
            name="uq_external_identity",
        ),
    )
    op.create_index("ix_external_identities_subject_id", "external_identities", ["subject_id"])

    op.create_table(
        "private_documents",
        sa.Column("document_id", sa.String(36), primary_key=True),
        sa.Column("owner_subject_id", sa.String(64), nullable=False),
        sa.Column("original_name", sa.String(180), nullable=False),
        sa.Column("stored_name", sa.String(80), nullable=False, unique=True),
        sa.Column("extension", sa.String(8), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_private_documents_owner_subject_id",
        "private_documents",
        ["owner_subject_id"],
    )

    for table, key, owner in (
        ("questionnaire_sessions", "session_id", "student_id"),
        ("applications", "app_id", "student_id"),
        ("feedback", "feedback_id", "student_id"),
        ("recruitments", "recruit_id", "publisher_id"),
    ):
        _orphan_legacy_owners(table, key, owner)
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                owner,
                existing_type=sa.String(20),
                type_=sa.String(64),
                nullable=False,
            )

    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            )
        )
        batch.alter_column(
            "status",
            existing_type=sa.String(20),
            nullable=False,
            server_default="submitted",
        )


def downgrade() -> None:
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("updated_at")
    for table, owner in (
        ("recruitments", "publisher_id"),
        ("feedback", "student_id"),
        ("applications", "student_id"),
        ("questionnaire_sessions", "student_id"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                owner,
                existing_type=sa.String(64),
                type_=sa.String(20),
                nullable=True,
            )
    op.drop_index(
        "ix_private_documents_owner_subject_id",
        table_name="private_documents",
    )
    op.drop_table("private_documents")
    op.drop_index("ix_external_identities_subject_id", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_index("ix_identity_sessions_subject_id", table_name="identity_sessions")
    op.drop_table("identity_sessions")
