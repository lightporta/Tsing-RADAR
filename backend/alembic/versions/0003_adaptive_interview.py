"""adaptive interview and editable profile

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questionnaire_sessions",
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="in_progress",
        ),
    )
    op.add_column(
        "questionnaire_sessions",
        sa.Column("current_question_id", sa.String(50), nullable=True),
    )
    op.add_column(
        "questionnaire_sessions",
        sa.Column("answered_dimensions", sa.JSON(), nullable=True),
    )
    op.add_column(
        "questionnaire_sessions",
        sa.Column(
            "profile_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "questionnaire_sessions",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "questionnaire_sessions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    for column_name in (
        "updated_at",
        "confirmed_at",
        "profile_version",
        "answered_dimensions",
        "current_question_id",
        "status",
    ):
        op.drop_column("questionnaire_sessions", column_name)
