"""Fail-closed production deployment action runner.

The CLI accepts action identifiers only.  Compose files, project name,
services, environment file and lock path are fixed here so an operator cannot
turn the runner into an arbitrary Docker command launcher.  Secret values and
subprocess output are never emitted.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import stat
import subprocess
import sys
import re
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy" / "production"
ENV_FILE = DEPLOY / "production.env"
PROJECT = "tsing-radar-prod"
HOST_JOB_LOCK = Path("/var/lib/tsing-radar/job.lock")

INFRA = DEPLOY / "compose.infra.yml"
PROD = DEPLOY / "compose.prod.yml"
JOBS = DEPLOY / "compose.jobs.yml"
L1_CHECKER = ROOT / "scripts" / "check_l1_production.py"
SECRET_PREFLIGHT = DEPLOY / "scripts" / "secret_preflight.py"

PROD_SECRET_ROOT = Path("/etc/tsing-radar/secrets/prod")
STAGE_SECRET_ROOT = Path("/etc/tsing-radar/secrets/stage")
BOOTSTRAP_SECRET_ROOT = Path("/etc/tsing-radar/secrets/bootstrap")

ACTION_IDS = (
    "first-deploy-plan",
    "resume-after-migration-plan",
    "upgrade-plan",
    "lock-probe",
    "preflight",
    "infra-health",
    "prod-db-provision",
    "prod-db-verification",
    "migration",
    "post-migration-verification",
    "backup",
    "restore-check",
    "start-backend-off-traffic",
    "contract-check",
    "start-frontend",
)

FIRST_DEPLOY_PLAN = (
    "preflight",
    "infra-health",
    "prod-db-provision",
    "prod-db-verification",
    "migration",
    "start-backend-off-traffic",
    "contract-check",
    "backup",
    "restore-check",
    "start-frontend",
)

RESUME_AFTER_MIGRATION_PLAN = (
    "preflight",
    "infra-health",
    "post-migration-verification",
    "start-backend-off-traffic",
    "contract-check",
    "backup",
    "restore-check",
    "start-frontend",
)

UPGRADE_PLAN = (
    "preflight",
    "infra-health",
    "backup",
    "restore-check",
    "compatibility-gate-requires-separate-authorization",
)

RESOURCE_COMBINATION = {
    "preflight": "default",
    "infra-health": "default",
    "prod-db-provision": "database-setup",
    "prod-db-verification": "database-setup",
    "migration": "migration",
    "post-migration-verification": "migration",
    "backup": "backup",
    "restore-check": "restore-check",
    "start-backend-off-traffic": "default",
    "contract-check": "default",
    "start-frontend": "default",
}

LOCKED_ACTIONS = {
    "prod-db-provision",
    "prod-db-verification",
    "migration",
    "post-migration-verification",
    "backup",
    "restore-check",
}

RESTORE_SERVICES = ("restore-check-db", "restore-check")
WORKFLOW_ACTIONS = (
    "first-deploy-plan",
    "resume-after-migration-plan",
    "upgrade-plan",
)
COMPATIBILITY_GATE = "compatibility-gate-requires-separate-authorization"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

DB_VERIFICATION_CODE = r"""
import os
from pathlib import Path
import psycopg

def required(name):
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit("database verification configuration missing")
    return value

def secret(name):
    path = Path(required(name))
    if not path.is_file() or path.is_symlink():
        raise SystemExit("database verification secret invalid")
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not value:
        raise SystemExit("database verification secret empty")
    return value

host = required("DATABASE_HOST")
bootstrap_user = required("DATABASE_BOOTSTRAP_USER")
target_db = required("TARGET_DATABASE_NAME")
target_user = required("TARGET_DATABASE_USER")
protected_db = required("PROTECTED_DATABASE_NAME")
protected_user = required("PROTECTED_DATABASE_USER")
bootstrap_password = secret("DATABASE_BOOTSTRAP_PASSWORD_FILE")
target_password = secret("TARGET_DATABASE_PASSWORD_FILE")

with psycopg.connect(
    host=host,
    dbname="postgres",
    user=bootstrap_user,
    password=bootstrap_password,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT oid, rolsuper, rolcreatedb, rolcreaterole, rolreplication "
            "FROM pg_roles WHERE rolname = %s",
            (target_user,),
        )
        target_role = cursor.fetchone()
        if target_role is None or any(target_role[1:]):
            raise SystemExit("application role privilege verification failed")
        target_role_oid = target_role[0]
        cursor.execute("SELECT oid FROM pg_roles WHERE rolname = %s", (bootstrap_user,))
        bootstrap_role = cursor.fetchone()
        if bootstrap_role is None:
            raise SystemExit("bootstrap role verification failed")
        bootstrap_role_oid = bootstrap_role[0]
        cursor.execute(
            "SELECT oid, datdba FROM pg_database WHERE datname = %s",
            (target_db,),
        )
        target_database = cursor.fetchone()
        if target_database is None or target_database[1] != target_role_oid:
            raise SystemExit("database owner verification failed")
        target_database_oid = target_database[0]
        cursor.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_database d "
            "CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) a "
            "WHERE d.oid = %s AND a.grantee = 0 AND a.privilege_type = 'CONNECT'"
            ")",
            (target_database_oid,),
        )
        if cursor.fetchone()[0]:
            raise SystemExit("public database connect verification failed")
        cursor.execute(
            "SELECT rolname FROM pg_roles WHERE rolcanlogin "
            "AND oid NOT IN (%s, %s) "
            "AND has_database_privilege(oid, %s, 'CONNECT') LIMIT 1",
            (target_role_oid, bootstrap_role_oid, target_database_oid),
        )
        if cursor.fetchone() is not None:
            raise SystemExit("unexpected database login privilege")
        cursor.execute("SELECT oid FROM pg_roles WHERE rolname = %s", (protected_user,))
        protected_role = cursor.fetchone()
        cursor.execute("SELECT oid FROM pg_database WHERE datname = %s", (protected_db,))
        protected_database = cursor.fetchone()
        if (protected_role is None) != (protected_database is None):
            raise SystemExit("stage database namespace is incomplete")
        if protected_role is not None:
            cursor.execute(
                "SELECT has_database_privilege(%s, %s, 'CONNECT'), "
                "has_database_privilege(%s, %s, 'CONNECT')",
                (
                    protected_role[0],
                    target_database_oid,
                    target_role_oid,
                    protected_database[0],
                ),
            )
            stage_to_prod, prod_to_stage = cursor.fetchone()
            if stage_to_prod or prod_to_stage:
                raise SystemExit("prod stage connection isolation failed")

with psycopg.connect(
    host=host,
    dbname=target_db,
    user=bootstrap_user,
    password=bootstrap_password,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN "
            "('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'"
        )
        if cursor.fetchone()[0] != 0:
            raise SystemExit("first deployment database is not empty")
        cursor.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_namespace n "
            "CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a "
            "WHERE n.nspname = 'public' AND a.grantee = 0 AND a.privilege_type = 'CREATE'"
            ")"
        )
        if cursor.fetchone()[0]:
            raise SystemExit("public schema create verification failed")

with psycopg.connect(
    host=host,
    dbname=target_db,
    user=target_user,
    password=target_password,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_user = %s, "
            "has_database_privilege(current_user, current_database(), 'CONNECT'), "
            "has_schema_privilege(current_user, 'public', 'USAGE'), "
            "has_schema_privilege(current_user, 'public', 'CREATE')",
            (target_user,),
        )
        if not all(cursor.fetchone()):
            raise SystemExit("application role access verification failed")

print("prod database verification passed")
""".strip()


class RunnerError(RuntimeError):
    """Stable runner failure that does not contain subprocess output."""

    def __init__(
        self,
        reason: str,
        exit_code: int = 1,
        *,
        failed_step_id: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code
        self.failed_step_id = failed_step_id


class RunnerInterrupted(RunnerError):
    def __init__(self) -> None:
        super().__init__("interrupted_cleanup_attempted", 130)


CommandRunner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


def _safe_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SYSTEMROOT",
        "USERPROFILE",
    )
    return {name: os.environ[name] for name in allowed if name in os.environ}


def _run_command(arguments: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def _deployment_identifiers(path: Path = ENV_FILE) -> dict[str, str]:
    required_names = {
        "PROD_DATABASE_NAME",
        "PROD_DATABASE_USER",
        "STAGE_DATABASE_NAME",
        "STAGE_DATABASE_USER",
    }
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RunnerError("fixed_environment_file_missing", 78) from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 65536:
        raise RunnerError("fixed_environment_file_invalid", 78)
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise RunnerError("fixed_environment_file_unreadable", 78) from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in required_names:
            continue
        if name in values:
            raise RunnerError("database_identifier_duplicate", 78)
        value = value.strip()
        if not IDENTIFIER.fullmatch(value):
            raise RunnerError("database_identifier_invalid", 78)
        values[name] = value
    if set(values) != required_names:
        raise RunnerError("database_identifier_missing", 78)
    if values["PROD_DATABASE_NAME"] == values["STAGE_DATABASE_NAME"]:
        raise RunnerError("database_namespace_reused", 78)
    if values["PROD_DATABASE_USER"] == values["STAGE_DATABASE_USER"]:
        raise RunnerError("database_role_reused", 78)
    return values


def _compose_prefix(*files: Path, profile: str | None = None) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        str(ENV_FILE),
    ]
    for path in files:
        command.extend(("--file", str(path)))
    if profile is not None:
        command.extend(("--profile", profile))
    return command


def command_for_action(
    action_id: str,
    identifiers: dict[str, str] | None = None,
) -> tuple[list[str], int]:
    """Return the fixed argv and timeout for a non-restore executable action."""

    if action_id == "prod-db-verification":
        if identifiers is None:
            raise RunnerError("database_identifiers_required", 78)
        return (
            [
                *_compose_prefix(INFRA, JOBS, profile="database-setup"),
                "run",
                "--rm",
                "--env",
                f"PROTECTED_DATABASE_NAME={identifiers['STAGE_DATABASE_NAME']}",
                "--env",
                f"PROTECTED_DATABASE_USER={identifiers['STAGE_DATABASE_USER']}",
                "prod-db-provision",
                "python",
                "-c",
                DB_VERIFICATION_CODE,
            ],
            180,
        )

    mapping: dict[str, tuple[list[str], int]] = {
        "preflight": (
            [
                sys.executable,
                str(SECRET_PREFLIGHT),
                "--secret-root",
                str(PROD_SECRET_ROOT),
                "--stage-secret-root",
                str(STAGE_SECRET_ROOT),
                "--bootstrap-secret-root",
                str(BOOTSTRAP_SECRET_ROOT),
            ],
            30,
        ),
        "infra-health": (
            [*_compose_prefix(INFRA), "up", "--detach", "--wait", "--wait-timeout", "900"],
            930,
        ),
        "prod-db-provision": (
            [
                *_compose_prefix(INFRA, JOBS, profile="database-setup"),
                "run",
                "--rm",
                "prod-db-provision",
            ],
            180,
        ),
        "migration": (
            [
                *_compose_prefix(INFRA, JOBS, profile="migration"),
                "run",
                "--rm",
                "migration",
            ],
            300,
        ),
        "post-migration-verification": (
            [
                *_compose_prefix(INFRA, JOBS, profile="resume-verification"),
                "run",
                "--rm",
                "post-migration-verification",
            ],
            300,
        ),
        "backup": (
            [
                *_compose_prefix(INFRA, JOBS, profile="backup"),
                "run",
                "--rm",
                "backup",
            ],
            900,
        ),
        "start-backend-off-traffic": (
            [
                *_compose_prefix(INFRA, PROD),
                "up",
                "--detach",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "180",
                "backend",
            ],
            210,
        ),
        "contract-check": (
            [
                *_compose_prefix(INFRA, PROD),
                "exec",
                "--no-TTY",
                "backend",
                "python",
                "-c",
                (
                    "import json,urllib.request;"
                    "data=json.load(urllib.request.urlopen("
                    "'http://127.0.0.1:8000/health/ready',timeout=5));"
                    "assert data.get('status') in {'ready','ok'};"
                    "mentors=json.load(urllib.request.urlopen("
                    "'http://127.0.0.1:8000/api/mentors',timeout=5));"
                    "assert mentors.get('data') == [];"
                    "assert mentors.get('meta') == {"
                    "'total_records':0,'published_records':0,"
                    "'withheld_records':0,'policy':'verified_only'}"
                ),
            ],
            30,
        ),
        "start-frontend": (
            [
                *_compose_prefix(INFRA, PROD),
                "up",
                "--detach",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "120",
                "frontend",
            ],
            150,
        ),
    }
    if action_id not in mapping:
        raise RunnerError("action_not_executable", 64)
    return mapping[action_id]


def _resource_gate(action_id: str, runner: CommandRunner) -> None:
    combination = RESOURCE_COMBINATION.get(action_id)
    if combination is None:
        return
    result = runner(
        [sys.executable, str(L1_CHECKER), "--require-combination", combination],
        120,
    )
    if result.returncode != 0:
        raise RunnerError("resource_gate_failed")


def probe_job_lock(path: Path = HOST_JOB_LOCK) -> None:
    """Acquire and immediately release the host lock; never hold across Compose."""

    if os.name != "posix":
        raise RunnerError("lock_probe_requires_posix", 78)
    import fcntl

    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        errno_label = exc.errno if isinstance(exc.errno, int) else "unknown"
        raise RunnerError(f"lock_file_unavailable_e{errno_label}", 78) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RunnerError("lock_file_invalid", 78)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerError("job_lock_busy", 75) from exc
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(descriptor)


def _restore_container_ids(runner: CommandRunner) -> dict[str, str]:
    found: dict[str, str] = {}
    for service in RESTORE_SERVICES:
        result = runner(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={PROJECT}",
                "--filter",
                f"label=com.docker.compose.service={service}",
            ],
            20,
        )
        if result.returncode != 0:
            raise RunnerError("restore_cleanup_discovery_failed")
        identifiers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(identifiers) > 1:
            raise RunnerError("restore_cleanup_ambiguous")
        if identifiers:
            found[service] = identifiers[0]
    return found


def cleanup_restore_services(runner: CommandRunner = _run_command) -> None:
    """Stop and remove only the two label-verified temporary containers.

    No volume operation exists in this function.  Failure leaves the objects in
    place and returns a stable manual-action reason.
    """

    containers = _restore_container_ids(runner)
    for service, identifier in containers.items():
        inspect_result = runner(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                identifier,
            ],
            20,
        )
        if inspect_result.returncode != 0:
            raise RunnerError("restore_cleanup_inspect_failed")
        try:
            labels = json.loads(inspect_result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RunnerError("restore_cleanup_labels_invalid") from exc
        if (
            labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != service
        ):
            raise RunnerError("restore_cleanup_label_mismatch")
    for service in reversed(RESTORE_SERVICES):
        identifier = containers.get(service)
        if identifier is None:
            continue
        stopped = runner(["docker", "stop", "--time", "10", identifier], 30)
        if stopped.returncode != 0:
            raise RunnerError("restore_cleanup_stop_failed_manual_action_required")
        removed = runner(["docker", "rm", identifier], 30)
        if removed.returncode != 0:
            raise RunnerError("restore_cleanup_remove_failed_manual_action_required")


def _parse_backup_created(stdout: str, database_name: str) -> str:
    """Return the one backup created by the immediately preceding job.

    The backup script emits this receipt only after the dump and its checksum
    both exist and the checksum has been verified.  A random suffix makes the
    filename unique while the strict database prefix prevents a receipt from a
    different namespace being handed to restore-check.
    """

    if len(stdout.encode("utf-8", errors="replace")) > 65536:
        raise RunnerError("backup_receipt_oversized", 78)
    receipts = [
        line.removeprefix("backup_created=")
        for line in stdout.splitlines()
        if line.startswith("backup_created=")
    ]
    if len(receipts) != 1:
        raise RunnerError("backup_receipt_invalid", 78)
    filename = receipts[0]
    pattern = re.compile(
        rf"^{re.escape(database_name)}-\d{{8}}T\d{{6}}Z-[A-Za-z0-9]{{6}}\.dump$"
    )
    if not pattern.fullmatch(filename):
        raise RunnerError("backup_receipt_filename_invalid", 78)
    return filename


def _run_restore_check(runner: CommandRunner, backup_file: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}-\d{8}T\d{6}Z-[A-Za-z0-9]{6}\.dump", backup_file):
        raise RunnerError("backup_receipt_filename_invalid", 78)
    start_database = [
        *_compose_prefix(INFRA, JOBS, profile="restore-check"),
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "180",
        "restore-check-db",
    ]
    restore = [
        *_compose_prefix(INFRA, JOBS, profile="restore-check"),
        "run",
        "--rm",
        "--no-deps",
        "--env",
        f"BACKUP_FILE={backup_file}",
        "restore-check",
    ]
    primary_error: RunnerError | None = None
    try:
        database_result = runner(start_database, 210)
        if database_result.returncode != 0:
            primary_error = RunnerError("restore_check_failed")
        else:
            restore_result = runner(restore, 1200)
            if restore_result.returncode != 0:
                primary_error = RunnerError("restore_check_failed")
    finally:
        try:
            cleanup_restore_services(runner)
        except RunnerError as cleanup_error:
            raise cleanup_error
    if primary_error is not None:
        raise primary_error


def _install_signal_handlers() -> None:
    def interrupt(_signum: int, _frame: object) -> None:
        raise RunnerInterrupted()

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupt)


def _execute_step(
    action_id: str,
    runner: CommandRunner,
    *,
    backup_file: str | None = None,
) -> str | None:
    _resource_gate(action_id, runner)
    if action_id in LOCKED_ACTIONS:
        # Probe and release.  The job-lock.sh entrypoint is the sole lock owner
        # while the Compose job actually runs.
        probe_job_lock()
    if action_id == "restore-check":
        if backup_file is None:
            raise RunnerError("workflow_backup_receipt_missing", 78)
        _run_restore_check(runner, backup_file)
        probe_job_lock()
        return None
    identifiers = (
        _deployment_identifiers()
        if action_id in {"prod-db-verification", "backup"}
        else None
    )
    command, timeout = command_for_action(action_id, identifiers)
    result = runner(command, timeout)
    if result.returncode != 0:
        raise RunnerError("action_failed")
    created_backup = None
    if action_id == "backup":
        if identifiers is None:
            raise RunnerError("database_identifiers_required", 78)
        created_backup = _parse_backup_created(
            result.stdout,
            identifiers["PROD_DATABASE_NAME"],
        )
    if action_id in LOCKED_ACTIONS:
        probe_job_lock()
    return created_backup


WorkflowStepExecutor = Callable[[str, CommandRunner], None]


def _validate_workflow_contract(action_id: str, steps: tuple[str, ...]) -> None:
    if action_id == "first-deploy-plan":
        if steps != FIRST_DEPLOY_PLAN:
            raise RunnerError("first_deploy_workflow_contract_invalid", 78)
        required_order = (
            "prod-db-provision",
            "prod-db-verification",
            "migration",
            "backup",
            "restore-check",
            "start-frontend",
        )
        positions = [steps.index(item) for item in required_order]
        if positions != sorted(positions):
            raise RunnerError("first_deploy_workflow_order_invalid", 78)
        return
    if action_id == "upgrade-plan":
        if steps != UPGRADE_PLAN or steps[-1] != COMPATIBILITY_GATE:
            raise RunnerError("upgrade_workflow_contract_invalid", 78)
        if "migration" in steps:
            raise RunnerError("upgrade_migration_not_authorized", 77)
        return
    if action_id == "resume-after-migration-plan":
        if steps != RESUME_AFTER_MIGRATION_PLAN:
            raise RunnerError("resume_workflow_contract_invalid", 78)
        forbidden = {"prod-db-provision", "prod-db-verification", "migration"}
        if forbidden.intersection(steps):
            raise RunnerError("resume_workflow_repeats_initialization", 78)
        required_order = (
            "post-migration-verification",
            "start-backend-off-traffic",
            "contract-check",
            "backup",
            "restore-check",
            "start-frontend",
        )
        positions = [steps.index(item) for item in required_order]
        if positions != sorted(positions):
            raise RunnerError("resume_workflow_order_invalid", 78)
        return
    raise RunnerError("workflow_not_executable", 64)


def execute_workflow(
    action_id: str,
    runner: CommandRunner = _run_command,
    step_executor: WorkflowStepExecutor | None = None,
) -> None:
    steps = plan_for(action_id)
    _validate_workflow_contract(action_id, steps)
    backup_file: str | None = None
    for step in steps:
        if step == COMPATIBILITY_GATE:
            raise RunnerError(
                "upgrade_compatibility_requires_separate_approval",
                77,
                failed_step_id=step,
            )
        try:
            if step_executor is not None:
                step_executor(step, runner)
                continue
            created_backup = _execute_step(step, runner, backup_file=backup_file)
        except RunnerError as exc:
            if exc.failed_step_id is not None:
                raise
            raise RunnerError(
                exc.reason,
                exc.exit_code,
                failed_step_id=step,
            ) from exc
        if step == "backup":
            if created_backup is None:
                raise RunnerError(
                    "workflow_backup_receipt_missing",
                    78,
                    failed_step_id=step,
                )
            backup_file = created_backup


def execute_action(action_id: str, runner: CommandRunner = _run_command) -> None:
    if action_id not in ACTION_IDS:
        raise RunnerError("unknown_action", 64)
    if action_id == "lock-probe":
        probe_job_lock()
        return
    if action_id not in WORKFLOW_ACTIONS:
        raise RunnerError("single_action_execute_forbidden", 64)
    if not ENV_FILE.is_file():
        raise RunnerError("fixed_environment_file_missing", 78)
    execute_workflow(action_id, runner)


def plan_for(action_id: str) -> tuple[str, ...]:
    if action_id == "first-deploy-plan":
        return FIRST_DEPLOY_PLAN
    if action_id == "resume-after-migration-plan":
        return RESUME_AFTER_MIGRATION_PLAN
    if action_id == "upgrade-plan":
        return UPGRADE_PLAN
    if action_id in ACTION_IDS:
        return (action_id,)
    raise RunnerError("unknown_action", 64)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=ACTION_IDS)
    parser.add_argument("--mode", required=True, choices=("plan", "execute"))
    args = parser.parse_args()
    _install_signal_handlers()
    try:
        if args.mode == "plan":
            report = {
                "schema_version": "l2-deploy-plan-v1",
                "status": "planned",
                "action_id": args.action,
                "steps": list(plan_for(args.action)),
                "values_or_host_metadata_emitted": False,
            }
        else:
            execute_action(args.action)
            report = {
                "schema_version": "l2-deploy-result-v1",
                "status": "passed",
                "action_id": args.action,
                "values_or_host_metadata_emitted": False,
            }
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except RunnerError as exc:
        failure_report = {
            "schema_version": "l2-deploy-result-v1",
            "status": "failed",
            "action_id": args.action,
            "reason": exc.reason,
            "values_or_host_metadata_emitted": False,
        }
        if exc.failed_step_id is not None:
            failure_report["failed_step_id"] = exc.failed_step_id
        print(
            json.dumps(
                failure_report,
                ensure_ascii=False,
            )
        )
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
