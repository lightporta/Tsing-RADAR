"""Ephemeral local-container checks for L1 network, health and lock contracts."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "production"
PREFIX = "tsing-radar-l1-check-"


def _run(arguments: list[str], *, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if completed.returncode not in expected:
        raise RuntimeError(f"container check command failed: {arguments[:3]}")
    return completed


def _docker(*arguments: str, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    return _run(["docker", *arguments], expected=expected)


def _mount(path: Path, target: str) -> str:
    return f"{path.resolve()}:{target}:ro"


def _mount_rw(path: Path, target: str) -> str:
    return f"{path.resolve()}:{target}"


def _wait_exec(name: str, command: list[str], *, attempts: int = 30) -> bool:
    for _ in range(attempts):
        result = _docker("exec", name, *command, expected=set(range(256)))
        if result.returncode == 0:
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    generation = uuid.uuid4().hex[:10]
    names = {
        key: f"{PREFIX}{generation}-{key}"
        for key in (
            "redis-good",
            "redis-wrong",
            "redis-missing",
            "clamd",
            "media-backend",
            "media-gateway",
            "postgres",
            "lock-holder",
            "job-lock-holder",
        )
    }
    network = f"{PREFIX}{generation}-network"
    created: list[str] = []
    checks: list[dict[str, object]] = []
    dummy_redis = "dummyRedisSecret_0123456789abcdef"
    wrong_redis = "wrongRedisSecret_0123456789abcdef"
    dummy_postgres = "dummyPostgresSecret_0123456789abcdef"
    dummy_prod_app = "dummyProdAppSecret_0123456789abcdef"
    dummy_stage_app = "dummyStageAppSecret_0123456789abcdef"
    try:
        _docker("network", "create", network)
        with tempfile.TemporaryDirectory(prefix=PREFIX) as temporary:
            temporary_path = Path(temporary)
            good_secret = temporary_path / "redis-good"
            wrong_secret = temporary_path / "redis-wrong"
            good_secret.write_text(dummy_redis, encoding="utf-8")
            wrong_secret.write_text(wrong_redis, encoding="utf-8")
            redis_entrypoint = DEPLOY / "scripts" / "redis-entrypoint.sh"
            redis_health = DEPLOY / "scripts" / "redis-healthcheck.sh"

            _docker(
                "run", "-d", "--name", names["redis-good"],
                "-v", _mount(good_secret, "/run/secrets/redis_password"),
                "-v", _mount(redis_entrypoint, "/opt/redis-entrypoint.sh"),
                "-v", _mount(redis_health, "/opt/redis-healthcheck.sh"),
                "--entrypoint", "/bin/sh", "redis:7-alpine", "/opt/redis-entrypoint.sh",
            )
            created.append(names["redis-good"])
            redis_positive = _wait_exec(
                names["redis-good"],
                ["/bin/sh", "/opt/redis-healthcheck.sh"],
            )

            _docker(
                "run", "-d", "--name", names["redis-wrong"],
                "-v", _mount(wrong_secret, "/run/secrets/redis_password"),
                "-v", _mount(redis_health, "/opt/redis-healthcheck.sh"),
                "redis:7-alpine", "redis-server", "--requirepass", dummy_redis,
            )
            created.append(names["redis-wrong"])
            time.sleep(0.5)
            wrong_result = _docker(
                "exec", names["redis-wrong"], "/bin/sh", "/opt/redis-healthcheck.sh",
                expected={0, 1},
            )

            _docker(
                "run", "-d", "--name", names["redis-missing"],
                "-v", _mount(redis_health, "/opt/redis-healthcheck.sh"),
                "redis:7-alpine",
            )
            created.append(names["redis-missing"])
            time.sleep(0.5)
            missing_result = _docker(
                "exec", names["redis-missing"], "/bin/sh", "/opt/redis-healthcheck.sh",
                expected={0, 1},
            )
            redis_logs = "".join(
                _docker("logs", name).stdout
                for name in (names["redis-good"], names["redis-wrong"], names["redis-missing"])
            )
            checks.append(
                {
                    "id": "redis.container_health_secret_contract",
                    "passed": redis_positive
                    and wrong_result.returncode != 0
                    and missing_result.returncode != 0
                    and dummy_redis not in redis_logs
                    and wrong_redis not in redis_logs,
                }
            )

            clamd_server = (
                "import socket,struct\n"
                "def exact(c,n):\n b=b''\n while len(b)<n:\n  x=c.recv(n-len(b))\n  if not x: raise EOFError\n  b+=x\n return b\n"
                "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',3310)); s.listen(); print('READY',flush=True)\n"
                "while True:\n c,_=s.accept()\n try:\n  exact(c,10)\n  while True:\n   n=struct.unpack('>I',exact(c,4))[0]\n   if n==0: break\n   exact(c,n)\n  c.sendall(b'stream: OK\\0')\n finally:\n  c.close()"
            )
            _docker(
                "run", "-d", "--name", names["clamd"], "--network", network,
                "--network-alias", "clamav", "python:3.11-slim", "python", "-u", "-c", clamd_server,
            )
            created.append(names["clamd"])
            server_ready = False
            for _ in range(30):
                if "READY" in _docker("logs", names["clamd"]).stdout:
                    server_ready = True
                    break
                time.sleep(0.25)
            scan_positive = _docker(
                "run", "--rm", "--network", network,
                "-e", "FILE_SCAN_MODE=clamav", "-e", "CLAMAV_HOST=clamav",
                "-e", "CLAMAV_PORT=3310", "tsing-radar-backend:local", "python", "-c",
                "from app.services.file_scanning import scan_payload; assert scan_payload(b'%PDF-1.4\\n%%EOF','.pdf').status=='clean'",
                expected={0, 1},
            )
            scan_negative = _docker(
                "run", "--rm", "--network", network,
                "-e", "FILE_SCAN_MODE=clamav", "-e", "CLAMAV_HOST=missing-scanner",
                "-e", "CLAMAV_TIMEOUT_SECONDS=1", "tsing-radar-backend:local", "python", "-c",
                "from app.services.file_scanning import scan_payload,ScanUnavailableError;\ntry: scan_payload(b'%PDF-1.4\\n%%EOF','.pdf'); raise SystemExit(2)\nexcept ScanUnavailableError: pass",
                expected={0, 1, 2},
            )
            checks.append(
                {
                    "id": "scanner.shared_network_and_fail_closed",
                    "passed": server_ready
                    and scan_positive.returncode == 0
                    and scan_negative.returncode == 0,
                    "observed_exit_codes": {
                        "server_ready": int(server_ready),
                        "reachable_scan": scan_positive.returncode,
                        "unavailable_scan": scan_negative.returncode,
                    },
                }
            )

            media_backend_code = (
                "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
                "class H(BaseHTTPRequestHandler):\n"
                " def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'pdf')\n"
                " def log_message(self,*a): pass\n"
                "HTTPServer(('0.0.0.0',8000),H).serve_forever()"
            )
            _docker(
                "run", "-d", "--name", names["media-backend"], "--network", network,
                "--network-alias", "backend", "python:3.11-slim", "python", "-u", "-c", media_backend_code,
            )
            created.append(names["media-backend"])
            media_config = DEPLOY / "media-gateway" / "nginx.conf"
            _docker(
                "run", "-d", "--name", names["media-gateway"], "--network", network,
                "--network-alias", "media", "-v", _mount(media_config, "/etc/nginx/nginx.conf"),
                "--entrypoint", "nginx", "tsing-radar-frontend:local", "-g", "daemon off;",
            )
            created.append(names["media-gateway"])
            canary = "canaryBearerToken_0123456789abcdef"
            media_client = None
            for _ in range(20):
                media_client = _docker(
                    "run", "--rm", "--network", network, "python:3.11-slim", "python", "-c",
                    f"import urllib.request; assert urllib.request.urlopen('http://media:8080/v1/attachments/{canary}',timeout=2).status==200",
                    expected=set(range(256)),
                )
                if media_client.returncode == 0:
                    break
                time.sleep(0.25)
            assert media_client is not None
            media_logs = _docker("logs", names["media-gateway"]).stdout
            checks.append(
                {
                    "id": "media.container_access_log_token_redaction",
                    "passed": media_client.returncode == 0
                    and canary not in media_logs
                    and "route_id=qxd_attachment" in media_logs,
                }
            )

            permission_probe_code = """
from pathlib import Path
import tempfile
from app.core.config import Settings

root = Path(tempfile.mkdtemp(prefix='l1-secret-probe-'))
names = (
    'db', 'redis', 'admin', 'session', 'artifact', 'cos-id', 'cos-secret',
    'qxd-api', 'qxd-claim',
)
paths = {}
for index, name in enumerate(names):
    path = root / name
    path.write_text(f'material-{index:02d}-' + 'x' * 40, encoding='utf-8')
    path.chmod(0o600)
    paths[name] = str(path)
(root / 'qxd-api').chmod(0o644)
configured = Settings(
    DEBUG=False,
    PRODUCTION_DEPLOYMENT=True,
    DATABASE_HOST='postgres', DATABASE_NAME='prod', DATABASE_USER='prod',
    DATABASE_PASSWORD_FILE=paths['db'],
    REDIS_HOST='redis', REDIS_PASSWORD_FILE=paths['redis'],
    ADMIN_TOKEN_FILE=paths['admin'],
    SESSION_HMAC_SECRET_FILE=paths['session'],
    ARTIFACT_SIGNING_SECRET_FILE=paths['artifact'],
    S3_ACCESS_KEY_ID_FILE=paths['cos-id'],
    S3_SECRET_ACCESS_KEY_FILE=paths['cos-secret'],
    QXD_API_KEY_FILE=paths['qxd-api'],
    QXD_END_USER_SIGNING_SECRET_FILE=paths['qxd-claim'],
)
print(
    'qxd_mode_restricted=' + str(not bool((root / 'qxd-api').stat().st_mode & 0o077))
    + ';permission_gate=' + str(configured.production_secret_file_permissions_valid)
)
raise SystemExit(0 if not configured.production_secret_file_permissions_valid else 1)
""".strip()
            encoded_permission_probe = base64.b64encode(
                permission_probe_code.encode("utf-8")
            ).decode("ascii")
            qxd_permission_probe = _docker(
                "run", "--rm", "--network", "none",
                "-v", _mount(ROOT / "backend" / "app", "/app/app"),
                "tsing-radar-backend:local", "python", "-c",
                f"import base64;exec(base64.b64decode('{encoded_permission_probe}'))",
                expected=set(range(256)),
            )
            checks.append(
                {
                    "id": "secrets.qxd_0644_permission_fails_closed",
                    "passed": qxd_permission_probe.returncode == 0,
                    "observed": qxd_permission_probe.stdout.strip(),
                    "observed_error_class": (
                        qxd_permission_probe.stderr.strip().splitlines()[-1].split(":", 1)[0]
                        if qxd_permission_probe.stderr.strip()
                        else "none"
                    ),
                }
            )

            _docker(
                "run", "-d", "--name", names["postgres"], "--network", network,
                "--network-alias", "postgres", "-e", "POSTGRES_USER=l1_bootstrap",
                "-e", f"POSTGRES_PASSWORD={dummy_postgres}", "-e", "POSTGRES_DB=l1_lock",
                "postgres:16-alpine",
            )
            created.append(names["postgres"])
            if not _wait_exec(
                names["postgres"],
                ["pg_isready", "-U", "l1_bootstrap", "-d", "l1_lock"],
                attempts=60,
            ):
                raise RuntimeError("ephemeral PostgreSQL did not become ready")
            bootstrap_secret = temporary_path / "database-bootstrap"
            prod_secret = temporary_path / "database-prod"
            stage_secret = temporary_path / "database-stage"
            bootstrap_secret.write_text(dummy_postgres, encoding="utf-8")
            prod_secret.write_text(dummy_prod_app, encoding="utf-8")
            stage_secret.write_text(dummy_stage_app, encoding="utf-8")
            provision_script = DEPLOY / "scripts" / "database_provision.py"
            migration_script = DEPLOY / "scripts" / "migration_with_lock.py"
            migration_without_provision = _docker(
                "run", "--rm", "--network", network,
                "-v", _mount(migration_script, "/opt/migration.py"),
                "-v", _mount(prod_secret, "/run/secrets/database_password"),
                "-e", "DATABASE_HOST=postgres",
                "-e", "DATABASE_NAME=l1_prod",
                "-e", "DATABASE_USER=l1_prod_app",
                "-e", "DATABASE_PASSWORD_FILE=/run/secrets/database_password",
                "tsing-radar-backend:local", "python", "/opt/migration.py",
                expected=set(range(256)),
            )
            common_provision = [
                "run", "--rm", "--network", network,
                "-v", _mount(provision_script, "/opt/database_provision.py"),
                "-v", _mount(bootstrap_secret, "/run/secrets/bootstrap"),
                "-e", "DATABASE_HOST=postgres",
                "-e", "DATABASE_BOOTSTRAP_USER=l1_bootstrap",
                "-e", "DATABASE_BOOTSTRAP_PASSWORD_FILE=/run/secrets/bootstrap",
                "tsing-radar-backend:local", "python", "/opt/database_provision.py",
            ]
            prod_provision = common_provision.copy()
            prod_provision[prod_provision.index("tsing-radar-backend:local"):prod_provision.index("tsing-radar-backend:local")] = [
                "-v", _mount(prod_secret, "/run/secrets/target"),
                "-e", "TARGET_DATABASE_NAME=l1_prod",
                "-e", "TARGET_DATABASE_USER=l1_prod_app",
                "-e", "TARGET_DATABASE_PASSWORD_FILE=/run/secrets/target",
            ]
            _docker(*prod_provision)
            stage_provision = common_provision.copy()
            stage_provision[stage_provision.index("tsing-radar-backend:local"):stage_provision.index("tsing-radar-backend:local")] = [
                "-v", _mount(stage_secret, "/run/secrets/target"),
                "-e", "TARGET_DATABASE_NAME=l1_stage",
                "-e", "TARGET_DATABASE_USER=l1_stage_app",
                "-e", "TARGET_DATABASE_PASSWORD_FILE=/run/secrets/target",
                "-e", "PROTECTED_DATABASE_NAME=l1_prod",
                "-e", "PROTECTED_DATABASE_USER=l1_prod_app",
            ]
            _docker(*stage_provision)
            _docker(*prod_provision)
            prod_create_role = _docker(
                "run", "--rm", "--network", network,
                "-e", f"PGPASSWORD={dummy_prod_app}", "postgres:16-alpine",
                "psql", "-h", "postgres", "-U", "l1_prod_app", "-d", "l1_prod",
                "-c", "CREATE ROLE forbidden_role",
                expected=set(range(256)),
            )
            prod_create_database = _docker(
                "run", "--rm", "--network", network,
                "-e", f"PGPASSWORD={dummy_prod_app}", "postgres:16-alpine",
                "psql", "-h", "postgres", "-U", "l1_prod_app", "-d", "l1_prod",
                "-c", "CREATE DATABASE forbidden_database",
                expected=set(range(256)),
            )
            stage_to_prod = _docker(
                "run", "--rm", "--network", network,
                "-e", f"PGPASSWORD={dummy_stage_app}", "postgres:16-alpine",
                "psql", "-h", "postgres", "-U", "l1_stage_app", "-d", "l1_prod",
                "-c", "SELECT 1",
                expected=set(range(256)),
            )
            prod_to_stage = _docker(
                "run", "--rm", "--network", network,
                "-e", f"PGPASSWORD={dummy_prod_app}", "postgres:16-alpine",
                "psql", "-h", "postgres", "-U", "l1_prod_app", "-d", "l1_stage",
                "-c", "SELECT 1",
                expected=set(range(256)),
            )
            prod_owner = _docker(
                "exec", "-e", f"PGPASSWORD={dummy_postgres}", names["postgres"],
                "psql", "-At", "-U", "l1_bootstrap", "-d", "postgres",
                "-c", "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='l1_prod'",
            )
            prod_empty = _docker(
                "run", "--rm", "--network", network,
                "-e", f"PGPASSWORD={dummy_prod_app}", "postgres:16-alpine",
                "psql", "-At", "-h", "postgres", "-U", "l1_prod_app", "-d", "l1_prod",
                "-c", "SELECT count(*) FROM pg_tables WHERE schemaname='public'",
            )
            prod_schema_on_stage = _docker(
                "exec", "-e", f"PGPASSWORD={dummy_postgres}", names["postgres"],
                "psql", "-At", "-U", "l1_bootstrap", "-d", "l1_stage",
                "-c", "SELECT has_schema_privilege('l1_prod_app','public','CREATE')",
            )
            checks.append(
                {
                    "id": "postgres.bootstrap_and_stage_authorization",
                    "passed": migration_without_provision.returncode != 0
                    and prod_create_role.returncode != 0
                    and prod_create_database.returncode != 0
                    and stage_to_prod.returncode != 0
                    and prod_to_stage.returncode != 0
                    and prod_owner.stdout.strip() == "l1_prod_app"
                    and prod_empty.stdout.strip() == "0"
                    and prod_schema_on_stage.stdout.strip() == "f",
                    "observed_exit_codes": {
                        "migration_without_provision": migration_without_provision.returncode,
                        "prod_create_role_denied": prod_create_role.returncode,
                        "prod_create_database_denied": prod_create_database.returncode,
                        "stage_prod_connect_denied": stage_to_prod.returncode,
                        "prod_stage_connect_denied": prod_to_stage.returncode,
                    },
                }
            )
            database_url = f"postgresql://l1_bootstrap:{dummy_postgres}@postgres:5432/l1_lock"
            holder_code = (
                "import importlib.util,time,psycopg; p='/opt/migration.py'; "
                "s=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"c=psycopg.connect('{database_url}',autocommit=True); assert m.acquire_deployment_lock(c,0); "
                "print('LOCKED',flush=True); time.sleep(30)"
            )
            _docker(
                "run", "-d", "--name", names["lock-holder"], "--network", network,
                "-v", _mount(migration_script, "/opt/migration.py"),
                "tsing-radar-backend:local", "python", "-c", holder_code,
            )
            created.append(names["lock-holder"])
            for _ in range(40):
                if "LOCKED" in _docker("logs", names["lock-holder"]).stdout:
                    break
                time.sleep(0.25)
            contender_code = (
                "import importlib.util,psycopg; p='/opt/migration.py'; "
                "s=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"c=psycopg.connect('{database_url}',autocommit=True); raise SystemExit(0 if m.acquire_deployment_lock(c,0.2) else m.LOCK_BUSY_EXIT)"
            )
            contender = _docker(
                "run", "--rm", "--network", network,
                "-v", _mount(migration_script, "/opt/migration.py"),
                "tsing-radar-backend:local", "python", "-c", contender_code,
                expected=set(range(256)),
            )
            _docker("stop", "--time", "1", names["lock-holder"])
            created.remove(names["lock-holder"])
            _docker("rm", names["lock-holder"])
            failure_code = (
                "import importlib.util,psycopg; p='/opt/migration.py'; "
                "s=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"c=psycopg.connect('{database_url}',autocommit=True); acquired=m.acquire_deployment_lock(c,0); "
                "assert acquired; m.release_deployment_lock(c); c.close(); raise SystemExit(m.MIGRATION_FAILED_EXIT)"
            )
            failed_migration = _docker(
                "run", "--rm", "--network", network,
                "-v", _mount(migration_script, "/opt/migration.py"),
                "tsing-radar-backend:local", "python", "-c", failure_code,
                expected=set(range(256)),
            )
            reacquire_code = (
                "import importlib.util,psycopg; p='/opt/migration.py'; "
                "s=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"c=psycopg.connect('{database_url}',autocommit=True); assert m.acquire_deployment_lock(c,0); m.release_deployment_lock(c); c.close()"
            )
            reacquire = _docker(
                "run", "--rm", "--network", network,
                "-v", _mount(migration_script, "/opt/migration.py"),
                "tsing-radar-backend:local", "python", "-c", reacquire_code,
                expected={0, 1},
            )
            checks.append(
                {
                    "id": "postgres.advisory_lock_concurrency_and_release",
                    "passed": contender.returncode == 75
                    and failed_migration.returncode == 70
                    and reacquire.returncode == 0,
                    "observed_exit_codes": {
                        "lock_busy": contender.returncode,
                        "migration_failure": failed_migration.returncode,
                        "reacquire": reacquire.returncode,
                    },
                }
            )
            job_lock_script = DEPLOY / "scripts" / "job-lock.sh"
            job_lock_file = temporary_path / "job.lock"
            job_lock_file.touch()
            job_lock_file.chmod(0o660)
            lock_mounts = [
                "-v", _mount(job_lock_script, "/opt/job-lock.sh"),
                "-v", _mount_rw(job_lock_file, "/run/tsing-radar/job.lock"),
                "-e", "JOB_LOCK_TIMEOUT_SECONDS=1",
            ]
            _docker(
                "run", "-d", "--name", names["job-lock-holder"],
                *lock_mounts,
                "alpine:3.22", "/bin/sh", "/opt/job-lock.sh",
                "/bin/sh", "-c", "echo LOCKED; sleep 30",
            )
            created.append(names["job-lock-holder"])
            for _ in range(40):
                if "LOCKED" in _docker("logs", names["job-lock-holder"]).stdout:
                    break
                time.sleep(0.25)
            second_job = _docker(
                "run", "--rm", *lock_mounts,
                "alpine:3.22", "/bin/sh", "/opt/job-lock.sh", "/bin/true",
                expected=set(range(256)),
            )
            _docker("stop", "--time", "1", names["job-lock-holder"])
            created.remove(names["job-lock-holder"])
            _docker("rm", names["job-lock-holder"])
            failed_job = _docker(
                "run", "--rm", *lock_mounts,
                "alpine:3.22", "/bin/sh", "/opt/job-lock.sh",
                "/bin/sh", "-c", "exit 70",
                expected=set(range(256)),
            )
            job_after_failure = _docker(
                "run", "--rm", *lock_mounts,
                "alpine:3.22", "/bin/sh", "/opt/job-lock.sh", "/bin/true",
                expected=set(range(256)),
            )
            checks.append(
                {
                    "id": "jobs.kernel_lock_cross_job_and_release",
                    "passed": second_job.returncode == 75
                    and failed_job.returncode == 70
                    and job_after_failure.returncode == 0,
                    "observed_exit_codes": {
                        "concurrent_second_job": second_job.returncode,
                        "failed_first_job": failed_job.returncode,
                        "reacquire_after_failure": job_after_failure.returncode,
                    },
                }
            )
    finally:
        for name in reversed(created):
            if name.startswith(PREFIX):
                _docker("rm", "-f", name, expected={0, 1})
        if network.startswith(PREFIX):
            _docker("network", "rm", network, expected={0, 1})

    failed = [item["id"] for item in checks if not item["passed"]]
    report = {
        "schema_version": "l1-ephemeral-containers-v1",
        "real_credentials_used": False,
        "persistent_volumes_created": False,
        "host_ports_published": False,
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed": failed,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
