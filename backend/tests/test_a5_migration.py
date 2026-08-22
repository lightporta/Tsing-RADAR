"""私有文档迁移可从空库升级，并可在 0004/head 间往返。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from app.core.config import settings


def test_a6_migration_reaches_head_with_private_delivery_and_delete_tables(tmp_path):
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "a5_migration.db"
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    migration_url = f"sqlite:///{database.as_posix()}"
    config.set_main_option("sqlalchemy.url", migration_url)
    previous_url = settings.DATABASE_URL
    settings.DATABASE_URL = migration_url
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0004")
        command.upgrade(config, "head")
    finally:
        settings.DATABASE_URL = previous_url

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert {
        "identity_sessions",
        "external_identities",
        "private_documents",
        "artifact_delivery_grants",
        "deleted_artifact_tombstones",
        "idempotency_records",
        "artifact_audit_events",
        "questionnaire_sessions",
        "applications",
        "mentor_accounts",
        "email_verification_codes",
        "mentor_claims",
        "mentor_profile_edits",
        "takedown_requests",
        "mentor_profiles",
        "advisor_ratings",
        "advisor_rating_summary",
        "recruitment_comments",
        "recruitment_comment_likes",
    }.issubset(inspector.get_table_names())
    # 招募立体化扩展列（0010，全部可空向后兼容）
    assert {
        "location",
        "quota",
        "compensation",
        "duration",
        "apply_method",
        "tags",
        "advisor_id",
    }.issubset({item["name"] for item in inspector.get_columns("recruitments")})
    # 评论表关键列（0011）
    assert {
        "comment_id",
        "recruit_id",
        "parent_id",
        "author_principal",
        "review_status",
        "like_count",
        "deleted_at",
    }.issubset(
        {item["name"] for item in inspector.get_columns("recruitment_comments")}
    )
    assert {
        item["name"]
        for item in inspector.get_columns("private_documents")
    } >= {
        "owner_subject_id",
        "stored_name",
        "media_type",
        "sha256",
        "extracted_text",
        "document_kind",
        "object_backend",
        "scan_status",
        "scan_method",
        "source_session_id",
        "generation_context",
        "user_confirmed_at",
    }
    delivery_foreign_keys = inspector.get_foreign_keys(
        "artifact_delivery_grants"
    )
    assert len(delivery_foreign_keys) == 1
    assert delivery_foreign_keys[0]["referred_table"] == "private_documents"
    assert delivery_foreign_keys[0]["options"].get("ondelete") == "CASCADE"
    application_foreign_keys = inspector.get_foreign_keys("applications")
    assert any(
        item["referred_table"] == "private_documents"
        and item["options"].get("ondelete") == "SET NULL"
        for item in application_foreign_keys
    )
    assert "token_nonce" in {
        item["name"]
        for item in inspector.get_columns("artifact_delivery_grants")
    }
    assert "attempt_digest" in {
        item["name"]
        for item in inspector.get_columns("idempotency_records")
    }
    assert {
        "uq_active_artifact_delivery_audience",
    }.issubset(
        {item["name"] for item in inspector.get_indexes("artifact_delivery_grants")}
    )
    assert {
        "uq_applications_active_document",
    }.issubset(
        {item["name"] for item in inspector.get_indexes("applications")}
    )
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    # 迁移链随版本合法推进：0013（v3.1.7 dialogue_sessions）/ 0014（v4.0.0
    # user_memories）/ 0015（v4.3.0 mentor_favorites）；断言跟随当前唯一头。
    assert revision == "0015"
    engine.dispose()


def test_0007_clears_only_redundant_extracted_text_and_downgrade_does_not_restore_it(
    tmp_path,
    monkeypatch,
):
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "private_text_cleanup.db"
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    migration_url = f"sqlite:///{database.as_posix()}"
    config.set_main_option("sqlalchemy.url", migration_url)
    monkeypatch.setattr(settings, "DATABASE_URL", migration_url)

    command.upgrade(config, "0006")
    engine = create_engine(migration_url)
    immutable_fields = {
        "document_id": "00000000-0000-0000-0000-000000000007",
        "owner_subject_id": "migration-owner",
        "original_name": "private.docx",
        "stored_name": "objects/migration-private.docx",
        "extension": ".docx",
        "media_type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "size_bytes": 321,
        "sha256": "7" * 64,
        "status": "ready",
        "document_kind": "upload",
        "object_backend": "s3",
        "scan_status": "clean",
        "scan_method": "migration-test",
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO private_documents (
                    document_id, owner_subject_id, original_name, stored_name,
                    extension, media_type, size_bytes, sha256, status,
                    extracted_text, document_kind, object_backend,
                    scan_status, scan_method, generation_context
                ) VALUES (
                    :document_id, :owner_subject_id, :original_name, :stored_name,
                    :extension, :media_type, :size_bytes, :sha256, :status,
                    :extracted_text, :document_kind, :object_backend,
                    :scan_status, :scan_method, '{}'
                )
                """
            ),
            {**immutable_fields, "extracted_text": "必须由迁移清除的历史正文"},
        )
    command.upgrade(config, "0007")
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT * FROM private_documents WHERE document_id = :id"),
            {"id": immutable_fields["document_id"]},
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["extracted_text"] == ""
    for field, expected in immutable_fields.items():
        assert rows[0][field] == expected

    command.downgrade(config, "0006")
    with engine.connect() as connection:
        downgraded = connection.execute(
            text(
                "SELECT document_id, extracted_text FROM private_documents "
                "WHERE document_id = :id"
            ),
            {"id": immutable_fields["document_id"]},
        ).mappings().one()
    assert downgraded["document_id"] == immutable_fields["document_id"]
    assert downgraded["extracted_text"] == ""
    engine.dispose()
