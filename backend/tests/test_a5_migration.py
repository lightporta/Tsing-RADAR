"""A6 Alembic 迁移可从空库升级，并可在 0004/0006 间往返。"""

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
    }.issubset(inspector.get_table_names())
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
    assert revision == "0006"
    engine.dispose()
