"""A6 idempotency, artifact audit and application/document invariants

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_legacy_applications() -> None:
    connection = op.get_bind()
    # A5 以前的 resume_id 可能引用旧 resumes 表。它不能作为当前私有对象
    # 的有效投递引用，因此保留记录但安全地撤回并清空悬空引用。
    connection.execute(
        sa.text(
            """
            UPDATE applications
               SET status = 'withdrawn', resume_id = NULL
             WHERE status != 'withdrawn'
               AND (
                    resume_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1
                          FROM private_documents d
                         WHERE d.document_id = applications.resume_id
                    )
               )
            """
        )
    )
    duplicate = connection.execute(
        sa.text(
            """
            SELECT student_id, recruit_id, resume_id, COUNT(*) AS count_rows
              FROM applications
             WHERE status != 'withdrawn'
             GROUP BY student_id, recruit_id, resume_id
            HAVING COUNT(*) > 1
             LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "存在重复有效站内投递；请先人工审计并撤回重复记录后再执行 0006"
        )


def _revoke_duplicate_delivery_grants() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT grant_id, document_id, audience, revoked
              FROM artifact_delivery_grants
             ORDER BY document_id, audience, created_at DESC, grant_id DESC
            """
        )
    ).mappings()
    active_seen: set[tuple[str, str]] = set()
    revoke_ids: list[str] = []
    for row in rows:
        if bool(row["revoked"]):
            continue
        key = (row["document_id"], row["audience"])
        if key in active_seen:
            revoke_ids.append(row["grant_id"])
        else:
            active_seen.add(key)
    for grant_id in revoke_ids:
        connection.execute(
            sa.text(
                "UPDATE artifact_delivery_grants "
                "SET revoked = :revoked WHERE grant_id = :grant_id"
            ),
            {"revoked": True, "grant_id": grant_id},
        )


def upgrade() -> None:
    _normalize_legacy_applications()
    with op.batch_alter_table("applications", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_applications_private_document",
            "private_documents",
            ["resume_id"],
            ["document_id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_active_application_has_document",
            "status = 'withdrawn' OR resume_id IS NOT NULL",
        )
    op.create_index(
        "uq_applications_active_document",
        "applications",
        ["student_id", "recruit_id", "resume_id"],
        unique=True,
        sqlite_where=sa.text("status != 'withdrawn'"),
        postgresql_where=sa.text("status != 'withdrawn'"),
    )

    with op.batch_alter_table("artifact_delivery_grants") as batch:
        batch.add_column(sa.Column("token_nonce", sa.String(64), nullable=True))
    _revoke_duplicate_delivery_grants()
    op.create_index(
        "uq_active_artifact_delivery_audience",
        "artifact_delivery_grants",
        ["document_id", "audience"],
        unique=True,
        sqlite_where=sa.text("revoked = 0"),
        postgresql_where=sa.text("revoked = false"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("idempotency_id", sa.String(36), primary_key=True),
        sa.Column("owner_subject_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("key_digest", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("attempt_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "owner_subject_id",
            "operation",
            "key_digest",
            name="uq_idempotency_owner_operation_key",
        ),
    )
    op.create_index(
        "ix_idempotency_records_owner_subject_id",
        "idempotency_records",
        ["owner_subject_id"],
    )

    op.create_table(
        "artifact_audit_events",
        sa.Column(
            "sequence_id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("owner_subject_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(64), nullable=True),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("scan_method", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_artifact_audit_events_owner_subject_id",
        "artifact_audit_events",
        ["owner_subject_id"],
    )
    op.create_index(
        "ix_artifact_audit_events_document_id",
        "artifact_audit_events",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_artifact_audit_events_document_id",
        table_name="artifact_audit_events",
    )
    op.drop_index(
        "ix_artifact_audit_events_owner_subject_id",
        table_name="artifact_audit_events",
    )
    op.drop_table("artifact_audit_events")
    op.drop_index(
        "ix_idempotency_records_owner_subject_id",
        table_name="idempotency_records",
    )
    op.drop_table("idempotency_records")

    op.drop_index(
        "uq_active_artifact_delivery_audience",
        table_name="artifact_delivery_grants",
    )
    with op.batch_alter_table("artifact_delivery_grants") as batch:
        batch.drop_column("token_nonce")

    op.drop_index(
        "uq_applications_active_document",
        table_name="applications",
    )
    with op.batch_alter_table("applications", recreate="always") as batch:
        batch.drop_constraint(
            "ck_active_application_has_document",
            type_="check",
        )
        batch.drop_constraint(
            "fk_applications_private_document",
            type_="foreignkey",
        )
