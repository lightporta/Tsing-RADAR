"""Verify an interrupted first deployment can safely resume after migration."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

from app import models  # noqa: F401 - populate SQLAlchemy metadata
from app.core.config import Settings
from app.db.base import Base
from migration_with_lock import psycopg_connect_kwargs

VERIFICATION_FAILED_EXIT = 70


def expected_alembic_heads(config_path: str = "/app/alembic.ini") -> set[str]:
    configuration = Config(config_path)
    return set(ScriptDirectory.from_config(configuration).get_heads())


def expected_business_tables() -> set[str]:
    return {table.name for table in Base.metadata.sorted_tables}


def verify_post_migration_state(connection, *, expected_heads: set[str]) -> None:
    """Require the exact current schema and zero rows in every business table."""

    expected_tables = expected_business_tables()
    if len(expected_heads) != 1 or not expected_tables:
        raise ValueError("post-migration source contract invalid")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
        actual_tables = {row[0] for row in cursor.fetchall()}
        if actual_tables != expected_tables | {"alembic_version"}:
            raise ValueError("post-migration table contract invalid")

        cursor.execute("SELECT version_num FROM alembic_version")
        actual_heads = {row[0] for row in cursor.fetchall()}
        if actual_heads != expected_heads:
            raise ValueError("post-migration revision contract invalid")

        for table_name in sorted(expected_tables):
            cursor.execute(
                sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
                    sql.Identifier(table_name)
                )
            )
            if cursor.fetchone()[0]:
                raise ValueError("post-migration business data is not empty")


def main() -> int:
    import psycopg

    connection = None
    try:
        configured = Settings()
        connection = psycopg.connect(
            **psycopg_connect_kwargs(configured.DATABASE_URL),
            autocommit=True,
        )
        verify_post_migration_state(
            connection,
            expected_heads=expected_alembic_heads(),
        )
        print("post-migration verification passed", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - never expose DSN, table or row data
        print(
            f"post-migration verification failed closed: {type(exc).__name__}",
            flush=True,
        )
        return VERIFICATION_FAILED_EXIT
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
