#!/usr/bin/env python3
"""只读检查 SQLite 是否具备 A3 访谈列，不输出业务数据。"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REQUIRED_COLUMNS = {
    "session_id",
    "student_id",
    "messages",
    "portrait",
    "status",
    "current_question_id",
    "answered_dimensions",
    "profile_version",
    "confirmed_at",
    "created_at",
    "updated_at",
}
A2_ADVISOR_COLUMNS = {
    "provenance",
    "governance",
    "quarantined_fields",
    "review_status",
    "publication_status",
    "authorization_basis",
    "record_created_at",
    "record_updated_at",
}
A2_RECRUITMENT_COLUMNS = {
    "provenance",
    "governance",
    "quarantined_fields",
    "review_status",
    "publication_status",
    "authorization_basis",
    "updated_at",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    args = parser.parse_args()

    database = Path(args.database)
    if not database.is_file():
        print(f"FAIL: database not found: {database}")
        return 1

    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(questionnaire_sessions)"
            )
        }
        advisor_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(advisors)")
        }
        recruitment_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(recruitments)")
        }
        version_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        revision = (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if version_table
            else None
        )
        session_rows = connection.execute(
            "SELECT COUNT(*) FROM questionnaire_sessions"
        ).fetchone()[0]
    finally:
        connection.close()

    missing = sorted(REQUIRED_COLUMNS - columns)
    has_a2 = (
        A2_ADVISOR_COLUMNS <= advisor_columns
        and A2_RECRUITMENT_COLUMNS <= recruitment_columns
    )
    detected_baseline = "0002" if has_a2 else "0001"
    if missing:
        print(
            "FAIL: questionnaire_sessions missing="
            f"{','.join(missing)} alembic_revision={revision[0] if revision else 'none'} "
            f"detected_baseline={detected_baseline} session_rows={session_rows}"
        )
        return 1
    print(
        "PASS: questionnaire_sessions A3 columns present "
        f"alembic_revision={revision[0] if revision else 'create_all'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
