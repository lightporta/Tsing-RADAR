"""Run Alembic under a PostgreSQL session advisory lock."""

from __future__ import annotations

import os
import subprocess
import time

from app.core.config import Settings

LOCK_ID = 0x5453494E47524144  # stable signed-64-safe deployment lock key
LOCK_BUSY_EXIT = 75
MIGRATION_FAILED_EXIT = 70


def acquire_deployment_lock(connection, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
            acquired = cursor.fetchone()
        if acquired and acquired[0] is True:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def release_deployment_lock(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def main() -> int:
    import psycopg

    try:
        timeout = float(os.environ.get("MIGRATION_LOCK_TIMEOUT_SECONDS", "5"))
    except ValueError:
        print("migration lock timeout invalid", flush=True)
        return MIGRATION_FAILED_EXIT
    if timeout < 0 or timeout > 300:
        print("migration lock timeout outside allowed range", flush=True)
        return MIGRATION_FAILED_EXIT

    configured = Settings()
    connection = None
    acquired = False
    try:
        connection = psycopg.connect(configured.DATABASE_URL, autocommit=True)
        acquired = acquire_deployment_lock(connection, timeout)
        if not acquired:
            print("migration lock busy", flush=True)
            return LOCK_BUSY_EXIT
        completed = subprocess.run(
            ["alembic", "upgrade", "head"],
            check=False,
        )
        if completed.returncode:
            print("alembic migration failed", flush=True)
            return MIGRATION_FAILED_EXIT
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"migration failed closed: {type(exc).__name__}", flush=True)
        return MIGRATION_FAILED_EXIT
    finally:
        if connection is not None:
            try:
                if acquired:
                    release_deployment_lock(connection)
            finally:
                connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
