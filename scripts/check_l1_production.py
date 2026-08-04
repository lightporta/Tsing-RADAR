"""Offline L1 production artifact checker.

The checker creates unique dummy files in a temporary directory. It never
reads real deployment secret directories and never prints values or hashes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "production"
INFRA = DEPLOY / "compose.infra.yml"
PROD = DEPLOY / "compose.prod.yml"
EDGE = DEPLOY / "compose.edge.yml"
QXD = DEPLOY / "compose.qxd.yml"
MEDIA = DEPLOY / "compose.media.yml"
STAGE = DEPLOY / "compose.stage.yml"
JOBS = DEPLOY / "compose.jobs.yml"
EMPTY_MENTOR_SEED = DEPLOY / "data" / "empty-mentor-governance.json"

HOST_MEMORY_MIB = 7578
DEFAULT_RESOLVED_LIMIT_MIB = 5184
PUBLIC_EDGE_BUDGET_MIB = 128
DEFAULT_CAPACITY_BUDGET_MIB = 5312
EDGE_PLANNING_HEADROOM_MIB = HOST_MEMORY_MIB - DEFAULT_CAPACITY_BUDGET_MIB
MIN_SUPPORTED_COMBINATION_HEADROOM_MIB = 1280

SECRET_NAMES = (
    "database_password",
    "redis_password",
    "milvus_minio_access_key",
    "milvus_minio_secret_key",
    "admin_token",
    "session_hmac_secret",
    "artifact_signing_secret",
    "cos_access_key_id",
    "cos_secret_access_key",
    "restore_check_password",
    "qxd_api_key",
    "qxd_end_user_signing_secret",
)
STAGE_SECRET_NAMES = (
    "database_password",
    "redis_password",
    "admin_token",
    "session_hmac_secret",
    "artifact_signing_secret",
    "cos_access_key_id",
    "cos_secret_access_key",
)
BOOTSTRAP_SECRET_NAMES = ("database_bootstrap_password",)
MUTATIONS = (
    "missing-secret",
    "secret-reuse",
    "stage-namespace-reuse",
    "debug-enabled",
    "trial-enabled",
    "cos-http",
    "cos-path-style",
    "sse-disabled",
    "nonedge-port",
    "half-qxd",
    "half-media",
    "weak-qxd-secret",
    "qxd-secret-reuse",
    "resource-overcommit",
)
EXPECTED_DEFAULT_SERVICES = {
    "postgres",
    "redis",
    "etcd",
    "milvus-minio",
    "milvus",
    "clamav",
    "backend",
    "frontend",
}
RESOURCE_COMBINATIONS = (
    "default",
    "edge",
    "qxd",
    "media",
    "database-setup",
    "migration",
    "backup",
    "restore-check",
    "stage-only",
    "prod-stage",
    "stage-backup",
    "backup-restore",
)


def _check(check_id: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "detail": "ok" if passed else detail,
    }


def _compose(
    files: list[Path],
    environment: dict[str, str],
    *,
    profiles: tuple[str, ...] = (),
) -> dict[str, Any]:
    command = ["docker", "compose"]
    for path in files:
        command.extend(("-f", str(path)))
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(("config", "--format", "json"))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("compose configuration failed without exposing output")
    return json.loads(completed.stdout)


def _memory_mib(service: dict[str, Any]) -> int:
    value = service.get("mem_limit")
    if isinstance(value, int) and value >= 0 and value % (1024 * 1024) == 0:
        return value // (1024 * 1024)
    if isinstance(value, str):
        if value.isdigit() and int(value) % (1024 * 1024) == 0:
            return int(value) // (1024 * 1024)
        matched = re.fullmatch(r"([0-9]+)([mMgG])", value)
        if matched:
            amount = int(matched.group(1))
            return amount * (1024 if matched.group(2).lower() == "g" else 1)
    raise ValueError(f"invalid service memory limit shape: {type(value).__name__}:{value!r}")


def _environment(service: dict[str, Any]) -> dict[str, str]:
    value = service.get("environment", {})
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    raise ValueError("unexpected Compose environment shape")


def _secret_bind_contract(
    service: dict[str, Any],
    expected: dict[str, Path],
) -> bool:
    """Validate exact read-only bind mounts for all /run/secrets targets."""

    if service.get("secrets"):
        return False
    entries = service.get("volumes", [])
    if not isinstance(entries, list):
        return False
    found: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", ""))
        if not target.startswith("/run/secrets/"):
            continue
        if target in found:
            return False
        found[target] = item
    if set(found) != set(expected):
        return False
    for target, source_path in expected.items():
        item = found[target]
        bind = item.get("bind", {})
        if (
            item.get("type") != "bind"
            or item.get("read_only") is not True
            or not isinstance(bind, dict)
            or bind.get("create_host_path") is not False
        ):
            return False
        try:
            actual_source = Path(str(item.get("source", ""))).resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False
        if actual_source != source_path.resolve(strict=False):
            return False
    return True


def _migration_import_contract(service: dict[str, Any]) -> bool:
    """Require the out-of-WORKDIR migration wrapper to import /app/app."""

    alembic_mounts = [
        item
        for item in service.get("volumes", [])
        if isinstance(item, dict) and item.get("target") == "/app/alembic/env.py"
    ]
    return (
        service.get("command")
        == ["python", "/opt/tsing-radar/migration_with_lock.py"]
        and _environment(service).get("PYTHONPATH") == "/app"
        and len(alembic_mounts) == 1
        and alembic_mounts[0].get("type") == "bind"
        and alembic_mounts[0].get("read_only") is True
        and alembic_mounts[0].get("bind", {}).get("create_host_path") is False
        and Path(str(alembic_mounts[0].get("source", ""))).resolve(strict=False)
        == (ROOT / "backend" / "alembic" / "env.py").resolve(strict=False)
    )


def _empty_mentor_seed_contract(service: dict[str, Any]) -> bool:
    """Require the reviewed empty seed at the image's fixed governance path."""

    try:
        payload = json.loads(EMPTY_MENTOR_SEED.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    source = payload.get("source") if isinstance(payload, dict) else None
    if (
        not isinstance(source, dict)
        or set(payload) != {"schema_version", "generated_at", "source", "records"}
        or payload.get("schema_version") != "2.0"
        or payload.get("records") != []
        or source.get("source_type") != "legacy_seed"
        or source.get("content_sha256")
        != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        or source.get("original_record_count") != 0
        or source.get("raw_retained") is not False
    ):
        return False
    mounts = [
        item
        for item in service.get("volumes", [])
        if isinstance(item, dict)
        and item.get("target") == "/app/data/mentors.evidence.json"
    ]
    if len(mounts) != 1:
        return False
    mount = mounts[0]
    return (
        mount.get("type") == "bind"
        and mount.get("read_only") is True
        and mount.get("bind", {}).get("create_host_path") is False
        and Path(str(mount.get("source", ""))).resolve(strict=False)
        == EMPTY_MENTOR_SEED.resolve(strict=False)
    )


def _post_migration_verification_contract(service: dict[str, Any]) -> bool:
    mounts = {
        str(item.get("target")): item
        for item in service.get("volumes", [])
        if isinstance(item, dict)
    }
    expected_scripts = {
        "/opt/tsing-radar/post_migration_verify.py": DEPLOY
        / "scripts"
        / "post_migration_verify.py",
        "/opt/tsing-radar/migration_with_lock.py": DEPLOY
        / "scripts"
        / "migration_with_lock.py",
    }
    scripts_ok = True
    for target, source in expected_scripts.items():
        item = mounts.get(target, {})
        scripts_ok = scripts_ok and (
            item.get("type") == "bind"
            and item.get("read_only") is True
            and Path(str(item.get("source", ""))).resolve(strict=False)
            == source.resolve(strict=False)
        )
    return (
        service.get("command")
        == ["python", "/opt/tsing-radar/post_migration_verify.py"]
        and service.get("restart") == "no"
        and not service.get("ports")
        and _environment(service).get("PYTHONPATH") == "/app:/opt/tsing-radar"
        and scripts_ok
    )


def _secret_is_strong(value: str) -> bool:
    placeholders = {"admin", "secret", "changeme", "change-me"}
    return (
        len(value.encode("utf-8")) >= 32
        and value.lower() not in placeholders
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def run_checks(
    mutation: str | None = None,
    require_combination: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    resource_matrix: list[dict[str, Any]] = []
    digest = "sha256:" + "a" * 64
    dummy_values: list[str] = []
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l1-") as temp:
        temp_root = Path(temp)
        prod_secrets = temp_root / "prod"
        stage_secrets = temp_root / "stage"
        bootstrap_secrets = temp_root / "bootstrap"
        prod_secrets.mkdir()
        stage_secrets.mkdir()
        bootstrap_secrets.mkdir()
        job_lock_file = temp_root / "job.lock"
        job_lock_file.touch()
        for index, name in enumerate(SECRET_NAMES):
            value = f"dummy-prod-{index:02d}-" + "x" * 40
            (prod_secrets / name).write_text(value, encoding="utf-8")
            dummy_values.append(value)
        for index, name in enumerate(STAGE_SECRET_NAMES):
            value = f"dummy-stage-{index:02d}-" + "y" * 40
            (stage_secrets / name).write_text(value, encoding="utf-8")
            dummy_values.append(value)
        for index, name in enumerate(BOOTSTRAP_SECRET_NAMES):
            value = f"dummy-bootstrap-{index:02d}-" + "z" * 40
            (bootstrap_secrets / name).write_text(value, encoding="utf-8")
            dummy_values.append(value)

        if mutation == "missing-secret":
            (prod_secrets / "admin_token").unlink()
        elif mutation == "secret-reuse":
            (stage_secrets / "admin_token").write_text(
                (prod_secrets / "admin_token").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        elif mutation == "weak-qxd-secret":
            (prod_secrets / "qxd_api_key").write_text("short", encoding="utf-8")
        elif mutation == "qxd-secret-reuse":
            (prod_secrets / "qxd_api_key").write_text(
                (prod_secrets / "session_hmac_secret").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        environment = os.environ.copy()
        environment.update(
            {
                "COMPOSE_PROJECT_NAME": "tsing-radar-l1-check",
                "SECRET_ROOT": str(prod_secrets),
                "STAGE_SECRET_ROOT": str(stage_secrets),
                "BOOTSTRAP_SECRET_ROOT": str(bootstrap_secrets),
                "POSTGRES_IMAGE": f"postgres@{digest}",
                "REDIS_IMAGE": f"redis@{digest}",
                "ETCD_IMAGE": f"etcd@{digest}",
                "MINIO_IMAGE": f"minio@{digest}",
                "MILVUS_IMAGE": f"milvus@{digest}",
                "CLAMAV_IMAGE": f"clamav@{digest}",
                "BACKEND_IMAGE": f"backend@{digest}",
                "FRONTEND_IMAGE": f"frontend@{digest}",
                "CADDY_IMAGE": f"caddy@{digest}",
                "NGINX_UNPRIVILEGED_IMAGE": f"nginx@{digest}",
                "PROD_DATABASE_NAME": "tsing_radar_prod",
                "PROD_DATABASE_USER": "tsing_radar_prod",
                "DATABASE_BOOTSTRAP_USER": "tsing_radar_bootstrap",
                "MILVUS_BUCKET": "tsing-radar-milvus",
                "PROD_COS_BUCKET": "tsing-radar-prod-1250000000",
                "PROD_CORS_ORIGINS": "https://radar.invalid",
                "STAGE_DATABASE_NAME": "tsing_radar_stage",
                "STAGE_DATABASE_USER": "tsing_radar_stage",
                "STAGE_COS_BUCKET": "tsing-radar-stage-1250000000",
                "STAGE_CORS_ORIGINS": "https://stage.invalid",
                "WEB_HOST": "radar.invalid",
                "QXD_HOST": "qxd.invalid",
                "MEDIA_HOST": "media.invalid",
                "BACKUP_FILE": "verified-backup.dump",
                "JOB_LOCK_FILE": str(job_lock_file),
                "JOB_LOCK_GID": "10002",
            }
        )

        if mutation == "stage-namespace-reuse":
            environment["STAGE_DATABASE_NAME"] = environment["PROD_DATABASE_NAME"]
            environment["STAGE_COS_BUCKET"] = environment["PROD_COS_BUCKET"]

        mutation_overlay = temp_root / "mutation.yml"
        mutation_environment: dict[str, str] = {}
        if mutation == "debug-enabled":
            mutation_environment["DEBUG"] = "true"
        elif mutation == "trial-enabled":
            mutation_environment["QXD_TRIAL_SINGLE_USER_MODE"] = "true"
        elif mutation == "cos-http":
            mutation_environment["S3_ENDPOINT_URL"] = "http://cos.ap-shanghai.myqcloud.com"
        elif mutation == "cos-path-style":
            mutation_environment["S3_ADDRESSING_STYLE"] = "path"
        elif mutation == "sse-disabled":
            mutation_environment["S3_SERVER_SIDE_ENCRYPTION"] = "none"
        elif mutation == "half-qxd":
            mutation_environment["QXD_API_KEY_FILE"] = "/run/secrets/qxd_api_key"
        elif mutation == "half-media":
            mutation_environment["QXD_ATTACHMENTS_ENABLED"] = "true"
            mutation_environment["PUBLIC_BASE_URL"] = "https://media.invalid"
        elif mutation == "resource-overcommit":
            pass
        if mutation_environment or mutation in {"nonedge-port", "resource-overcommit"}:
            lines = ["services:", "  backend:"]
            if mutation_environment:
                lines.append("    environment:")
                lines.extend(
                    f'      {key}: "{value}"'
                    for key, value in mutation_environment.items()
                )
            if mutation == "nonedge-port":
                lines.extend(("    ports:", '      - "127.0.0.1:18000:8000"'))
            if mutation == "resource-overcommit":
                lines.append("    mem_limit: 3072m")
            mutation_overlay.write_text("\n".join(lines) + "\n", encoding="utf-8")

        default_files = [INFRA, PROD]
        if mutation_overlay.is_file():
            default_files.append(mutation_overlay)
        default = _compose(default_files, environment)
        default_services = default.get("services", {})
        backend_environment = _environment(default_services["backend"])
        checks.append(
            _check(
                "compose.default_services_exact",
                set(default_services) == EXPECTED_DEFAULT_SERVICES,
                "default service set changed",
            )
        )
        checks.append(
            _check(
                "compose.default_has_no_host_ports",
                all(not service.get("ports") for service in default_services.values()),
                "default composition publishes a host port",
            )
        )
        checks.append(
            _check(
                "compose.production_flags_fail_closed",
                backend_environment.get("DEBUG") == "false"
                and backend_environment.get("QXD_TRIAL_SINGLE_USER_MODE")
                == "false",
                "DEBUG or trial compatibility mode enabled",
            )
        )
        checks.append(
            _check(
                "mentor.empty_governance_seed_mounted_fail_closed",
                _empty_mentor_seed_contract(default_services["backend"]),
                "backend lacks the exact tracked zero-record governance seed bind",
            )
        )
        resolved_memory = sum(
            _memory_mib(service) for service in default_services.values()
        )
        checks.append(
            _check(
                "resources.default_resolved_5184_mib",
                resolved_memory == DEFAULT_RESOLVED_LIMIT_MIB,
                "default resolved memory total differs",
            )
        )
        checks.append(
            _check(
                "resources.capacity_budget_5312_mib",
                resolved_memory + PUBLIC_EDGE_BUDGET_MIB
                == DEFAULT_CAPACITY_BUDGET_MIB
                and EDGE_PLANNING_HEADROOM_MIB == 2266,
                "capacity or headroom arithmetic differs",
            )
        )
        checks.append(
            _check(
                "cos.sdk_endpoint_bucket_free",
                backend_environment.get("S3_ENDPOINT_URL")
                == "https://cos.ap-shanghai.myqcloud.com"
                and backend_environment.get("S3_ADDRESSING_STYLE") == "virtual"
                and backend_environment.get("S3_SERVER_SIDE_ENCRYPTION")
                == "AES256"
                and backend_environment.get("S3_PROVIDER") == "tencent_cos"
                and backend_environment.get("S3_BUCKET")
                == "tsing-radar-prod-1250000000",
                "COS endpoint, bucket or virtual style differs",
            )
        )
        checks.append(
            _check(
                "compose.default_qxd_media_absent",
                not ({"edge", "qxd-gateway", "media-gateway"} & set(default_services))
                and not backend_environment.get("QXD_API_KEY_FILE")
                and backend_environment.get("PUBLIC_BASE_URL", "") == "",
                "optional public surface leaked into default",
            )
        )

        stage = _compose(
            [INFRA, PROD, STAGE],
            environment,
            profiles=("stage",),
        )
        stage_services = stage["services"]
        stage_backend = stage_services["stage-backend"]
        stage_environment = _environment(stage_backend)
        stage_networks = set(stage_backend.get("networks", {}))
        prod_backend_networks = set(stage_services["backend"].get("networks", {}))
        scanner_networks = set(stage_services["clamav"].get("networks", {}))
        checks.append(
            _check(
                "isolation.stage_has_no_prod_app_or_milvus",
                "prod-app" not in stage_networks
                and "prod-data" not in stage_networks
                and "vector-data" not in stage_networks
                and "MILVUS_HOST" not in stage_environment
                and "stage-app" not in prod_backend_networks
                and stage_networks & scanner_networks == {"scanner-shared"},
                "stage and prod application/vector networks overlap",
            )
        )
        checks.append(
            _check(
                "isolation.stage_credentials_and_cos_distinct",
                stage_environment.get("DATABASE_NAME") == "tsing_radar_stage"
                and stage_environment.get("S3_BUCKET")
                == "tsing-radar-stage-1250000000"
                and stage_environment.get("S3_BUCKET")
                != backend_environment.get("S3_BUCKET")
                and "stage-redis" in stage_services,
                "stage data services are not distinct",
            )
        )

        all_secret_paths = [
            *(prod_secrets / name for name in SECRET_NAMES),
            *(stage_secrets / name for name in STAGE_SECRET_NAMES),
            *(bootstrap_secrets / name for name in BOOTSTRAP_SECRET_NAMES),
        ]
        checks.append(
            _check(
                "secrets.all_required_files_exist",
                all(path.is_file() for path in all_secret_paths),
                "a required secret file is missing",
            )
        )
        existing_secret_values = [
            path.read_text(encoding="utf-8")
            for path in all_secret_paths
            if path.is_file()
        ]
        checks.append(
            _check(
                "secrets.prod_stage_bootstrap_independent",
                len(existing_secret_values) == len(set(existing_secret_values))
                and environment["DATABASE_BOOTSTRAP_USER"]
                not in {
                    environment["PROD_DATABASE_USER"],
                    environment["STAGE_DATABASE_USER"],
                },
                "secret material or database identities are reused",
            )
        )
        secret_material_paths = [
            prod_secrets / name
            for name in (
                "database_password",
                "redis_password",
                "milvus_minio_secret_key",
                "admin_token",
                "session_hmac_secret",
                "artifact_signing_secret",
                "cos_secret_access_key",
                "restore_check_password",
                "qxd_api_key",
                "qxd_end_user_signing_secret",
            )
        ] + [
            stage_secrets / name
            for name in (
                "database_password",
                "redis_password",
                "admin_token",
                "session_hmac_secret",
                "artifact_signing_secret",
                "cos_secret_access_key",
            )
        ] + [bootstrap_secrets / "database_bootstrap_password"]
        secret_material = [
            path.read_text(encoding="utf-8")
            for path in secret_material_paths
            if path.is_file()
        ]
        checks.append(
            _check(
                "secrets.strong_and_purpose_isolated",
                len(secret_material) == len(secret_material_paths)
                and all(_secret_is_strong(value) for value in secret_material)
                and len(secret_material) == len(set(secret_material)),
                "a password/key is weak, placeholder, missing or reused",
            )
        )
        backend_secret_mounts = json.dumps(
            default_services["backend"].get("volumes", []),
            sort_keys=True,
        )
        checks.append(
            _check(
                "secrets.bootstrap_not_mounted_to_runtime",
                "bootstrap" not in backend_secret_mounts
                and "DATABASE_BOOTSTRAP" not in json.dumps(backend_environment),
                "bootstrap credential reached the production backend",
            )
        )
        checks.append(
            _check(
                "secrets.backend_explicit_bind_contract",
                default_services["backend"].get("user") == "10001:10001"
                and _secret_bind_contract(
                    default_services["backend"],
                    {
                        "/run/secrets/database_password": prod_secrets
                        / "database_password",
                        "/run/secrets/redis_password": prod_secrets / "redis_password",
                        "/run/secrets/admin_token": prod_secrets / "admin_token",
                        "/run/secrets/session_hmac_secret": prod_secrets
                        / "session_hmac_secret",
                        "/run/secrets/artifact_signing_secret": prod_secrets
                        / "artifact_signing_secret",
                        "/run/secrets/cos_access_key_id": prod_secrets
                        / "cos_access_key_id",
                        "/run/secrets/cos_secret_access_key": prod_secrets
                        / "cos_secret_access_key",
                    },
                ),
                "backend secret bind contract differs",
            )
        )

        edge = _compose(
            [INFRA, PROD, EDGE],
            environment,
        )
        edge_services = edge["services"]
        checks.append(
            _check(
                "edge.atomic_overlay_only",
                "edge" in edge_services
                and "qxd-gateway" not in edge_services
                and "media-gateway" not in edge_services,
                "edge overlay unexpectedly enables another public surface",
            )
        )

        qxd = _compose(
            [INFRA, PROD, EDGE, QXD],
            environment,
        )
        checks.append(
            _check(
                "qxd.optional_overlay_scoped",
                "qxd-gateway" in qxd["services"]
                and "media-gateway" not in qxd["services"]
                and _environment(qxd["services"]["backend"]).get(
                    "QXD_TRIAL_SINGLE_USER_MODE"
                )
                == "false",
                "QXD overlay scope or trial gate differs",
            )
        )
        qxd_backend_environment = _environment(qxd["services"]["backend"])
        checks.append(
            _check(
                "qxd.inbound_media_and_outbound_attachments_disabled",
                qxd_backend_environment.get("QXD_REMOTE_MEDIA_FETCH_ENABLED")
                == "false"
                and qxd_backend_environment.get("QXD_ATTACHMENTS_ENABLED")
                == "false"
                and _secret_bind_contract(
                    qxd["services"]["backend"],
                    {
                        "/run/secrets/database_password": prod_secrets
                        / "database_password",
                        "/run/secrets/redis_password": prod_secrets / "redis_password",
                        "/run/secrets/admin_token": prod_secrets / "admin_token",
                        "/run/secrets/session_hmac_secret": prod_secrets
                        / "session_hmac_secret",
                        "/run/secrets/artifact_signing_secret": prod_secrets
                        / "artifact_signing_secret",
                        "/run/secrets/cos_access_key_id": prod_secrets
                        / "cos_access_key_id",
                        "/run/secrets/cos_secret_access_key": prod_secrets
                        / "cos_secret_access_key",
                        "/run/secrets/qxd_api_key": prod_secrets / "qxd_api_key",
                        "/run/secrets/qxd_end_user_signing_secret": prod_secrets
                        / "qxd_end_user_signing_secret",
                    },
                ),
                "QXD overlay enables media or has a weak secret mount contract",
            )
        )

        media = _compose(
            [INFRA, PROD, EDGE, QXD, MEDIA],
            environment,
        )
        checks.append(
            _check(
                "media.requires_explicit_overlay",
                "media-gateway" in media["services"]
                and _environment(media["services"]["backend"]).get(
                    "QXD_ATTACHMENTS_ENABLED"
                )
                == "true",
                "media overlay did not enable its explicit contract",
            )
        )

        partial_qxd_rejected = False
        partial_media_rejected = False
        try:
            _compose([INFRA, PROD, QXD], environment)
        except RuntimeError:
            partial_qxd_rejected = True
        try:
            _compose([INFRA, PROD, EDGE, MEDIA], environment)
        except RuntimeError:
            partial_media_rejected = True
        checks.append(
            _check(
                "optional_overlays.reject_partial_combinations",
                partial_qxd_rejected and partial_media_rejected,
                "a QXD/media overlay can be half-enabled",
            )
        )

        jobs = _compose([INFRA, PROD, JOBS], environment, profiles=("migration",))
        resume_verification = _compose(
            [INFRA, PROD, JOBS],
            environment,
            profiles=("resume-verification",),
        )
        database_setup = _compose(
            [INFRA, PROD, JOBS], environment, profiles=("database-setup",)
        )
        backup = _compose([INFRA, PROD, JOBS], environment, profiles=("backup",))
        restore = _compose(
            [INFRA, PROD, JOBS], environment, profiles=("restore-check",)
        )
        stage_only = _compose([INFRA, STAGE], environment, profiles=("stage",))
        stage_setup = _compose(
            [INFRA, STAGE], environment, profiles=("stage-setup",)
        )
        prod_stage = stage
        stage_backup = _compose(
            [INFRA, PROD, STAGE, JOBS],
            environment,
            profiles=("stage", "backup"),
        )
        backup_restore = _compose(
            [INFRA, PROD, JOBS],
            environment,
            profiles=("backup", "restore-check"),
        )

        secret_bind_expectations = (
            (
                default["services"]["postgres"],
                {
                    "/run/secrets/database_bootstrap_password": bootstrap_secrets
                    / "database_bootstrap_password",
                },
            ),
            (
                default["services"]["redis"],
                {"/run/secrets/redis_password": prod_secrets / "redis_password"},
            ),
            (
                default["services"]["milvus-minio"],
                {
                    "/run/secrets/milvus_minio_access_key": prod_secrets
                    / "milvus_minio_access_key",
                    "/run/secrets/milvus_minio_secret_key": prod_secrets
                    / "milvus_minio_secret_key",
                },
            ),
            (
                default["services"]["milvus"],
                {
                    "/run/secrets/milvus_minio_access_key": prod_secrets
                    / "milvus_minio_access_key",
                    "/run/secrets/milvus_minio_secret_key": prod_secrets
                    / "milvus_minio_secret_key",
                },
            ),
            (
                database_setup["services"]["prod-db-provision"],
                {
                    "/run/secrets/database_bootstrap_password": bootstrap_secrets
                    / "database_bootstrap_password",
                    "/run/secrets/database_password": prod_secrets
                    / "database_password",
                },
            ),
            (
                jobs["services"]["migration"],
                {
                    "/run/secrets/database_password": prod_secrets
                    / "database_password"
                },
            ),
            (
                resume_verification["services"]["post-migration-verification"],
                {
                    "/run/secrets/database_password": prod_secrets
                    / "database_password"
                },
            ),
            (
                backup["services"]["backup"],
                {
                    "/run/secrets/database_password": prod_secrets
                    / "database_password"
                },
            ),
            (
                restore["services"]["restore-check-db"],
                {
                    "/run/secrets/restore_check_password": prod_secrets
                    / "restore_check_password"
                },
            ),
            (
                restore["services"]["restore-check"],
                {
                    "/run/secrets/restore_check_password": prod_secrets
                    / "restore_check_password"
                },
            ),
            (
                stage_setup["services"]["stage-db-provision"],
                {
                    "/run/secrets/database_bootstrap_password": bootstrap_secrets
                    / "database_bootstrap_password",
                    "/run/secrets/stage_database_password": stage_secrets
                    / "database_password",
                },
            ),
            (
                stage_only["services"]["stage-redis"],
                {"/run/secrets/redis_password": stage_secrets / "redis_password"},
            ),
            (
                stage_only["services"]["stage-backend"],
                {
                    "/run/secrets/database_password": stage_secrets
                    / "database_password",
                    "/run/secrets/redis_password": stage_secrets / "redis_password",
                    "/run/secrets/admin_token": stage_secrets / "admin_token",
                    "/run/secrets/session_hmac_secret": stage_secrets
                    / "session_hmac_secret",
                    "/run/secrets/artifact_signing_secret": stage_secrets
                    / "artifact_signing_secret",
                    "/run/secrets/cos_access_key_id": stage_secrets
                    / "cos_access_key_id",
                    "/run/secrets/cos_secret_access_key": stage_secrets
                    / "cos_secret_access_key",
                },
            ),
        )
        rendered_configurations = (
            default,
            qxd,
            database_setup,
            jobs,
            resume_verification,
            backup,
            restore,
            stage_only,
            stage_setup,
        )
        checks.append(
            _check(
                "secrets.explicit_bind_mounts_all_consumers",
                all(
                    _secret_bind_contract(service, expected)
                    for service, expected in secret_bind_expectations
                )
                and all(
                    "secrets" not in configuration
                    and all(
                        not service.get("secrets")
                        for service in configuration.get("services", {}).values()
                    )
                    for configuration in rendered_configurations
                ),
                "a secret consumer is not an exact read-only no-create bind mount",
            )
        )

        matrix_inputs = (
            ("default", default, True),
            ("edge", edge, True),
            ("qxd", qxd, True),
            ("media", media, True),
            ("database-setup", database_setup, True),
            ("migration", jobs, True),
            ("backup", backup, True),
            ("restore-check", restore, True),
            ("stage-only", stage_only, True),
            ("prod-stage", prod_stage, False),
            ("stage-backup", stage_backup, False),
            ("backup-restore", backup_restore, False),
        )
        for name, configuration, policy_supported in matrix_inputs:
            total_mib = sum(
                _memory_mib(service)
                for service in configuration.get("services", {}).values()
            )
            headroom_mib = HOST_MEMORY_MIB - total_mib
            allowed = (
                policy_supported
                and headroom_mib >= MIN_SUPPORTED_COMBINATION_HEADROOM_MIB
            )
            resource_matrix.append(
                {
                    "name": name,
                    "resolved_limit_mib": total_mib,
                    "non_swap_headroom_mib": headroom_mib,
                    "allowed": allowed,
                    "reason": (
                        "supported"
                        if allowed
                        else (
                            "explicit_concurrency_policy"
                            if not policy_supported
                            else "insufficient_non_swap_headroom"
                        )
                    ),
                }
            )
        matrix_by_name = {item["name"]: item for item in resource_matrix}
        checks.append(
            _check(
                "resources.supported_and_rejected_matrix",
                all(
                    matrix_by_name[name]["allowed"]
                    for name in (
                        "default",
                        "edge",
                        "qxd",
                        "media",
                        "database-setup",
                        "migration",
                        "backup",
                        "restore-check",
                        "stage-only",
                    )
                )
                and all(
                    not matrix_by_name[name]["allowed"]
                    for name in ("prod-stage", "stage-backup", "backup-restore")
                )
                and matrix_by_name["restore-check"]["resolved_limit_mib"]
                == DEFAULT_RESOLVED_LIMIT_MIB + 896,
                "resource matrix or restore-check 896 MiB budget differs",
            )
        )
        if require_combination is not None:
            requested = matrix_by_name[require_combination]
            checks.append(
                _check(
                    "resources.requested_combination_allowed",
                    bool(requested["allowed"]),
                    "requested combination is blocked by resource/concurrency policy",
                )
            )
        checks.append(
            _check(
                "jobs.migration_one_shot",
                jobs["services"]["migration"].get("restart") == "no"
                and not jobs["services"]["migration"].get("ports")
                and _migration_import_contract(jobs["services"]["migration"])
                and _environment(jobs["services"]["migration"]).get(
                    "MIGRATION_LOCK_TIMEOUT_SECONDS"
                )
                == "5",
                "migration is not a locked isolated one-shot with /app import path",
            )
        )
        checks.append(
            _check(
                "jobs.post_migration_resume_verification",
                _post_migration_verification_contract(
                    resume_verification["services"]["post-migration-verification"]
                ),
                "post-migration resume verification job is not fixed and isolated",
            )
        )
        job_lock_mounts = {
            service_name: json.dumps(service.get("volumes", []), sort_keys=True)
            for service_name, service in {
                "prod-db-provision": database_setup["services"]["prod-db-provision"],
                "migration": jobs["services"]["migration"],
                "post-migration-verification": resume_verification["services"][
                    "post-migration-verification"
                ],
                "backup": backup["services"]["backup"],
                "restore-check-db": restore["services"]["restore-check-db"],
                "stage-backend": stage_only["services"]["stage-backend"],
            }.items()
        }
        checks.append(
            _check(
                "jobs.shared_kernel_lock_contract",
                all("job.lock" in mounts for mounts in job_lock_mounts.values())
                and all(
                    "job-lock.sh"
                    in json.dumps(configuration["services"][service_name])
                    for service_name, configuration in (
                        ("prod-db-provision", database_setup),
                        ("migration", jobs),
                        ("post-migration-verification", resume_verification),
                        ("backup", backup),
                        ("restore-check-db", restore),
                        ("stage-backend", stage_only),
                    )
                ),
                "a high-load job/stage path does not hold the shared kernel lock",
            )
        )

        serialized = json.dumps(
            {
                "default": default,
                "stage": stage,
                "edge": edge,
                "qxd": qxd,
                "media": media,
                "jobs": jobs,
                "database_setup": database_setup,
                "backup": backup,
                "restore": restore,
                "stage_only": stage_only,
                "stage_setup": stage_setup,
            },
            sort_keys=True,
        )
        checks.append(
            _check(
                "secrets.material_not_rendered",
                all(value not in serialized for value in dummy_values),
                "dummy secret material appeared in rendered configuration",
            )
        )
        checks.append(
            _check(
                "images.immutable_digests",
                all(
                    re.search(r"@sha256:[a-f0-9]{64}$", service.get("image", ""))
                    for configuration in (default, edge, qxd, media, jobs)
                    for service in configuration.get("services", {}).values()
                    if service.get("image")
                ),
                "a resolved image is not digest pinned",
            )
        )

    edge_base = (DEPLOY / "edge" / "Caddyfile").read_text(encoding="utf-8")
    web_routes = (DEPLOY / "edge" / "routes" / "web-api.caddy").read_text(
        encoding="utf-8"
    )
    edge_compose = EDGE.read_text(encoding="utf-8")
    checks.append(
        _check(
            "edge.default_route_mount_allowlist",
            "admin off" in edge_base
            and "web-api.caddy" in edge_compose
            and "qxd.caddy" not in edge_compose
            and "media.caddy" not in edge_compose
            and "path /api/*" not in web_routes
            and (DEPLOY / "edge" / "public-route-allowlist.json").is_file(),
            "default edge route allowlist differs",
        )
    )
    allowlist = json.loads(
        (DEPLOY / "edge" / "public-route-allowlist.json").read_text(
            encoding="utf-8"
        )
    )
    public_routes = {
        (item["method"], item["path"])
        for item in allowlist
    }
    dangerous_prefixes = (
        "/api/internal",
        "/api/v1/llm",
        "/api/train",
        "/api/documents",
        "/api/artifacts",
        "/api/resume",
        "/v1",
        "/docs",
        "/openapi",
    )
    checks.append(
        _check(
            "edge.public_route_manifest_deny_by_default",
            len(public_routes) == len(allowlist)
            and all(
                not path.startswith(dangerous_prefixes)
                for _method, path in public_routes
            )
            and "path /api/*" not in web_routes,
            "public route manifest is broad or contains a protected route",
        )
    )
    media_gateway = (DEPLOY / "media-gateway" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    media_log_format = next(
        line.strip()
        for line in media_gateway.splitlines()
        if line.strip().startswith("log_format ")
    )
    checks.append(
        _check(
            "media.access_log_has_no_token_uri_or_query",
            "uri=$uri" not in media_log_format
            and "$request_uri" not in media_log_format
            and "$args" not in media_log_format
            and "$http_authorization" not in media_log_format
            and "$http_cookie" not in media_log_format
            and "route_id=qxd_attachment" in media_log_format
            and "access_log off" in media_gateway,
            "media access log may record a signed token or query",
        )
    )
    checks.append(
        _check(
            "cos.policy_has_no_list_grant",
            "ListBucket" not in (DEPLOY / "RUNBOOK.md").read_text(encoding="utf-8")
            or "not pre-granted" in (DEPLOY / "RUNBOOK.md").read_text(encoding="utf-8"),
            "COS List permission appears pre-granted",
        )
    )
    failed = [item["id"] for item in checks if item["status"] != "passed"]
    return {
        "schema_version": "l1-production-artifacts-v1",
        "mode": "offline_dummy_secrets_only",
        "network_requests_performed": False,
        "real_credentials_used": False,
        "cloud_changes_performed": False,
        "status": "passed" if not failed else "failed",
        "resource_budget": {
            "host_memory_mib": HOST_MEMORY_MIB,
            "default_resolved_limit_mib": DEFAULT_RESOLVED_LIMIT_MIB,
            "public_edge_capacity_reserve_mib": PUBLIC_EDGE_BUDGET_MIB,
            "default_capacity_budget_mib": DEFAULT_CAPACITY_BUDGET_MIB,
            "default_non_swap_headroom_mib": (
                HOST_MEMORY_MIB - DEFAULT_RESOLVED_LIMIT_MIB
            ),
            "edge_planning_non_swap_headroom_mib": EDGE_PLANNING_HEADROOM_MIB,
            "minimum_supported_combination_headroom_mib": (
                MIN_SUPPORTED_COMBINATION_HEADROOM_MIB
            ),
        },
        "resource_matrix": resource_matrix,
        "checks": checks,
        "failed": failed,
        "remaining_cloud_gates": [
            "real Tencent COS permission/SSE/request-host probe",
            "real DNS/TLS/ICP/public Host allowlist",
            "real PostgreSQL backup/restore and two-connection races",
            "real ClamAV failure-closed behavior",
            "pinned vendor image user/capability verification",
            "trusted QXD end-user identity or complete transcript",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--mutation", choices=MUTATIONS)
    parser.add_argument("--require-combination", choices=RESOURCE_COMBINATIONS)
    args = parser.parse_args()
    report = run_checks(args.mutation, args.require_combination)
    print(json.dumps(report, indent=2 if args.pretty else None, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
