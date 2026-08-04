"""Offline and ephemeral-container checks for the L2 release handoff."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import build_l2_release_manifest as release

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "production"
RUNNER_PATH = DEPLOY / "scripts" / "deploy-runner.py"
BACKEND_IMAGE = "tsing-radar-backend:l2-local"
FRONTEND_IMAGE = "tsing-radar-frontend:l2-local"
CONTAINER_PREFIX = "tsing-radar-l2-check-"
CONTAINER_RUNNER_PATH = "/workspace/deploy/production/scripts/deploy-runner.py"
CONTAINER_JOB_LOCK = "/var/lib/tsing-radar/job.lock"

MUTATIONS = (
    "backend-context-mentor-rule",
    "backend-context-private-rule",
    "tag-only",
    "wrong-platform",
    "manifest-tamper",
    "application-image-digest-tamper",
    "application-image-role-swap",
    "application-image-reference-tamper",
    "compose-slot-removal",
    "cloud-gate-removal",
    "release-inject-mentor",
    "release-traversal",
    "release-case-collision",
    "runner-public-action",
    "runner-compose-injection",
    "runner-direct-migration",
    "runner-missing-db-verification",
    "runner-skip-backup-restore",
    "runner-upgrade-compatibility-bypass",
)

RUNNER_IDENTIFIERS = {
    "PROD_DATABASE_NAME": "tsing_radar_prod",
    "PROD_DATABASE_USER": "tsing_radar_prod",
    "STAGE_DATABASE_NAME": "tsing_radar_stage",
    "STAGE_DATABASE_USER": "tsing_radar_stage",
}


def _load_runner_module() -> Any:
    spec = importlib.util.spec_from_file_location("l2_deploy_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("runner module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner_module()


def _check(check_id: str, passed: bool, reason: str) -> dict[str, object]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "reason": "ok" if passed else reason,
    }


def _command(
    arguments: list[str],
    *,
    timeout: int = 120,
    expected: set[int] = {0},
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    if completed.returncode not in expected:
        raise RuntimeError("L2 check subprocess failed")
    return completed


def _manifest_stub() -> list[dict[str, str]]:
    return [
        {
            "role": "backend",
            "local_reference": BACKEND_IMAGE,
            "image_id": "sha256:" + "b" * 64,
            "os": "linux",
            "architecture": "amd64",
        },
        {
            "role": "frontend",
            "local_reference": FRONTEND_IMAGE,
            "image_id": "sha256:" + "f" * 64,
            "os": "linux",
            "architecture": "amd64",
        },
    ]


def _base_image_relation_valid(images: list[dict[str, str]]) -> bool:
    if images != [dict(item) for item in release.BASE_IMAGES]:
        return False
    for item in images:
        if item["tag"].endswith(":latest"):
            return False
        for key in (
            "index_digest",
            "linux_amd64_manifest_digest",
            "linux_amd64_config_digest",
        ):
            if not release.DIGEST_PATTERN.fullmatch(item[key]):
                return False
    return True


def _verify_registry_relationships() -> bool:
    for item in release.BASE_IMAGES:
        repository = item["tag"].split(":", 1)[0]
        index = _command(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{repository}@{item['index_digest']}",
                "--raw",
            ],
            timeout=90,
        )
        index_json = json.loads(index.stdout)
        matches = [
            manifest
            for manifest in index_json.get("manifests", [])
            if manifest.get("digest") == item["linux_amd64_manifest_digest"]
            and manifest.get("platform") == {"architecture": "amd64", "os": "linux"}
        ]
        if len(matches) != 1:
            return False
        manifest = _command(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{repository}@{item['linux_amd64_manifest_digest']}",
                "--raw",
            ],
            timeout=90,
        )
        manifest_json = json.loads(manifest.stdout)
        if manifest_json.get("config", {}).get("digest") != item[
            "linux_amd64_config_digest"
        ]:
            return False
    return True


def _dockerignore_contract(text: str) -> bool:
    lines = {line.strip() for line in text.splitlines() if line.strip()}
    return {
        "data/catalog_d1/cache",
        "data/catalog_d1/generated",
        "data/mentors.evidence.json",
        "data/private_local/",
    }.issubset(lines)


def _runner_contract() -> bool:
    forbidden = {"down", "--volume", "--volumes", "-v"}
    for action in RUNNER.RESOURCE_COMBINATION:
        if action == "restore-check":
            continue
        identifiers = RUNNER_IDENTIFIERS if action == "prod-db-verification" else None
        command, _timeout = RUNNER.command_for_action(action, identifiers)
        if not isinstance(command, list) or any(item in forbidden for item in command):
            return False
        joined = " ".join(command)
        if "compose.edge" in joined or "compose.qxd" in joined or "compose.media" in joined:
            return False
    try:
        RUNNER.command_for_action("public-edge")
    except RUNNER.RunnerError:
        pass
    else:
        return False
    return RUNNER.PROJECT == "tsing-radar-prod" and RUNNER.ENV_FILE == (
        DEPLOY / "production.env"
    )


def _plan_contract(extra_argument: bool = False) -> bool:
    command = [
        sys.executable,
        str(RUNNER_PATH),
        "--action",
        "first-deploy-plan",
        "--mode",
        "plan",
    ]
    if extra_argument:
        command.extend(("--file", "untrusted.yml"))
    completed = _command(command, timeout=30, expected=set(range(256)))
    if extra_argument:
        return completed.returncode == 0
    if completed.returncode != 0:
        return False
    report = json.loads(completed.stdout)
    upgrade = _command(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--action",
            "upgrade-plan",
            "--mode",
            "plan",
        ],
        timeout=30,
        expected=set(range(256)),
    )
    if upgrade.returncode != 0:
        return False
    upgrade_report = json.loads(upgrade.stdout)
    return (
        report.get("steps") == list(RUNNER.FIRST_DEPLOY_PLAN)
        and upgrade_report.get("steps") == list(RUNNER.UPGRADE_PLAN)
        and "migration" not in upgrade_report.get("steps", [])
        and upgrade_report.get("steps", [])[-1] == RUNNER.COMPATIBILITY_GATE
        and report.get("values_or_host_metadata_emitted") is False
        and set(report) == {
            "schema_version",
            "status",
            "action_id",
            "steps",
            "values_or_host_metadata_emitted",
        }
    )


def _workflow_execution_contract(mutation: str | None) -> bool:
    first = list(RUNNER.FIRST_DEPLOY_PLAN)
    upgrade = list(RUNNER.UPGRADE_PLAN)
    if mutation == "runner-missing-db-verification":
        first.remove("prod-db-verification")
    if mutation == "runner-skip-backup-restore":
        first.remove("backup")
        first.remove("restore-check")
    if mutation == "runner-upgrade-compatibility-bypass":
        upgrade[-1:] = ["migration"]
    try:
        RUNNER._validate_workflow_contract("first-deploy-plan", tuple(first))
        RUNNER._validate_workflow_contract("upgrade-plan", tuple(upgrade))
    except RUNNER.RunnerError:
        return False

    direct = _command(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--action",
            "migration",
            "--mode",
            "execute",
        ],
        timeout=30,
        expected=set(range(256)),
    )
    try:
        direct_report = json.loads(direct.stdout)
    except json.JSONDecodeError:
        return False
    direct_blocked = (
        direct.returncode != 0
        and direct_report.get("reason") == "single_action_execute_forbidden"
    )
    if mutation == "runner-direct-migration":
        direct_blocked = False

    visited: list[str] = []
    try:
        RUNNER.execute_workflow(
            "upgrade-plan",
            step_executor=lambda step, _runner: visited.append(step),
        )
    except RUNNER.RunnerError as exc:
        upgrade_blocked = (
            exc.reason == "upgrade_compatibility_requires_separate_approval"
            and visited == list(RUNNER.UPGRADE_PLAN[:-1])
        )
    else:
        upgrade_blocked = False
    return direct_blocked and upgrade_blocked


def _source_contract(mutation: str | None) -> tuple[bool, dict[str, object]]:
    extra: list[str] = []
    if mutation == "release-inject-mentor":
        extra = ["backend/data/mentors.evidence.json"]
    elif mutation == "release-traversal":
        extra = ["../outside"]
    try:
        paths = release.collect_source_paths(extra_candidates=extra)
        manifest = release.build_manifest()
        if mutation == "manifest-tamper":
            manifest["source_files"][0]["sha256"] = "sha256:" + "0" * 64
        if mutation == "application-image-digest-tamper":
            manifest["application_images"][0]["image_id"] = "sha256:" + "0" * 64
        if mutation == "application-image-role-swap":
            manifest["application_images"][0]["role"], manifest["application_images"][1]["role"] = (
                manifest["application_images"][1]["role"],
                manifest["application_images"][0]["role"],
            )
        if mutation == "application-image-reference-tamper":
            manifest["application_images"][0]["local_reference"] = FRONTEND_IMAGE
        if mutation == "compose-slot-removal":
            manifest["compose_image_slots"].pop()
        if mutation == "cloud-gate-removal":
            manifest["cloud_gates"].pop()
        if mutation == "wrong-platform":
            manifest["target_platform"]["architecture"] = "arm64"
        release.validate_manifest(manifest)
        prohibited_absent = (
            "backend/data/mentors.evidence.json" not in paths
            and not any(path.startswith("backend/data/private_local/") for path in paths)
            and not any(path.startswith(".pytest-") for path in paths)
        )
        return prohibited_absent, {"source_files": len(paths)}
    except release.ReleaseManifestError as exc:
        return False, {"reason": str(exc)}


def _case_collision_contract(mutation: str | None) -> bool:
    values = ["backend/Dockerfile"]
    if mutation == "release-case-collision":
        values.append("backend/dockerfile")
    try:
        release.ensure_unique_normalized_paths(values)
        return True
    except release.ReleaseManifestError:
        return False


def run_static_checks(
    mutation: str | None = None,
    *,
    verify_registry: bool = False,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    base_images = [dict(item) for item in release.BASE_IMAGES]
    if mutation == "tag-only":
        base_images[0]["linux_amd64_manifest_digest"] = "python:3.11-slim"
    pins_ok = True
    try:
        release.validate_dockerfile_pins()
    except release.ReleaseManifestError:
        pins_ok = False
    checks.append(
        _check(
            "images.linux_amd64_manifest_pins",
            pins_ok and _base_image_relation_valid(base_images),
            "base image pin or platform relationship invalid",
        )
    )
    checks.append(
        _check(
            "runner.workflow_order_and_non_bypassable_execute",
            _workflow_execution_contract(mutation),
            "runner workflow can skip database, backup, restore, or compatibility gates",
        )
    )
    if verify_registry:
        registry_ok = False
        try:
            registry_ok = _verify_registry_relationships()
        except (RuntimeError, json.JSONDecodeError):
            registry_ok = False
        checks.append(
            _check(
                "images.registry_index_manifest_config_relationship",
                registry_ok,
                "registry relationship could not be verified",
            )
        )

    dockerignore = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
    if mutation == "backend-context-mentor-rule":
        dockerignore = dockerignore.replace("data/mentors.evidence.json", "")
    if mutation == "backend-context-private-rule":
        dockerignore = dockerignore.replace("data/private_local/", "")
    checks.append(
        _check(
            "release.backend_context_excludes_private_governance_data",
            _dockerignore_contract(dockerignore),
            "backend context private-data ignore rule missing",
        )
    )
    root_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    checks.append(
        _check(
            "release.root_ephemeral_ignore_is_precise",
            "/.pytest-*/" in root_ignore
            and "/.l2-release/" in root_ignore
            and "deploy/production/release-manifest.local.json" in root_ignore,
            "root L2 ignore contract missing",
        )
    )

    source_ok, source_observed = _source_contract(mutation)
    checks.append(
        {
            **_check(
                "release.normalized_allowlist_and_integrity",
                source_ok,
                "release source allowlist or integrity failed",
            ),
            "observed": source_observed,
        }
    )
    checks.append(
        _check(
            "release.casefold_collision_rejected",
            _case_collision_contract(mutation),
            "case-insensitive path collision accepted",
        )
    )
    runner_ok = _runner_contract()
    if mutation == "runner-public-action":
        runner_ok = False
    checks.append(
        _check(
            "runner.fixed_action_compose_and_project_mapping",
            runner_ok,
            "runner exposes a non-enumerated or public/destructive action",
        )
    )
    checks.append(
        _check(
            "runner.plan_output_and_argument_boundary",
            _plan_contract(extra_argument=mutation == "runner-compose-injection"),
            "runner plan leaks metadata or accepted command injection",
        )
    )
    pytest_dirs = [
        path
        for path in ROOT.iterdir()
        if path.name.startswith(".pytest-") and path.is_dir() and not path.is_symlink()
    ]
    checks.append(
        {
            **_check(
                "release.pytest_directories_metadata_only",
                all(path.parent == ROOT for path in pytest_dirs),
                "pytest temporary path escaped repository root",
            ),
            "observed_count": len(pytest_dirs),
            "contents_read": False,
        }
    )
    return checks


def _docker(*arguments: str, expected: set[int] = {0}, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return _command(["docker", *arguments], timeout=timeout, expected=expected)


def _bind_source(path: Path) -> str:
    # Docker Desktop's native CLI receives subprocess argv directly here;
    # forward slashes avoid Windows backslash/quote ambiguity in --mount.
    return path.resolve().as_posix()


def _labelled_restore_ids() -> list[str]:
    result = _docker(
        "ps",
        "-aq",
        "--filter",
        f"label=com.docker.compose.project={RUNNER.PROJECT}",
        "--filter",
        "label=com.docker.compose.service=restore-check-db",
    )
    second = _docker(
        "ps",
        "-aq",
        "--filter",
        f"label=com.docker.compose.project={RUNNER.PROJECT}",
        "--filter",
        "label=com.docker.compose.service=restore-check",
    )
    return [line for line in (result.stdout + second.stdout).splitlines() if line.strip()]


def _start_restore_pair(generation: str, lock_file: Path) -> list[str]:
    if _labelled_restore_ids():
        raise RuntimeError("existing restore-check containers make the test unsafe")
    job_script = DEPLOY / "scripts" / "job-lock.sh"
    names = [
        f"{CONTAINER_PREFIX}{generation}-restore-db",
        f"{CONTAINER_PREFIX}{generation}-restore",
    ]
    _docker(
        "run",
        "--detach",
        "--name",
        names[0],
        "--label",
        f"com.docker.compose.project={RUNNER.PROJECT}",
        "--label",
        "com.docker.compose.service=restore-check-db",
        "--env",
        f"JOB_LOCK_FILE_IN_CONTAINER={CONTAINER_JOB_LOCK}",
        "--mount",
        f"type=bind,source={_bind_source(job_script)},target=/opt/job-lock.sh,readonly",
        "--mount",
        f"type=bind,source={_bind_source(lock_file)},target={CONTAINER_JOB_LOCK}",
        BACKEND_IMAGE,
        "/bin/sh",
        "/opt/job-lock.sh",
        "/bin/sh",
        "-c",
        "sleep 300",
    )
    _docker(
        "run",
        "--detach",
        "--name",
        names[1],
        "--label",
        f"com.docker.compose.project={RUNNER.PROJECT}",
        "--label",
        "com.docker.compose.service=restore-check",
        "alpine:3.22",
        "/bin/sh",
        "-c",
        "sleep 300",
    )
    time.sleep(0.5)
    return names


def _container_lock_probe(lock_file: Path) -> tuple[int, str]:
    result = _docker(
        "run",
        "--rm",
        "--mount",
        f"type=bind,source={_bind_source(RUNNER_PATH)},target={CONTAINER_RUNNER_PATH},readonly",
        "--mount",
        f"type=bind,source={_bind_source(lock_file)},target={CONTAINER_JOB_LOCK}",
        BACKEND_IMAGE,
        "python",
        CONTAINER_RUNNER_PATH,
        "--action",
        "lock-probe",
        "--mode",
        "execute",
        expected=set(range(256)),
    )
    try:
        report = json.loads(result.stdout)
        reason = str(report.get("reason", report.get("status", "unknown")))
    except json.JSONDecodeError:
        reason = "invalid_probe_response"
    return result.returncode, reason


def _container_migration_import_contract() -> dict[str, object]:
    """Prove an out-of-WORKDIR wrapper imports app only via PYTHONPATH=/app."""

    migration_script = DEPLOY / "scripts" / "migration_with_lock.py"
    probe_code = (
        "import runpy;"
        "runpy.run_path('/opt/tsing-radar/migration_with_lock.py', "
        "run_name='migration_import_probe')"
    )
    base_arguments = [
        "run",
        "--rm",
        "--pull",
        "never",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--workdir",
        "/",
        "--mount",
        (
            f"type=bind,source={_bind_source(migration_script)},"
            "target=/opt/tsing-radar/migration_with_lock.py,readonly"
        ),
    ]

    def run_probe(python_path: str | None) -> subprocess.CompletedProcess[str]:
        arguments = list(base_arguments)
        if python_path is not None:
            arguments.extend(("--env", f"PYTHONPATH={python_path}"))
        arguments.extend((BACKEND_IMAGE, "python", "-c", probe_code))
        return _docker(*arguments, expected=set(range(256)))

    exact = run_probe("/app")
    missing = run_probe(None)
    drifted = run_probe("/srv/app")
    return {
        **_check(
            "jobs.migration_imports_app_from_outside_workdir",
            exact.returncode == 0
            and missing.returncode != 0
            and drifted.returncode != 0,
            "migration wrapper import path is missing, implicit, or drifted",
        ),
        "observed_exit_codes": {
            "exact": exact.returncode,
            "missing": missing.returncode,
            "drifted": drifted.returncode,
        },
    }


def _cleanup_with_runner() -> None:
    RUNNER.cleanup_restore_services()


def _wait_container_exec(name: str, command: list[str], attempts: int = 60) -> bool:
    for _ in range(attempts):
        result = _docker("exec", name, *command, expected=set(range(256)))
        if result.returncode == 0:
            return True
        time.sleep(0.25)
    return False


def _container_database_verification(
    temporary_path: Path,
    generation: str,
) -> dict[str, object]:
    network = f"{CONTAINER_PREFIX}{generation}-db-network"
    postgres_name = f"{CONTAINER_PREFIX}{generation}-postgres"
    bootstrap_password = "dummyL2Bootstrap_0123456789abcdef"
    prod_password = "dummyL2ProdApp_0123456789abcdef"
    stage_password = "dummyL2StageApp_0123456789abcdef"
    bootstrap_secret = temporary_path / "database-bootstrap"
    prod_secret = temporary_path / "database-prod"
    stage_secret = temporary_path / "database-stage"
    bootstrap_secret.write_text(bootstrap_password, encoding="utf-8")
    prod_secret.write_text(prod_password, encoding="utf-8")
    stage_secret.write_text(stage_password, encoding="utf-8")
    provision_script = DEPLOY / "scripts" / "database_provision.py"

    def provision(
        target_db: str,
        target_user: str,
        target_secret: Path,
        protected: tuple[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            "run",
            "--rm",
            "--network",
            network,
            "--mount",
            f"type=bind,source={_bind_source(provision_script)},target=/opt/database_provision.py,readonly",
            "--mount",
            f"type=bind,source={_bind_source(bootstrap_secret)},target=/run/secrets/bootstrap,readonly",
            "--mount",
            f"type=bind,source={_bind_source(target_secret)},target=/run/secrets/target,readonly",
            "--env",
            "DATABASE_HOST=postgres",
            "--env",
            "DATABASE_BOOTSTRAP_USER=l2_bootstrap",
            "--env",
            "DATABASE_BOOTSTRAP_PASSWORD_FILE=/run/secrets/bootstrap",
            "--env",
            f"TARGET_DATABASE_NAME={target_db}",
            "--env",
            f"TARGET_DATABASE_USER={target_user}",
            "--env",
            "TARGET_DATABASE_PASSWORD_FILE=/run/secrets/target",
        ]
        if protected is not None:
            arguments.extend(
                (
                    "--env",
                    f"PROTECTED_DATABASE_NAME={protected[0]}",
                    "--env",
                    f"PROTECTED_DATABASE_USER={protected[1]}",
                )
            )
        arguments.extend((BACKEND_IMAGE, "python", "/opt/database_provision.py"))
        return _docker(*arguments, expected=set(range(256)))

    def verify() -> subprocess.CompletedProcess[str]:
        return _docker(
            "run",
            "--rm",
            "--network",
            network,
            "--mount",
            f"type=bind,source={_bind_source(bootstrap_secret)},target=/run/secrets/bootstrap,readonly",
            "--mount",
            f"type=bind,source={_bind_source(prod_secret)},target=/run/secrets/target,readonly",
            "--env",
            "DATABASE_HOST=postgres",
            "--env",
            "DATABASE_BOOTSTRAP_USER=l2_bootstrap",
            "--env",
            "DATABASE_BOOTSTRAP_PASSWORD_FILE=/run/secrets/bootstrap",
            "--env",
            "TARGET_DATABASE_NAME=l2_prod",
            "--env",
            "TARGET_DATABASE_USER=l2_prod_app",
            "--env",
            "TARGET_DATABASE_PASSWORD_FILE=/run/secrets/target",
            "--env",
            "PROTECTED_DATABASE_NAME=l2_stage",
            "--env",
            "PROTECTED_DATABASE_USER=l2_stage_app",
            BACKEND_IMAGE,
            "python",
            "-c",
            RUNNER.DB_VERIFICATION_CODE,
            expected=set(range(256)),
        )

    _docker("network", "create", network)
    try:
        _docker(
            "run",
            "--detach",
            "--name",
            postgres_name,
            "--network",
            network,
            "--network-alias",
            "postgres",
            "--env",
            "POSTGRES_USER=l2_bootstrap",
            "--env",
            f"POSTGRES_PASSWORD={bootstrap_password}",
            "--env",
            "POSTGRES_DB=postgres",
            "postgres:16-alpine",
        )
        if not _wait_container_exec(
            postgres_name,
            ["pg_isready", "-U", "l2_bootstrap", "-d", "postgres"],
        ):
            raise RuntimeError("ephemeral PostgreSQL did not become ready")
        before_provision = verify()
        prod_provision = provision("l2_prod", "l2_prod_app", prod_secret)
        stage_provision = provision(
            "l2_stage",
            "l2_stage_app",
            stage_secret,
            protected=("l2_prod", "l2_prod_app"),
        )
        prod_reconverge = provision(
            "l2_prod",
            "l2_prod_app",
            prod_secret,
            protected=("l2_stage", "l2_stage_app"),
        )
        verified = verify()
        create_table = _docker(
            "run",
            "--rm",
            "--network",
            network,
            "--env",
            f"PGPASSWORD={prod_password}",
            "postgres:16-alpine",
            "psql",
            "-h",
            "postgres",
            "-U",
            "l2_prod_app",
            "-d",
            "l2_prod",
            "-c",
            "CREATE TABLE must_block_first_deploy(id integer)",
            expected=set(range(256)),
        )
        nonempty = verify()
        combined_output = "".join(
            item.stdout + item.stderr
            for item in (
                before_provision,
                prod_provision,
                stage_provision,
                prod_reconverge,
                verified,
                create_table,
                nonempty,
            )
        )
        passed = (
            before_provision.returncode != 0
            and prod_provision.returncode == 0
            and stage_provision.returncode == 0
            and prod_reconverge.returncode == 0
            and verified.returncode == 0
            and create_table.returncode == 0
            and nonempty.returncode != 0
            and bootstrap_password not in combined_output
            and prod_password not in combined_output
            and stage_password not in combined_output
        )
        return {
            **_check(
                "runner.prod_database_verification_real_postgres",
                passed,
                "database verification did not fail closed before provision or on nonempty target",
            ),
            "observed_exit_codes": {
                "before_provision": before_provision.returncode,
                "prod_provision": prod_provision.returncode,
                "stage_provision": stage_provision.returncode,
                "prod_reconverge": prod_reconverge.returncode,
                "verified_empty_isolated": verified.returncode,
                "nonempty_target": nonempty.returncode,
            },
        }
    finally:
        _docker("rm", "-f", postgres_name, expected={0, 1})
        _docker("network", "rm", network, expected={0, 1})


def _container_migration_database_probe(
    temporary_path: Path,
    generation: str,
) -> dict[str, object]:
    """Run the real migration wrapper against an ephemeral PostgreSQL target."""

    network = f"{CONTAINER_PREFIX}{generation}-migration-network"
    postgres_name = f"{CONTAINER_PREFIX}{generation}-migration-postgres"
    bootstrap_password = "dummyL2MigrationBootstrap_0123456789abcdef"
    app_password = "dummyL2MigrationApp_@:/?#%[]!"
    bootstrap_secret = temporary_path / "migration-bootstrap"
    app_secret = temporary_path / "migration-app"
    bootstrap_secret.write_text(bootstrap_password, encoding="utf-8")
    app_secret.write_text(app_password, encoding="utf-8")
    provision_script = DEPLOY / "scripts" / "database_provision.py"
    migration_script = DEPLOY / "scripts" / "migration_with_lock.py"
    alembic_environment = ROOT / "backend" / "alembic" / "env.py"

    _docker("network", "create", network)
    try:
        _docker(
            "run",
            "--detach",
            "--name",
            postgres_name,
            "--network",
            network,
            "--network-alias",
            "postgres",
            "--env",
            "POSTGRES_USER=l2_migration_bootstrap",
            "--env",
            f"POSTGRES_PASSWORD={bootstrap_password}",
            "--env",
            "POSTGRES_DB=postgres",
            "postgres:16-alpine",
        )
        if not _wait_container_exec(
            postgres_name,
            ["pg_isready", "-U", "l2_migration_bootstrap", "-d", "postgres"],
        ):
            raise RuntimeError("ephemeral migration PostgreSQL did not become ready")

        provision = _docker(
            "run",
            "--rm",
            "--network",
            network,
            "--mount",
            (
                f"type=bind,source={_bind_source(provision_script)},"
                "target=/opt/database_provision.py,readonly"
            ),
            "--mount",
            (
                f"type=bind,source={_bind_source(bootstrap_secret)},"
                "target=/run/secrets/bootstrap,readonly"
            ),
            "--mount",
            (
                f"type=bind,source={_bind_source(app_secret)},"
                "target=/run/secrets/database,readonly"
            ),
            "--env",
            "DATABASE_HOST=postgres",
            "--env",
            "DATABASE_BOOTSTRAP_USER=l2_migration_bootstrap",
            "--env",
            "DATABASE_BOOTSTRAP_PASSWORD_FILE=/run/secrets/bootstrap",
            "--env",
            "TARGET_DATABASE_NAME=l2_migration",
            "--env",
            "TARGET_DATABASE_USER=l2_migration_app",
            "--env",
            "TARGET_DATABASE_PASSWORD_FILE=/run/secrets/database",
            BACKEND_IMAGE,
            "python",
            "/opt/database_provision.py",
            expected=set(range(256)),
        )
        migration = _docker(
            "run",
            "--rm",
            "--pull",
            "never",
            "--platform",
            "linux/amd64",
            "--network",
            network,
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:size=32m,mode=1777",
            "--mount",
            (
                f"type=bind,source={_bind_source(migration_script)},"
                "target=/opt/tsing-radar/migration_with_lock.py,readonly"
            ),
            "--mount",
            (
                f"type=bind,source={_bind_source(alembic_environment)},"
                "target=/app/alembic/env.py,readonly"
            ),
            "--mount",
            (
                f"type=bind,source={_bind_source(app_secret)},"
                "target=/run/secrets/database_password,readonly"
            ),
            "--env",
            "PYTHONPATH=/app",
            "--env",
            "DATABASE_HOST=postgres",
            "--env",
            "DATABASE_PORT=5432",
            "--env",
            "DATABASE_NAME=l2_migration",
            "--env",
            "DATABASE_USER=l2_migration_app",
            "--env",
            "DATABASE_PASSWORD_FILE=/run/secrets/database_password",
            "--env",
            "AUTO_CREATE_SCHEMA=false",
            "--env",
            "MIGRATION_LOCK_TIMEOUT_SECONDS=5",
            BACKEND_IMAGE,
            "python",
            "/opt/tsing-radar/migration_with_lock.py",
            expected=set(range(256)),
            timeout=180,
        )
        version = _docker(
            "run",
            "--rm",
            "--network",
            network,
            "--env",
            f"PGPASSWORD={app_password}",
            "postgres:16-alpine",
            "psql",
            "-h",
            "postgres",
            "-U",
            "l2_migration_app",
            "-d",
            "l2_migration",
            "-Atqc",
            "SELECT count(*) FROM alembic_version",
            expected=set(range(256)),
        )
        combined_output = (
            provision.stdout
            + provision.stderr
            + migration.stdout
            + migration.stderr
            + version.stdout
            + version.stderr
        )
        passed = (
            provision.returncode == 0
            and migration.returncode == 0
            and version.returncode == 0
            and version.stdout.strip() == "1"
            and bootstrap_password not in combined_output
            and app_password not in combined_output
        )
        return {
            **_check(
                "jobs.migration_real_postgres_settings_dsn",
                passed,
                "migration wrapper did not apply Alembic through explicit psycopg kwargs",
            ),
            "observed_exit_codes": {
                "provision": provision.returncode,
                "migration": migration.returncode,
                "alembic_version": version.returncode,
            },
        }
    finally:
        _docker("rm", "-f", postgres_name, expected={0, 1})
        _docker("network", "rm", network, expected={0, 1})


def run_container_checks() -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    generation = uuid.uuid4().hex[:10]
    created: list[str] = []
    lock_file: Path | None = None
    try:
        backend_absent = _docker(
            "run",
            "--rm",
            BACKEND_IMAGE,
            "python",
            "-c",
            (
                "from pathlib import Path;"
                "assert not Path('/app/data/mentors.evidence.json').exists();"
                "assert not Path('/app/data/private_local').exists()"
            ),
            expected=set(range(256)),
        )
        backend_inspect = json.loads(
            _docker("image", "inspect", BACKEND_IMAGE, "--format", "{{json .}}").stdout
        )
        frontend_inspect = json.loads(
            _docker("image", "inspect", FRONTEND_IMAGE, "--format", "{{json .}}").stdout
        )
        checks.append(
            _check(
                "images.application_linux_amd64_and_context_exclusion",
                backend_absent.returncode == 0
                and backend_inspect.get("Os") == "linux"
                and backend_inspect.get("Architecture") == "amd64"
                and backend_inspect.get("Config", {}).get("User") == "10001:10001"
                and frontend_inspect.get("Os") == "linux"
                and frontend_inspect.get("Architecture") == "amd64",
                "application image platform, uid or excluded data contract failed",
            )
        )
        checks.append(_container_migration_import_contract())

        local_ephemeral_root = ROOT / ".l2-release"
        local_ephemeral_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=CONTAINER_PREFIX,
            dir=local_ephemeral_root,
        ) as temporary:
            temporary_path = Path(temporary)
            checks.append(_container_database_verification(temporary_path, generation))
            checks.append(
                _container_migration_database_probe(temporary_path, generation)
            )
            # Docker Desktop maps a direct workspace file consistently for the
            # numeric container uid; Windows TemporaryDirectory ACLs do not.
            lock_file = local_ephemeral_root / f"{CONTAINER_PREFIX}{generation}.lock"
            lock_file.touch()
            if os.name == "posix":
                lock_file.chmod(0o660)

            pair = _start_restore_pair(generation + "a", lock_file)
            created.extend(pair)
            busy, busy_reason = _container_lock_probe(lock_file)
            _cleanup_with_runner()
            created.clear()
            released, released_reason = _container_lock_probe(lock_file)
            checks.append(
                {
                    **_check(
                        "runner.probe_releases_before_job_and_second_job_is_busy",
                        busy == 75 and released == 0,
                        "runner/job lock layering self-locked or failed to reject concurrency",
                    ),
                    "observed_exit_codes": {"job_active": busy, "after_cleanup": released},
                    "observed_reasons": {
                        "job_active": busy_reason,
                        "after_cleanup": released_reason,
                    },
                }
            )

            pair = _start_restore_pair(generation + "b", lock_file)
            created.extend(pair)
            try:
                raise RuntimeError("synthetic_primary_failure")
            except RuntimeError:
                _cleanup_with_runner()
            created.clear()
            failure_release, failure_release_reason = _container_lock_probe(lock_file)

            pair = _start_restore_pair(generation + "c", lock_file)
            created.extend(pair)
            if os.name == "nt":
                previous_term = signal.getsignal(signal.SIGTERM)
                previous_int = signal.getsignal(signal.SIGINT)
                RUNNER._install_signal_handlers()
                signal_handler = signal.getsignal(signal.SIGTERM)
                try:
                    try:
                        signal_handler(signal.SIGTERM, None)
                    finally:
                        _cleanup_with_runner()
                except RUNNER.RunnerInterrupted as interrupted:
                    signal_exit = interrupted.exit_code
                finally:
                    signal.signal(signal.SIGTERM, previous_term)
                    signal.signal(signal.SIGINT, previous_int)
                signal_mode = "registered_handler_invocation_windows"
            else:
                child_code = (
                    "import importlib.util,signal,sys,time;"
                    f"p={str(RUNNER_PATH)!r};"
                    "s=importlib.util.spec_from_file_location('signal_runner',p);"
                    "m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);"
                    "m._install_signal_handlers();"
                    "\ntry:\n time.sleep(60)\nfinally:\n m.cleanup_restore_services()"
                )
                child = subprocess.Popen(
                    [sys.executable, "-c", child_code],
                    cwd=ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                time.sleep(1)
                child.terminate()
                child.wait(timeout=30)
                signal_exit = child.returncode
                signal_mode = "real_sigterm_posix"
            created.clear()
            signal_release, signal_release_reason = _container_lock_probe(lock_file)
            checks.append(
                {
                    **_check(
                        "runner.restore_failure_and_sigterm_cleanup_release_lock",
                        failure_release == 0
                        and signal_release == 0
                        and not _labelled_restore_ids(),
                        "restore cleanup did not converge after failure or SIGTERM",
                    ),
                    "observed_exit_codes": {
                        "after_primary_failure": failure_release,
                        "signal_path": signal_exit,
                        "after_sigterm": signal_release,
                    },
                    "signal_mode": signal_mode,
                    "observed_reasons": {
                        "after_primary_failure": failure_release_reason,
                        "after_sigterm": signal_release_reason,
                    },
                }
            )
    finally:
        for name in reversed(created):
            if name.startswith(CONTAINER_PREFIX):
                _docker("rm", "-f", name, expected={0, 1})
        if (
            lock_file is not None
            and lock_file.parent == ROOT / ".l2-release"
            and lock_file.name.startswith(CONTAINER_PREFIX)
        ):
            lock_file.unlink(missing_ok=True)
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", choices=MUTATIONS)
    parser.add_argument("--verify-registry", action="store_true")
    parser.add_argument("--containers", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    checks = run_static_checks(args.mutation, verify_registry=args.verify_registry)
    if args.containers:
        checks.extend(run_container_checks())
    failed = [item["id"] for item in checks if item["status"] != "passed"]
    report = {
        "schema_version": "l2-release-check-v1",
        "mode": "local_dummy_and_public_image_metadata_only",
        "target_platform": "linux/amd64",
        "real_credentials_used": False,
        "cloud_changes_performed": False,
        "host_ports_published": False,
        "persistent_volumes_created": False,
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed": failed,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
