"""A6 private artifacts, scan state and signed delivery grants

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("private_documents") as batch:
        batch.add_column(
            sa.Column(
                "document_kind",
                sa.String(24),
                nullable=False,
                server_default="upload",
            )
        )
        batch.add_column(
            sa.Column(
                "object_backend",
                sa.String(16),
                nullable=False,
                server_default="local",
            )
        )
        batch.add_column(
            sa.Column(
                "scan_status",
                sa.String(24),
                nullable=False,
                server_default="unscanned",
            )
        )
        batch.add_column(
            sa.Column(
                "scan_method",
                sa.String(80),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column("scan_checked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("source_session_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "generation_context",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column("user_confirmed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_private_documents_source_session_id",
            ["source_session_id"],
        )

    op.create_table(
        "artifact_delivery_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("private_documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_subject_id", sa.String(64), nullable=False),
        sa.Column("audience", sa.String(24), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_downloads", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_artifact_delivery_grants_document_id",
        "artifact_delivery_grants",
        ["document_id"],
    )
    op.create_index(
        "ix_artifact_delivery_grants_owner_subject_id",
        "artifact_delivery_grants",
        ["owner_subject_id"],
    )
    op.create_table(
        "deleted_artifact_tombstones",
        sa.Column("document_id", sa.String(36), primary_key=True),
        sa.Column("owner_subject_id", sa.String(64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_deleted_artifact_tombstones_owner_subject_id",
        "deleted_artifact_tombstones",
        ["owner_subject_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deleted_artifact_tombstones_owner_subject_id",
        table_name="deleted_artifact_tombstones",
    )
    op.drop_table("deleted_artifact_tombstones")
    op.drop_index(
        "ix_artifact_delivery_grants_owner_subject_id",
        table_name="artifact_delivery_grants",
    )
    op.drop_index(
        "ix_artifact_delivery_grants_document_id",
        table_name="artifact_delivery_grants",
    )
    op.drop_table("artifact_delivery_grants")

    with op.batch_alter_table("private_documents") as batch:
        batch.drop_index("ix_private_documents_source_session_id")
        for column_name in (
            "user_confirmed_at",
            "generation_context",
            "source_session_id",
            "scan_checked_at",
            "scan_method",
            "scan_status",
            "object_backend",
            "document_kind",
        ):
            batch.drop_column(column_name)
