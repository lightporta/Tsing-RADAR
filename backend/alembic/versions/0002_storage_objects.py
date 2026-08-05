"""storage objects table (v2.2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storage_objects",
        sa.Column("object_id", sa.String(36), primary_key=True),
        sa.Column("owner_subject", sa.String(64), nullable=True),
        sa.Column("bucket", sa.String(64), nullable=True),
        sa.Column("object_key", sa.String(128), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("declared_size", sa.String(32), nullable=True),
        sa.Column("mime", sa.String(128), nullable=True),
        sa.Column("scan_status", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_storage_objects_owner_subject", "storage_objects", ["owner_subject"])
    op.create_index("ix_storage_objects_scan_status", "storage_objects", ["scan_status"])


def downgrade() -> None:
    op.drop_index("ix_storage_objects_scan_status", table_name="storage_objects")
    op.drop_index("ix_storage_objects_owner_subject", table_name="storage_objects")
    op.drop_table("storage_objects")
