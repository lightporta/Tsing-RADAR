"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("student_id", sa.String(20), primary_key=True),
        sa.Column("email", sa.String(50)),
        sa.Column("department", sa.String(50)),
        sa.Column("category", sa.String(20)),
        sa.Column("grade", sa.String(20)),
        sa.Column("phone", sa.String(20)),
        sa.Column("profile_text", sa.Text),
        sa.Column("interest_vector", sa.JSON),
    )
    op.create_table(
        "advisors",
        sa.Column("advisor_id", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(50)),
        sa.Column("department", sa.String(50)),
        sa.Column("field", sa.String(200)),
        sa.Column("tags", sa.JSON),
        sa.Column("profile_text", sa.Text),
        sa.Column("recent_papers", sa.JSON),
        sa.Column("contact_email", sa.String(50)),
        sa.Column("office_loc", sa.String(50)),
        sa.Column("radar_traits", sa.JSON),
        sa.Column("popularity", sa.Float, default=0),
        sa.Column("sector", sa.Float, default=0),
    )
    op.create_table(
        "match_records",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(20), sa.ForeignKey("students.student_id")),
        sa.Column("advisor_id", sa.String(20), sa.ForeignKey("advisors.advisor_id")),
        sa.Column("synergy_score", sa.Float),
        sa.Column("match_reason", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "resumes",
        sa.Column("resume_id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(20)),
        sa.Column("title", sa.String(100)),
        sa.Column("content", sa.JSON),
        sa.Column("polished_text", sa.Text),
        sa.Column("target_advisor_id", sa.String(20)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "recruitments",
        sa.Column("recruit_id", sa.String(36), primary_key=True),
        sa.Column("publisher_id", sa.String(20)),
        sa.Column("publisher_type", sa.String(20)),
        sa.Column("type", sa.String(20)),
        sa.Column("title", sa.String(200)),
        sa.Column("req", sa.Text),
        sa.Column("major", sa.String(100)),
        sa.Column("deadline", sa.Date),
        sa.Column("is_urgent", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "applications",
        sa.Column("app_id", sa.String(36), primary_key=True),
        sa.Column("recruit_id", sa.String(36)),
        sa.Column("student_id", sa.String(20)),
        sa.Column("resume_id", sa.String(36)),
        sa.Column("status", sa.String(20), default="待处理"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "feedback",
        sa.Column("feedback_id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(20)),
        sa.Column("advisor_id", sa.String(20)),
        sa.Column("rating", sa.Integer),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "questionnaire_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(20)),
        sa.Column("messages", sa.JSON),
        sa.Column("portrait", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "training_samples",
        sa.Column("sample_id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(20)),
        sa.Column("questionnaire_id", sa.String(36)),
        sa.Column("chosen_advisor_id", sa.String(20)),
        sa.Column("features", sa.JSON),
        sa.Column("label", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in [
        "training_samples",
        "questionnaire_sessions",
        "feedback",
        "applications",
        "recruitments",
        "resumes",
        "match_records",
        "advisors",
        "students",
    ]:
        op.drop_table(table)
