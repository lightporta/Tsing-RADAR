"""evidence-aware data governance

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_governance_columns(table_name: str, *, created_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("provenance", sa.JSON(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("governance", sa.JSON(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("quarantined_fields", sa.JSON(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default="pending_review",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "publication_status",
            sa.String(20),
            nullable=False,
            server_default="restricted",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "authorization_basis",
            sa.String(40),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        table_name,
        sa.Column("consent_id", sa.String(100), nullable=True),
    )
    if created_name == "record_created_at":
        op.add_column(
            table_name,
            sa.Column(
                "record_created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    op.add_column(
        table_name,
        sa.Column(
            "record_updated_at" if table_name == "advisors" else "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        table_name,
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("takedown_at", sa.DateTime(timezone=True), nullable=True),
    )


def upgrade() -> None:
    _add_governance_columns("advisors", created_name="record_created_at")
    _add_governance_columns("recruitments", created_name="created_at")


def downgrade() -> None:
    advisor_columns = [
        "takedown_at",
        "expires_at",
        "verified_at",
        "record_updated_at",
        "record_created_at",
        "consent_id",
        "authorization_basis",
        "publication_status",
        "review_status",
        "quarantined_fields",
        "governance",
        "provenance",
    ]
    recruitment_columns = [
        "takedown_at",
        "expires_at",
        "verified_at",
        "updated_at",
        "consent_id",
        "authorization_basis",
        "publication_status",
        "review_status",
        "quarantined_fields",
        "governance",
        "provenance",
    ]
    for column_name in advisor_columns:
        op.drop_column("advisors", column_name)
    for column_name in recruitment_columns:
        op.drop_column("recruitments", column_name)
