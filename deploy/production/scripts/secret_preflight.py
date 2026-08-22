"""Validate deployment secret files without printing values or fingerprints."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

MAX_SECRET_BYTES = 64 * 1024
PLACEHOLDERS = {"admin", "secret", "changeme", "change-me"}

PROD_FILES = (
    "database_password",
    "redis_password",
    "admin_token",
    "session_hmac_secret",
    "artifact_signing_secret",
    "llm_api_key",
    "mail_password",
    "cos_access_key_id",
    "cos_secret_access_key",
    "restore_check_password",
)
PROD_SECRET_MATERIAL = (
    "database_password",
    "redis_password",
    "admin_token",
    "session_hmac_secret",
    "artifact_signing_secret",
    "llm_api_key",
    "mail_password",
    "cos_secret_access_key",
    "restore_check_password",
)
QXD_FILES = ("qxd_api_key", "qxd_end_user_signing_secret")
STAGE_FILES = (
    "database_password",
    "redis_password",
    "admin_token",
    "session_hmac_secret",
    "artifact_signing_secret",
    "cos_access_key_id",
    "cos_secret_access_key",
)
STAGE_SECRET_MATERIAL = tuple(
    name for name in STAGE_FILES if name != "cos_access_key_id"
)
BOOTSTRAP_FILES = ("database_bootstrap_password",)


def _read_restricted(root: Path, name: str) -> tuple[str | None, str]:
    path = root / name
    try:
        metadata = path.lstat()
    except OSError:
        return None, "missing"
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        return None, "not_regular"
    if os.name == "posix" and metadata.st_mode & 0o077:
        return None, "permissions"
    if metadata.st_size <= 0 or metadata.st_size > MAX_SECRET_BYTES:
        return None, "size"
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        return None, "unreadable"
    if not value or "\x00" in value:
        return None, "invalid"
    return value, "ok"


def _is_strong(value: str) -> bool:
    return (
        len(value.encode("utf-8")) >= 32
        and value.lower() not in PLACEHOLDERS
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def validate_roots(
    prod_root: Path,
    stage_root: Path,
    bootstrap_root: Path,
) -> dict[str, object]:
    roots = {
        "prod": (prod_root, PROD_FILES),
        "stage": (stage_root, STAGE_FILES),
        "bootstrap": (bootstrap_root, BOOTSTRAP_FILES),
    }
    qxd_presence = tuple((prod_root / name).exists() for name in QXD_FILES)
    if any(qxd_presence):
        roots["qxd"] = (prod_root, QXD_FILES)

    values: dict[str, str] = {}
    checks: list[dict[str, object]] = []
    for scope, (root, names) in roots.items():
        if not root.is_absolute():
            checks.append(
                {"label": f"{scope}.root", "passed": False, "reason": "relative"}
            )
            continue
        if scope == "qxd" and not all(qxd_presence):
            checks.append(
                {"label": "qxd.pair", "passed": False, "reason": "incomplete"}
            )
        for name in names:
            value, reason = _read_restricted(root, name)
            checks.append(
                {
                    "label": f"{scope}.{name}.file",
                    "passed": reason == "ok",
                    "reason": reason,
                }
            )
            if value is not None:
                values[f"{scope}.{name}"] = value

    strong_labels = {
        *(f"prod.{name}" for name in PROD_SECRET_MATERIAL),
        *(f"stage.{name}" for name in STAGE_SECRET_MATERIAL),
        "bootstrap.database_bootstrap_password",
    }
    if any(qxd_presence):
        strong_labels.update(f"qxd.{name}" for name in QXD_FILES)
    for label in sorted(strong_labels):
        value = values.get(label)
        checks.append(
            {
                "label": f"{label}.strength",
                "passed": value is not None and _is_strong(value),
                "reason": "ok" if value is not None and _is_strong(value) else "weak",
            }
        )

    material = [values[label] for label in strong_labels if label in values]
    checks.append(
        {
            "label": "all.secret_material.purpose_isolation",
            "passed": len(material) == len(strong_labels)
            and len(material) == len(set(material)),
            "reason": "ok"
            if len(material) == len(strong_labels)
            and len(material) == len(set(material))
            else "reused_or_missing",
        }
    )
    failed = [item["label"] for item in checks if not item["passed"]]
    return {
        "schema_version": "l1-secret-preflight-v1",
        "status": "passed" if not failed else "failed",
        "values_or_hashes_emitted": False,
        "checks": checks,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-root", required=True, type=Path)
    parser.add_argument("--stage-secret-root", required=True, type=Path)
    parser.add_argument("--bootstrap-secret-root", required=True, type=Path)
    args = parser.parse_args()
    report = validate_roots(
        args.secret_root.resolve(),
        args.stage_secret_root.resolve(),
        args.bootstrap_secret_root.resolve(),
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
