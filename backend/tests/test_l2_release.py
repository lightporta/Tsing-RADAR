from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_l2_release_manifest as release  # noqa: E402
import check_l2_release as checker  # noqa: E402

RUNNER = checker.RUNNER
RUNNER_IDENTIFIERS = checker.RUNNER_IDENTIFIERS


def _completed(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _manifest() -> dict[str, object]:
    return release.build_manifest(application_images=checker._manifest_stub())


def test_base_images_are_pinned_to_verified_linux_amd64_manifests():
    release.validate_dockerfile_pins()
    assert all(
        release.DIGEST_PATTERN.fullmatch(item["index_digest"])
        and release.DIGEST_PATTERN.fullmatch(item["linux_amd64_manifest_digest"])
        and release.DIGEST_PATTERN.fullmatch(item["linux_amd64_config_digest"])
        for item in release.BASE_IMAGES
    )


def test_backend_build_context_excludes_only_private_governance_paths():
    text = (REPOSITORY_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
    assert checker._dockerignore_contract(text)
    assert "data/catalog_d1/cache" in text
    assert "data/catalog_d1/generated" in text
    assert "data/**" not in text

    assert not checker._dockerignore_contract(
        text.replace("data/mentors.evidence.json", "")
    )
    assert not checker._dockerignore_contract(text.replace("data/private_local/", ""))


@pytest.mark.parametrize(
    "path",
    ("../escape", "/absolute", "C:/absolute", "backend/../escape", "backend//app"),
)
def test_release_path_normalization_rejects_escape_and_noncanonical_forms(path: str):
    with pytest.raises(release.ReleaseManifestError):
        release.normalize_relative_path(path)


def test_release_paths_reject_casefold_collisions():
    with pytest.raises(release.ReleaseManifestError, match="case_collision"):
        release.ensure_unique_normalized_paths(
            ["backend/Dockerfile", "backend/dockerfile"]
        )


def test_release_allowlist_excludes_local_data_and_rejects_injection():
    paths = release.collect_source_paths()
    assert "backend/data/mentors.evidence.json" not in paths
    assert not any(path.startswith("backend/data/private_local/") for path in paths)
    assert not any(path.startswith(".pytest-") for path in paths)

    with pytest.raises(release.ReleaseManifestError, match="prohibited"):
        release.collect_source_paths(
            extra_candidates=["backend/data/mentors.evidence.json"]
        )


def test_release_allowlist_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    outside.write_text("synthetic", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(release.ReleaseManifestError, match="symlink"):
        release._validate_candidate(root, "link.txt")


def test_release_manifest_detects_source_and_platform_tampering():
    manifest = _manifest()
    release.validate_manifest(manifest, verify_local_images=False)

    source_tamper = deepcopy(manifest)
    source_tamper["source_files"][0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(release.ReleaseManifestError, match="integrity"):
        release.validate_manifest(source_tamper, verify_local_images=False)

    platform_tamper = deepcopy(manifest)
    platform_tamper["target_platform"]["architecture"] = "arm64"
    with pytest.raises(release.ReleaseManifestError, match="platform"):
        release.validate_manifest(platform_tamper, verify_local_images=False)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("digest", "inspect_mismatch"),
        ("role", "identity_invalid"),
        ("reference", "identity_invalid"),
        ("extra_image_field", "application_image_invalid"),
        ("compose_slot", "compose_image_slots_invalid"),
        ("cloud_gate", "cloud_gates_invalid"),
        ("extra_top_level", "manifest_fields_invalid"),
    ],
)
def test_release_manifest_rejects_image_identity_and_gate_tampering(
    mutation: str,
    expected: str,
    monkeypatch,
):
    manifest = _manifest()
    inspected = deepcopy(manifest["application_images"])
    monkeypatch.setattr(release, "_inspect_application_images", lambda: inspected)
    if mutation == "digest":
        manifest["application_images"][0]["image_id"] = "sha256:" + "0" * 64
    elif mutation == "role":
        manifest["application_images"][0]["role"] = "frontend"
    elif mutation == "reference":
        manifest["application_images"][0]["local_reference"] = checker.FRONTEND_IMAGE
    elif mutation == "extra_image_field":
        manifest["application_images"][0]["unexpected"] = True
    elif mutation == "compose_slot":
        manifest["compose_image_slots"].pop()
    elif mutation == "cloud_gate":
        manifest["cloud_gates"].pop()
    else:
        manifest["unexpected"] = True
    with pytest.raises(release.ReleaseManifestError, match=expected):
        release.validate_manifest(manifest)


def test_runner_uses_fixed_argv_without_public_or_destructive_actions():
    assert RUNNER.PROJECT == "tsing-radar-prod"
    assert RUNNER.ENV_FILE == REPOSITORY_ROOT / "deploy" / "production" / "production.env"
    for action in RUNNER.RESOURCE_COMBINATION:
        if action == "restore-check":
            continue
        identifiers = RUNNER_IDENTIFIERS if action == "prod-db-verification" else None
        command, timeout = RUNNER.command_for_action(action, identifiers)
        assert isinstance(command, list)
        assert timeout > 0
        assert "down" not in command
        assert "--volumes" not in command
        assert not any("compose.edge" in part for part in command)
        assert not any("compose.qxd" in part for part in command)
        assert not any("compose.media" in part for part in command)

    with pytest.raises(RUNNER.RunnerError, match="not_executable"):
        RUNNER.command_for_action("public-edge")


def test_runner_plan_is_action_ids_only_and_rejects_extra_compose_file():
    assert RUNNER.plan_for("first-deploy-plan") == RUNNER.FIRST_DEPLOY_PLAN
    assert RUNNER.plan_for("upgrade-plan") == RUNNER.UPGRADE_PLAN
    completed = subprocess.run(
        [
            sys.executable,
            str(checker.RUNNER_PATH),
            "--action",
            "first-deploy-plan",
            "--mode",
            "plan",
            "--file",
            "untrusted.yml",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    assert completed.returncode != 0


def test_runner_execute_rejects_all_single_deployment_actions():
    for action in (
        "prod-db-provision",
        "prod-db-verification",
        "migration",
        "backup",
        "restore-check",
        "start-backend-off-traffic",
        "contract-check",
        "start-frontend",
    ):
        with pytest.raises(RUNNER.RunnerError, match="single_action_execute_forbidden"):
            RUNNER.execute_action(action)


def test_first_deploy_workflow_enforces_database_and_recovery_gates():
    RUNNER._validate_workflow_contract(
        "first-deploy-plan",
        RUNNER.FIRST_DEPLOY_PLAN,
    )
    for omitted in (
        "prod-db-provision",
        "prod-db-verification",
        "backup",
        "restore-check",
    ):
        mutated = tuple(step for step in RUNNER.FIRST_DEPLOY_PLAN if step != omitted)
        with pytest.raises(RUNNER.RunnerError, match="workflow_contract_invalid"):
            RUNNER._validate_workflow_contract("first-deploy-plan", mutated)

    visited: list[str] = []
    RUNNER.execute_workflow(
        "first-deploy-plan",
        step_executor=lambda step, _runner: visited.append(step),
    )
    assert visited == list(RUNNER.FIRST_DEPLOY_PLAN)
    assert visited.index("prod-db-provision") < visited.index("prod-db-verification")
    assert visited.index("prod-db-verification") < visited.index("migration")
    assert visited.index("backup") < visited.index("restore-check")
    assert visited.index("restore-check") < visited.index("start-frontend")


def test_first_deploy_passes_current_backup_receipt_to_restore(monkeypatch):
    backup_file = "tsing_radar-20260805T001122Z-Ab12z9.dump"
    visited: list[tuple[str, str | None]] = []

    def fake_execute(step, _runner, *, backup_file=None):
        visited.append((step, backup_file))
        if step == "backup":
            return "tsing_radar-20260805T001122Z-Ab12z9.dump"
        return None

    monkeypatch.setattr(RUNNER, "_execute_step", fake_execute)
    RUNNER.execute_workflow("first-deploy-plan")

    restore_call = next(item for item in visited if item[0] == "restore-check")
    assert restore_call == ("restore-check", backup_file)
    assert next(item for item in visited if item[0] == "backup")[1] is None


@pytest.mark.parametrize(
    "stdout",
    (
        "",
        "backup_created=tsing_radar-20260805T001122Z.dump\n",
        "backup_created=other_db-20260805T001122Z-Ab12z9.dump\n",
        "backup_created=tsing_radar-20260805T001122Z-Ab12z9.dump\n"
        "backup_created=tsing_radar-20260805T001123Z-Cd34x8.dump\n",
        "backup_created=../../escape.dump\n",
    ),
)
def test_backup_receipt_rejects_missing_ambiguous_or_foreign_files(stdout):
    with pytest.raises(RUNNER.RunnerError, match="backup_receipt"):
        RUNNER._parse_backup_created(stdout, "tsing_radar")


def test_backup_receipt_accepts_one_verified_current_filename():
    stdout = "compose noise\nbackup_created=tsing_radar-20260805T001122Z-Ab12z9.dump\n"
    assert RUNNER._parse_backup_created(stdout, "tsing_radar") == (
        "tsing_radar-20260805T001122Z-Ab12z9.dump"
    )


def test_first_deploy_stops_before_migration_when_database_verification_fails():
    visited: list[str] = []

    def fail_verification(step, _runner):
        visited.append(step)
        if step == "prod-db-verification":
            raise RUNNER.RunnerError("action_failed")

    with pytest.raises(RUNNER.RunnerError, match="action_failed"):
        RUNNER.execute_workflow(
            "first-deploy-plan",
            step_executor=fail_verification,
        )
    assert "migration" not in visited
    assert "start-backend-off-traffic" not in visited


def test_upgrade_stops_after_verified_restore_without_compatibility_approval():
    visited: list[str] = []
    with pytest.raises(
        RUNNER.RunnerError,
        match="upgrade_compatibility_requires_separate_approval",
    ) as exc:
        RUNNER.execute_workflow(
            "upgrade-plan",
            step_executor=lambda step, _runner: visited.append(step),
        )
    assert exc.value.exit_code == 77
    assert visited == ["preflight", "infra-health", "backup", "restore-check"]
    assert "migration" not in RUNNER.UPGRADE_PLAN

    bypass = (*RUNNER.UPGRADE_PLAN[:-1], "migration")
    with pytest.raises(RUNNER.RunnerError, match="workflow_contract_invalid"):
        RUNNER._validate_workflow_contract("upgrade-plan", bypass)


def test_restore_cleanup_uses_verified_labels_reverse_order_and_no_volumes():
    ids = {
        "restore-check-db": "db-container-id",
        "restore-check": "restore-container-id",
    }
    calls: list[list[str]] = []

    def fake_runner(arguments, _timeout):
        command = list(arguments)
        calls.append(command)
        if command[:2] == ["docker", "ps"]:
            service = next(
                value.rsplit("=", 1)[1]
                for value in command
                if value.startswith("label=com.docker.compose.service=")
            )
            return _completed(stdout=ids[service] + "\n")
        if command[:2] == ["docker", "inspect"]:
            identifier = command[-1]
            service = next(key for key, value in ids.items() if value == identifier)
            return _completed(
                stdout=json.dumps(
                    {
                        "com.docker.compose.project": RUNNER.PROJECT,
                        "com.docker.compose.service": service,
                    }
                )
            )
        return _completed()

    RUNNER.cleanup_restore_services(fake_runner)
    stop_ids = [command[-1] for command in calls if command[:2] == ["docker", "stop"]]
    assert stop_ids == ["restore-container-id", "db-container-id"]
    flattened = " ".join(part for command in calls for part in command)
    assert "down" not in flattened
    assert "--volumes" not in flattened
    assert "volume rm" not in flattened


def test_restore_cleanup_failure_is_nonzero_manual_action_reason():
    def fake_runner(arguments, _timeout):
        command = list(arguments)
        if command[:2] == ["docker", "ps"]:
            service_filter = next(
                value
                for value in command
                if value.startswith("label=com.docker.compose.service=")
            )
            if service_filter.endswith("restore-check"):
                return _completed(stdout="restore-id\n")
            return _completed()
        if command[:2] == ["docker", "inspect"]:
            return _completed(
                stdout=json.dumps(
                    {
                        "com.docker.compose.project": RUNNER.PROJECT,
                        "com.docker.compose.service": "restore-check",
                    }
                )
            )
        if command[:2] == ["docker", "stop"]:
            return _completed(returncode=1)
        return _completed()

    with pytest.raises(RUNNER.RunnerError, match="manual_action_required"):
        RUNNER.cleanup_restore_services(fake_runner)


def test_restore_primary_failure_still_runs_cleanup(monkeypatch):
    cleaned: list[bool] = []

    def fake_runner(_arguments, _timeout):
        return _completed(returncode=70)

    monkeypatch.setattr(
        RUNNER,
        "cleanup_restore_services",
        lambda _runner: cleaned.append(True),
    )
    with pytest.raises(RUNNER.RunnerError, match="restore_check_failed"):
        RUNNER._run_restore_check(
            fake_runner,
            "tsing_radar-20260805T001122Z-Ab12z9.dump",
        )
    assert cleaned == [True]


def test_restore_uses_only_the_workflow_backup_receipt(monkeypatch):
    calls: list[list[str]] = []
    cleaned: list[bool] = []
    backup_file = "tsing_radar-20260805T001122Z-Ab12z9.dump"

    def fake_runner(arguments, _timeout):
        calls.append(list(arguments))
        return _completed()

    monkeypatch.setattr(
        RUNNER,
        "cleanup_restore_services",
        lambda _runner: cleaned.append(True),
    )
    RUNNER._run_restore_check(fake_runner, backup_file)

    assert len(calls) == 2
    assert calls[0][-6:] == [
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "180",
        "restore-check-db",
    ]
    assert calls[1][-6:] == [
        "run",
        "--rm",
        "--no-deps",
        "--env",
        f"BACKUP_FILE={backup_file}",
        "restore-check",
    ]
    assert cleaned == [True]


def test_backup_script_creates_unique_no_clobber_receipt_and_compose_has_no_static_file():
    backup_script = (
        REPOSITORY_ROOT / "deploy" / "production" / "scripts" / "postgres-backup.sh"
    ).read_text(encoding="utf-8")
    jobs = (
        REPOSITORY_ROOT / "deploy" / "production" / "compose.jobs.yml"
    ).read_text(encoding="utf-8")

    assert 'mktemp "/backups/${DATABASE_NAME}-${stamp}-XXXXXX.dump.partial"' in backup_script
    assert 'ln "$temporary" "$target"' in backup_script
    assert 'sha256sum -c "$(basename "${target}.sha256")"' in backup_script
    assert backup_script.index("sha256sum -c") < backup_script.index("backup_created=")
    assert "BACKUP_FILE: ${BACKUP_FILE" not in jobs


@pytest.mark.skipif(os.name != "posix", reason="real flock semantics run in L2 container checker")
def test_runner_lock_probe_releases_before_the_job(tmp_path: Path):
    lock = tmp_path / "job.lock"
    lock.touch(mode=0o660)
    RUNNER.probe_job_lock(lock)
    RUNNER.probe_job_lock(lock)


def test_container_lock_mount_target_stays_posix_on_windows(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def fake_docker(*arguments, **_kwargs):
        calls.append(list(arguments))
        return _completed(stdout='{"status":"passed"}')

    monkeypatch.setattr(checker, "_docker", fake_docker)
    lock = tmp_path / "job.lock"
    lock.touch()

    exit_code, reason = checker._container_lock_probe(lock)

    assert exit_code == 0
    assert reason == "passed"
    mount = next(
        value
        for value in calls[0]
        if value.startswith("type=bind") and "job.lock" in value
    )
    assert mount.endswith(
        ",target=/var/lib/tsing-radar/job.lock"
    )
    assert "target=\\var\\lib" not in mount


def test_release_manifest_schema_is_valid_json_and_fixed_linux_amd64():
    schema = json.loads(
        (
            REPOSITORY_ROOT
            / "deploy"
            / "production"
            / "release-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["properties"]["target_platform"]["properties"]["os"]["const"] == "linux"
    assert (
        schema["properties"]["target_platform"]["properties"]["architecture"]["const"]
        == "amd64"
    )
