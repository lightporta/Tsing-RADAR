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
    assert "deploy/production/data/empty-mentor-governance.json" in paths
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
    preflight_command, _ = RUNNER.command_for_action("preflight")
    environment_index = preflight_command.index("--environment-file")
    assert preflight_command[environment_index + 1] == str(RUNNER.ENV_FILE)
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
    assert (
        RUNNER.plan_for("resume-after-migration-plan")
        == RUNNER.RESUME_AFTER_MIGRATION_PLAN
    )
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
        "post-migration-verification",
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


def test_resume_after_migration_is_complete_non_bypassable_and_ordered():
    RUNNER._validate_workflow_contract(
        "resume-after-migration-plan",
        RUNNER.RESUME_AFTER_MIGRATION_PLAN,
    )
    assert not {
        "prod-db-provision",
        "prod-db-verification",
        "migration",
    }.intersection(RUNNER.RESUME_AFTER_MIGRATION_PLAN)
    for omitted in (
        "post-migration-verification",
        "contract-check",
        "backup",
        "restore-check",
    ):
        mutated = tuple(
            step for step in RUNNER.RESUME_AFTER_MIGRATION_PLAN if step != omitted
        )
        with pytest.raises(RUNNER.RunnerError, match="resume_workflow_contract_invalid"):
            RUNNER._validate_workflow_contract(
                "resume-after-migration-plan",
                mutated,
            )

    visited: list[str] = []
    RUNNER.execute_workflow(
        "resume-after-migration-plan",
        step_executor=lambda step, _runner: visited.append(step),
    )
    assert visited == list(RUNNER.RESUME_AFTER_MIGRATION_PLAN)
    assert visited.index("post-migration-verification") < visited.index(
        "start-backend-off-traffic"
    )
    assert visited.index("contract-check") < visited.index("backup")
    assert visited.index("backup") < visited.index("restore-check")
    assert visited.index("restore-check") < visited.index("start-frontend")


def test_resume_stops_before_backend_when_post_migration_state_is_not_safe():
    visited: list[str] = []

    def fail_verification(step, _runner):
        visited.append(step)
        if step == "post-migration-verification":
            raise RUNNER.RunnerError("action_failed")

    with pytest.raises(RUNNER.RunnerError, match="action_failed") as failure:
        RUNNER.execute_workflow(
            "resume-after-migration-plan",
            step_executor=fail_verification,
        )
    assert failure.value.failed_step_id == "post-migration-verification"
    assert "start-backend-off-traffic" not in visited


def test_backend_contract_check_requires_configured_reviewed_mentor_state():
    command, _timeout = RUNNER.command_for_action("contract-check")
    script = command[-1]
    assert "/health/ready" in script
    assert "/api/mentors" in script
    assert "MENTOR_DATA_EXPECTED_PUBLISHED_COUNT" in script
    assert "MENTOR_DATA_EXPECTED_MATCH_CANDIDATE_COUNT" in script
    assert "len(mentors.get('data',[])) <= 20" in script
    assert "meta.get('published_records') == expected" in script
    assert "meta.get('match_candidate_records') == expected_match" in script


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


def test_workflow_failure_records_stable_step_without_child_output():
    visited: list[str] = []
    child_canary = "synthetic-child-output-must-not-escape"

    def fail_migration(step, _runner):
        visited.append(step)
        if step == "migration":
            raise RUNNER.RunnerError("action_failed") from RuntimeError(child_canary)

    with pytest.raises(RUNNER.RunnerError, match="action_failed") as failure:
        RUNNER.execute_workflow(
            "first-deploy-plan",
            step_executor=fail_migration,
        )
    assert failure.value.failed_step_id == "migration"
    assert child_canary not in str(failure.value)
    assert visited[-1] == "migration"
    assert "backup" not in visited


def test_subprocess_timeout_is_redacted_and_stable(monkeypatch):
    canary = "synthetic-timeout-output-must-not-escape"

    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            ["synthetic-command", canary],
            1,
            output=canary,
            stderr=canary,
        )

    monkeypatch.setattr(RUNNER.subprocess, "run", timeout_run)
    with pytest.raises(RUNNER.RunnerError, match="subprocess_timeout") as failure:
        RUNNER._run_command(["synthetic-command", canary], 1)
    assert failure.value.exit_code == 124
    assert canary not in str(failure.value)


def test_backup_timeout_cleans_exact_one_shot_and_records_step(monkeypatch):
    cleanup_calls: list[tuple[str, object]] = []
    lock_probes: list[bool] = []

    monkeypatch.setattr(RUNNER, "_resource_gate", lambda *_args: None)
    monkeypatch.setattr(
        RUNNER,
        "_deployment_identifiers",
        lambda: {
            "PROD_DATABASE_NAME": "tsing_radar",
            "PROD_DATABASE_USER": "tsing_radar",
            "STAGE_DATABASE_NAME": "tsing_radar_stage",
            "STAGE_DATABASE_USER": "tsing_radar_stage",
        },
    )
    monkeypatch.setattr(
        RUNNER,
        "probe_job_lock",
        lambda *_args: lock_probes.append(True),
    )
    monkeypatch.setattr(
        RUNNER,
        "cleanup_one_shot_action",
        lambda action, runner: cleanup_calls.append((action, runner)),
    )

    def timeout_runner(arguments, timeout):
        raise subprocess.TimeoutExpired(arguments, timeout, output="canary")

    def execute_backup(_step, runner, *, backup_file=None):
        del backup_file
        return RUNNER._execute_step("backup", runner)

    with pytest.raises(
        RUNNER.RunnerError,
        match="action_timeout_cleanup_attempted",
    ) as failure:
        RUNNER.execute_workflow(
            "resume-after-migration-plan",
            runner=timeout_runner,
            step_executor=lambda step, runner: (
                execute_backup(step, runner)
                if step == "backup"
                else None
            ),
        )
    assert failure.value.exit_code == 124
    assert failure.value.failed_step_id == "backup"
    assert cleanup_calls == [("backup", timeout_runner)]
    assert len(lock_probes) == 2
    assert "canary" not in str(failure.value)


def test_one_shot_timeout_cleanup_uses_exact_labels_and_no_volumes():
    calls: list[list[str]] = []

    def fake_runner(arguments, _timeout):
        command = list(arguments)
        calls.append(command)
        if command[:2] == ["docker", "ps"]:
            return _completed(stdout="backup-container-id\n")
        if command[:2] == ["docker", "inspect"]:
            return _completed(
                stdout=json.dumps(
                    {
                        "com.docker.compose.project": RUNNER.PROJECT,
                        "com.docker.compose.service": "backup",
                    }
                )
            )
        return _completed()

    RUNNER.cleanup_one_shot_action("backup", fake_runner)
    flattened = " ".join(part for command in calls for part in command)
    assert f"label=com.docker.compose.project={RUNNER.PROJECT}" in flattened
    assert "label=com.docker.compose.service=backup" in flattened
    assert [command[-1] for command in calls if command[:2] == ["docker", "stop"]] == [
        "backup-container-id"
    ]
    assert "down" not in flattened
    assert "--volumes" not in flattened
    assert "volume rm" not in flattened


def test_runner_failure_report_emits_step_id_without_raw_output(
    monkeypatch,
    capsys,
):
    child_canary = "synthetic-secret-like-child-output"

    def fail_action(_action):
        raise RUNNER.RunnerError(
            "action_failed",
            failed_step_id="migration",
        ) from RuntimeError(child_canary)

    monkeypatch.setattr(RUNNER, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(RUNNER, "execute_action", fail_action)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(checker.RUNNER_PATH),
            "--action",
            "first-deploy-plan",
            "--mode",
            "execute",
        ],
    )
    assert RUNNER.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "schema_version": "l2-deploy-result-v1",
        "status": "failed",
        "action_id": "first-deploy-plan",
        "reason": "action_failed",
        "values_or_host_metadata_emitted": False,
        "failed_step_id": "migration",
    }
    assert child_canary not in json.dumps(report)


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


def test_restore_timeout_is_redacted_and_cleanup_is_attempted(monkeypatch):
    cleaned: list[bool] = []

    def timeout_runner(arguments, timeout):
        raise subprocess.TimeoutExpired(arguments, timeout, output="restore-canary")

    monkeypatch.setattr(
        RUNNER,
        "cleanup_restore_services",
        lambda _runner: cleaned.append(True),
    )
    with pytest.raises(
        RUNNER.RunnerError,
        match="restore_check_timeout_cleanup_attempted",
    ) as failure:
        RUNNER._run_restore_check(
            timeout_runner,
            "tsing_radar-20260805T001122Z-Ab12z9.dump",
        )
    assert failure.value.exit_code == 124
    assert cleaned == [True]
    assert "restore-canary" not in str(failure.value)


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

    assert 'mktemp "${temporary_prefix}XXXXXX"' in backup_script
    assert 'mktemp "${checksum_prefix}XXXXXX"' in backup_script
    assert 'target="/backups/${DATABASE_NAME}-${stamp}-${token}.dump"' in backup_script
    assert "XXXXXX.dump" not in backup_script
    assert "XXXXXX.sha256" not in backup_script
    assert 'ln "$temporary" "$target"' in backup_script
    assert 'sha256sum -c "$(basename "${target}.sha256")"' in backup_script
    assert backup_script.index("sha256sum -c") < backup_script.index("backup_created=")
    assert "BACKUP_FILE: ${BACKUP_FILE" not in jobs
    assert "database secret unavailable or invalid" in backup_script
    assert 'od -An -v -t x1 "$secret_path"' in backup_script
    assert "--no-password" in backup_script
    assert "PGCONNECT_TIMEOUT=10" in backup_script
    assert "timeout -s TERM -k 10 840 pg_dump" in backup_script

    restore_script = (
        REPOSITORY_ROOT
        / "deploy"
        / "production"
        / "scripts"
        / "postgres-restore-check.sh"
    ).read_text(encoding="utf-8")
    assert "restore secret unavailable or invalid" in restore_script
    assert 'od -An -v -t x1 "$secret_path"' in restore_script
    assert "pg_restore --no-password" in restore_script
    assert "psql --no-password" in restore_script
    assert "--no-owner --no-acl" in restore_script
    assert "PGCONNECT_TIMEOUT=10" in restore_script
    assert "timeout -s TERM -k 10 840 pg_restore" in restore_script
    assert jobs.count('cap_add: ["DAC_OVERRIDE"]') == 2


def test_migration_container_probe_requires_exact_app_pythonpath(monkeypatch):
    calls: list[list[str]] = []

    def fake_docker(*arguments, **_kwargs):
        command = list(arguments)
        calls.append(command)
        environment = next(
            (
                command[index + 1]
                for index, value in enumerate(command[:-1])
                if value == "--env" and command[index + 1].startswith("PYTHONPATH=")
            ),
            None,
        )
        return _completed(returncode=0 if environment == "PYTHONPATH=/app" else 1)

    monkeypatch.setattr(checker, "_docker", fake_docker)
    report = checker._container_migration_import_contract()

    assert report["status"] == "passed"
    assert report["observed_exit_codes"] == {
        "exact": 0,
        "missing": 1,
        "drifted": 1,
    }
    assert len(calls) == 3
    assert all("--network" in call and "none" in call for call in calls)
    assert all("--read-only" in call and "--pull" in call for call in calls)
    assert all("migration_with_lock.py" in " ".join(call) for call in calls)


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
