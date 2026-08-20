"""Local liveness/readiness checks that never call external services."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text

from app.db.session import engine
from app.services.data_loader import mentor_data_summary

_REQUIRED_TABLES = {
    "identity_sessions",
    "questionnaire_sessions",
    "private_documents",
    "idempotency_records",
    "artifact_audit_events",
}


def local_readiness() -> dict[str, Any]:
    """Check only in-process data and the configured database connection."""
    checks: dict[str, bool] = {
        "database_query": False,
        "database_schema": False,
        "mentor_governance_dataset": False,
    }
    reason_codes: list[str] = []
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database_query"] = True
    except Exception:  # noqa: BLE001 - response must not expose driver details
        reason_codes.append("database_query_failed")

    try:
        tables = set(inspect(engine).get_table_names())
        checks["database_schema"] = _REQUIRED_TABLES.issubset(tables)
        if not checks["database_schema"]:
            reason_codes.append("database_schema_incomplete")
    except Exception:  # noqa: BLE001
        reason_codes.append("database_schema_check_failed")

    try:
        summary = mentor_data_summary()
        checks["mentor_governance_dataset"] = (
            int(summary["total_records"]) >= 0
            and int(summary["published_records"]) >= 0
            and int(summary["withheld_records"]) >= 0
        )
        if not checks["mentor_governance_dataset"]:
            reason_codes.append("mentor_governance_dataset_invalid")
    except Exception:  # noqa: BLE001
        reason_codes.append("mentor_governance_dataset_invalid")

    ready = all(checks.values())
    return {
        "status": "ready" if ready else "not_ready",
        "scope": "local_dependencies_only",
        "checks": checks,
        "reason_codes": sorted(set(reason_codes)),
        "external_dependencies_probed": False,
    }
