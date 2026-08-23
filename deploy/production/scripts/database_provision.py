"""Provision one least-privilege application role/database using bootstrap only."""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
from psycopg import sql

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing {name}")
    return value


def secret(name: str) -> str:
    path = Path(required(name))
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"invalid {name}")
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not value:
        raise SystemExit(f"empty {name}")
    return value


host = required("DATABASE_HOST")
bootstrap_user = required("DATABASE_BOOTSTRAP_USER")
target_db = required("TARGET_DATABASE_NAME")
target_user = required("TARGET_DATABASE_USER")
protected_db = os.environ.get("PROTECTED_DATABASE_NAME", "")
protected_user = os.environ.get("PROTECTED_DATABASE_USER", "")
if bool(protected_db) != bool(protected_user):
    raise SystemExit("protected database and user must be configured together")
for label, value in (
    ("bootstrap user", bootstrap_user),
    ("target database", target_db),
    ("target user", target_user),
    ("protected database", protected_db),
    ("protected user", protected_user),
):
    if value and not IDENTIFIER.fullmatch(value):
        raise SystemExit(f"invalid {label}")
if target_user == bootstrap_user or target_user == protected_user:
    raise SystemExit("application and bootstrap/protected identities must differ")
if protected_db and target_db == protected_db:
    raise SystemExit("target and protected databases must differ")

with psycopg.connect(
    host=host,
    dbname="postgres",
    user=bootstrap_user,
    password=secret("DATABASE_BOOTSTRAP_PASSWORD_FILE"),
    autocommit=True,
) as connection:
    target_password = secret("TARGET_DATABASE_PASSWORD_FILE")
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (target_user,))
        action = "CREATE" if cursor.fetchone() is None else "ALTER"
        cursor.execute(
            sql.SQL(
                "{} ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION"
            ).format(
                sql.SQL(action),
                sql.Identifier(target_user),
                sql.Literal(target_password),
            )
        )
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(target_db),
                    sql.Identifier(target_user),
                )
            )
        cursor.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(target_db)
            )
        )
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                sql.Identifier(target_db),
                sql.Identifier(target_user),
                sql.Identifier(bootstrap_user),
            )
        )
        if protected_user:
            cursor.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                    sql.Identifier(target_db),
                    sql.Identifier(protected_user),
                )
            )
        if protected_db:
            cursor.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(protected_db)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                    sql.Identifier(protected_db),
                    sql.Identifier(target_user),
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                    sql.Identifier(protected_db),
                    sql.Identifier(protected_user),
                    sql.Identifier(bootstrap_user),
                )
            )

with psycopg.connect(
    host=host,
    dbname=target_db,
    user=bootstrap_user,
    password=secret("DATABASE_BOOTSTRAP_PASSWORD_FILE"),
    autocommit=True,
) as target_connection:
    with target_connection.cursor() as cursor:
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cursor.execute(
            sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                sql.Identifier(target_user)
            )
        )
        for object_kind in ("TABLES", "SEQUENCES", "FUNCTIONS", "TYPES"):
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE {} "
                    "REVOKE ALL ON {} FROM PUBLIC"
                ).format(
                    sql.Identifier(target_user),
                    sql.SQL(object_kind),
                )
            )
print("application database isolation converged")
