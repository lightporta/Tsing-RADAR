"""L1 additive production artifact and adapter contracts."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.main import app
from app.services.object_storage import (
    ObjectStorageError,
    S3PrivateObjectStore,
    validate_tencent_cos_configuration,
)
from app.services.preflight import run_l1_production_preflight
from app.core.security_validation import validate_production_secrets
from app.services.qxd_media import validate_remote_media_configuration

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "production"


def _secret(tmp_path: Path, name: str, marker: str) -> str:
    path = tmp_path / name
    path.write_text(marker + "-" + "x" * 40, encoding="utf-8")
    return str(path)


def _clear_direct_secret_environment(monkeypatch) -> None:
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "ADMIN_TOKEN",
        "SESSION_HMAC_SECRET",
        "ARTIFACT_SIGNING_SECRET",
        "QXD_API_KEY",
        "QXD_END_USER_SIGNING_SECRET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _production_settings(tmp_path: Path, monkeypatch) -> Settings:
    _clear_direct_secret_environment(monkeypatch)
    return Settings(
        DEBUG=False,
        PRODUCTION_DEPLOYMENT=True,
        AUTO_CREATE_SCHEMA=False,
        DATABASE_HOST="postgres",
        DATABASE_NAME="tsing_radar_prod",
        DATABASE_USER="tsing_radar_prod",
        DATABASE_PASSWORD_FILE=_secret(tmp_path, "db", "db"),
        REDIS_HOST="redis",
        REDIS_PASSWORD_FILE=_secret(tmp_path, "redis", "redis"),
        ADMIN_TOKEN_FILE=_secret(tmp_path, "admin", "admin"),
        SESSION_HMAC_SECRET_FILE=_secret(tmp_path, "session", "session"),
        ARTIFACT_SIGNING_SECRET_FILE=_secret(
            tmp_path,
            "artifact",
            "artifact",
        ),
        WEB_COOKIE_SECURE=True,
        OBJECT_STORE_BACKEND="s3",
        S3_PROVIDER="tencent_cos",
        S3_BUCKET="tsing-radar-prod-1250000000",
        S3_ENDPOINT_URL="https://cos.ap-shanghai.myqcloud.com",
        S3_REGION="ap-shanghai",
        S3_ACCESS_KEY_ID_FILE=_secret(tmp_path, "cos-id", "cos-id"),
        S3_SECRET_ACCESS_KEY_FILE=_secret(
            tmp_path,
            "cos-secret",
            "cos-secret",
        ),
        S3_ADDRESSING_STYLE="virtual",
        S3_SERVER_SIDE_ENCRYPTION="AES256",
        FILE_SCAN_MODE="clamav",
        CLAMAV_HOST="clamav",
        QXD_TRIAL_SINGLE_USER_MODE=False,
        QXD_REMOTE_MEDIA_FETCH_ENABLED=False,
        QXD_ATTACHMENTS_ENABLED=False,
        PUBLIC_BASE_URL=None,
    )


def test_file_backed_settings_build_private_database_and_redis_urls(
    tmp_path,
    monkeypatch,
):
    configured = _production_settings(tmp_path, monkeypatch)
    assert configured.DATABASE_URL.startswith(
        "postgresql+psycopg://tsing_radar_prod:"
    )
    assert "@postgres:5432/tsing_radar_prod" in configured.DATABASE_URL
    assert configured.REDIS_URL is not None
    assert configured.REDIS_URL.startswith("redis://:")
    assert configured.REDIS_URL.endswith("@redis:6379/0")
    assert configured.production_secret_files_configured is True


def test_direct_and_file_secret_inputs_are_mutually_exclusive(
    tmp_path,
    monkeypatch,
):
    _clear_direct_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings(
            ADMIN_TOKEN="direct-value-must-not-win",
            ADMIN_TOKEN_FILE=_secret(tmp_path, "admin", "file-value"),
        )
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings(
            DATABASE_URL="postgresql://direct.invalid/database",
            DATABASE_HOST="postgres",
            DATABASE_NAME="database",
            DATABASE_USER="user",
            DATABASE_PASSWORD_FILE=_secret(tmp_path, "database", "password"),
        )


def test_optional_qxd_secrets_are_strong_distinct_and_permission_scoped(
    tmp_path,
    monkeypatch,
):
    configured = _production_settings(tmp_path, monkeypatch)
    qxd_key_file = _secret(tmp_path, "qxd-key", "qxd-key")
    qxd_claim_file = _secret(tmp_path, "qxd-claim", "qxd-claim")
    object.__setattr__(configured, "QXD_API_KEY_FILE", qxd_key_file)
    object.__setattr__(
        configured,
        "QXD_END_USER_SIGNING_SECRET_FILE",
        qxd_claim_file,
    )
    object.__setattr__(configured, "QXD_API_KEY", "qxd-key-" + "k" * 40)
    object.__setattr__(
        configured,
        "QXD_END_USER_SIGNING_SECRET",
        "qxd-claim-" + "c" * 40,
    )
    assert qxd_key_file in configured.production_secret_file_paths
    assert qxd_claim_file in configured.production_secret_file_paths
    validate_production_secrets(configured)

    object.__setattr__(configured, "QXD_API_KEY", "admin")
    with pytest.raises(RuntimeError, match="QXD_API_KEY") as placeholder:
        validate_production_secrets(configured)
    assert "admin" not in str(placeholder.value)

    object.__setattr__(configured, "QXD_API_KEY", "short")
    with pytest.raises(RuntimeError, match="QXD_API_KEY"):
        validate_production_secrets(configured)

    object.__setattr__(configured, "QXD_API_KEY", configured.SESSION_HMAC_SECRET)
    with pytest.raises(RuntimeError, match="不同密钥"):
        validate_production_secrets(configured)


def test_remote_media_enablement_requires_bearer_and_nonempty_allowlist(
    tmp_path,
    monkeypatch,
):
    configured = _production_settings(tmp_path, monkeypatch)
    object.__setattr__(configured, "QXD_REMOTE_MEDIA_FETCH_ENABLED", True)
    with pytest.raises(RuntimeError, match="入站协议凭证"):
        validate_remote_media_configuration(configured)

    object.__setattr__(configured, "QXD_API_KEY", "qxd-api-" + "k" * 40)
    with pytest.raises(RuntimeError, match="非空域名白名单"):
        validate_remote_media_configuration(configured)

    object.__setattr__(configured, "QXD_MEDIA_ALLOWED_HOSTS", "media.example.edu")
    validate_remote_media_configuration(configured)


def test_secret_preflight_rejects_weak_and_reused_material_without_echo(tmp_path):
    path = DEPLOY / "scripts" / "secret_preflight.py"
    spec = importlib.util.spec_from_file_location("secret_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    prod = (tmp_path / "prod").resolve()
    stage = (tmp_path / "stage").resolve()
    bootstrap = (tmp_path / "bootstrap").resolve()
    for root in (prod, stage, bootstrap):
        root.mkdir()
    counter = 0
    for root, names in (
        (prod, module.PROD_FILES + module.QXD_FILES),
        (stage, module.STAGE_FILES),
        (bootstrap, module.BOOTSTRAP_FILES),
    ):
        for name in names:
            counter += 1
            file_path = root / name
            file_path.write_text(f"material-{counter:02d}-" + "x" * 40, encoding="utf-8")
            file_path.chmod(0o600)

    passed = module.validate_roots(prod, stage, bootstrap)
    assert passed["status"] == "passed"
    assert passed["values_or_hashes_emitted"] is False

    weak_value = "short-canary-must-not-echo"
    (prod / "qxd_api_key").write_text(weak_value, encoding="utf-8")
    (prod / "qxd_api_key").chmod(0o600)
    weak = module.validate_roots(prod, stage, bootstrap)
    assert weak["status"] == "failed"
    assert weak_value not in json.dumps(weak, ensure_ascii=False)

    reused_value = (prod / "session_hmac_secret").read_text(encoding="utf-8")
    (prod / "qxd_api_key").write_text(reused_value, encoding="utf-8")
    (prod / "qxd_api_key").chmod(0o600)
    reused = module.validate_roots(prod, stage, bootstrap)
    assert reused["status"] == "failed"
    assert reused_value not in json.dumps(reused, ensure_ascii=False)


@pytest.mark.parametrize(
    ("endpoint", "bucket", "region", "style"),
    [
        ("http://cos.ap-shanghai.myqcloud.com", "bucket-1250000000", "ap-shanghai", "virtual"),
        ("https://user@cos.ap-shanghai.myqcloud.com", "bucket-1250000000", "ap-shanghai", "virtual"),
        ("https://cos.ap-shanghai.myqcloud.com/path", "bucket-1250000000", "ap-shanghai", "virtual"),
        ("https://cos.ap-shanghai.myqcloud.com?x=1", "bucket-1250000000", "ap-shanghai", "virtual"),
        ("https://cos.ap-beijing.myqcloud.com", "bucket-1250000000", "ap-shanghai", "virtual"),
        ("https://bucket-1250000000.cos.ap-shanghai.myqcloud.com", "bucket-1250000000", "ap-shanghai", "virtual"),
        ("https://cos.ap-shanghai.myqcloud.com", "bucket-without-appid", "ap-shanghai", "virtual"),
        ("https://cos.ap-shanghai.myqcloud.com", "bucket-1250000000", "ap-beijing", "virtual"),
        ("https://cos.ap-shanghai.myqcloud.com", "bucket-1250000000", "ap-shanghai", "path"),
    ],
)
def test_cos_endpoint_contract_fails_closed(endpoint, bucket, region, style):
    with pytest.raises(ObjectStorageError):
        validate_tencent_cos_configuration(
            endpoint_url=endpoint,
            bucket=bucket,
            region=region,
            addressing_style=style,
        )


def test_cos_sdk_endpoint_is_bucket_free_and_signed_host_adds_bucket_once(
    monkeypatch,
):
    bucket = "tsing-radar-prod-1250000000"
    endpoint = "https://cos.ap-shanghai.myqcloud.com"
    assert validate_tencent_cos_configuration(
        endpoint_url=endpoint,
        bucket=bucket,
        region="ap-shanghai",
        addressing_style="virtual",
    ) == f"{bucket}.cos.ap-shanghai.myqcloud.com"

    monkeypatch.setattr(settings, "S3_PROVIDER", "tencent_cos")
    monkeypatch.setattr(settings, "S3_BUCKET", bucket)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", endpoint)
    monkeypatch.setattr(settings, "S3_REGION", "ap-shanghai")
    monkeypatch.setattr(settings, "S3_ADDRESSING_STYLE", "virtual")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY_ID", "dummy-access-key")
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", "dummy-secret-key")
    store = S3PrivateObjectStore()
    signed = store.client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": "objects/report.pdf"},
        ExpiresIn=60,
    )
    host = urlsplit(signed).hostname
    assert host == f"{bucket}.cos.ap-shanghai.myqcloud.com"
    assert host.count(bucket) == 1


def test_l1_preflight_is_redacted_and_remains_cloud_blocked(
    tmp_path,
    monkeypatch,
):
    configured = _production_settings(tmp_path, monkeypatch)
    report = run_l1_production_preflight(configured)
    assert report["status"] == "blocked"
    assert report["blockers"] == []
    assert all(item["status"] == "passed" for item in report["checks"])
    assert report["network_requests_performed"] is False
    serialized = json.dumps(report)
    for path in tmp_path.iterdir():
        value = path.read_text(encoding="utf-8")
        assert value not in serialized
    assert "cloud.tencent_cos_runtime_and_sse" in report["manual_release_gates"]


def test_default_artifacts_do_not_mount_or_route_qxd_or_media():
    edge = (DEPLOY / "compose.edge.yml").read_text(encoding="utf-8")
    base = (DEPLOY / "edge" / "Caddyfile").read_text(encoding="utf-8")
    web = (DEPLOY / "edge" / "routes" / "web-api.caddy").read_text(
        encoding="utf-8"
    )
    qxd = (DEPLOY / "qxd-gateway" / "nginx.conf").read_text(encoding="utf-8")
    assert "qxd.caddy" not in edge
    assert "media.caddy" not in edge
    assert "admin off" in base
    assert "path /api/*" not in web
    assert "attachments and /v1 are absent" in web
    assert "QXD1-Trial" not in qxd
    assert "qxd1-single-user-trial" not in qxd


def test_stage_has_no_prod_milvus_or_prod_application_network_contract():
    stage = (DEPLOY / "compose.stage.yml").read_text(encoding="utf-8")
    assert "No MILVUS_HOST" in stage
    assert "vector-data" not in stage
    assert "prod-app" not in stage
    assert "${STAGE_SECRET_ROOT:?Set STAGE_SECRET_ROOT}/redis_password" in stage
    assert "create_host_path: false" in stage
    assert "STAGE_COS_BUCKET" in stage
    assert "scanner-shared" in stage


def test_database_bootstrap_identity_is_one_shot_and_never_reaches_backend():
    infra = (DEPLOY / "compose.infra.yml").read_text(encoding="utf-8")
    prod = (DEPLOY / "compose.prod.yml").read_text(encoding="utf-8")
    stage = (DEPLOY / "compose.stage.yml").read_text(encoding="utf-8")
    jobs = (DEPLOY / "compose.jobs.yml").read_text(encoding="utf-8")
    provision = (DEPLOY / "scripts" / "database_provision.py").read_text(
        encoding="utf-8"
    )
    assert "DATABASE_BOOTSTRAP_USER" in infra
    assert "DATABASE_BOOTSTRAP" not in prod
    assert "database_bootstrap_password" in stage
    assert "prod-db-provision" in jobs and 'restart: "no"' in jobs
    assert "NOSUPERUSER NOCREATEDB" in provision
    assert "NOCREATEROLE NOREPLICATION" in provision
    assert "REVOKE CONNECT ON DATABASE" in provision


def test_public_route_manifest_matches_real_routes_and_denies_new_routes():
    manifest = json.loads(
        (DEPLOY / "edge" / "public-route-allowlist.json").read_text(
            encoding="utf-8"
        )
    )
    allowed = {(item["method"], item["path"]) for item in manifest}
    actual = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
    }
    assert allowed <= actual
    protected = {
        (method, path)
        for method, path in actual
        if path.startswith(
            (
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
        )
    }
    assert protected
    assert protected.isdisjoint(allowed)
    caddy = (DEPLOY / "edge" / "routes" / "web-api.caddy").read_text(
        encoding="utf-8"
    )
    assert "path /api/*" not in caddy
    assert ("GET", "/api/new-route-added-later") not in allowed


def test_media_access_log_never_contains_signed_uri_or_query_tokens():
    config = (DEPLOY / "media-gateway" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    canary = "canary-bearer-token-must-not-log"
    assert canary not in config
    log_format = next(
        line for line in config.splitlines() if line.strip().startswith("log_format ")
    )
    assert "uri=$uri" not in log_format
    assert "$request_uri" not in log_format
    assert "$args" not in log_format
    assert "$http_authorization" not in log_format
    assert "$http_cookie" not in log_format
    assert "route_id=qxd_attachment" in log_format
    assert "access_log off" in config


def test_migration_wrapper_has_timeout_exit_and_releases_lock_on_failure():
    path = DEPLOY / "scripts" / "migration_with_lock.py"
    spec = importlib.util.spec_from_file_location("migration_with_lock", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Cursor:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, _parameters):
            self.connection.statements.append(statement)

        def fetchone(self):
            return (self.connection.acquire_result,)

    class Connection:
        def __init__(self, acquire_result):
            self.acquire_result = acquire_result
            self.statements = []

        def cursor(self):
            return Cursor(self)

    winner = Connection(True)
    loser = Connection(False)
    assert module.acquire_deployment_lock(winner, 0) is True
    assert module.acquire_deployment_lock(loser, 0) is False
    module.release_deployment_lock(winner)
    assert any("pg_advisory_unlock" in item for item in winner.statements)
    assert module.LOCK_BUSY_EXIT == 75


def test_l1_artifact_checker_passes_with_dummy_secrets_only():
    completed = subprocess.run(
        [sys.executable, "scripts/check_l1_production.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "passed"
    assert report["mode"] == "offline_dummy_secrets_only"
    assert report["resource_budget"] == {
        "host_memory_mib": 7578,
        "default_resolved_limit_mib": 5184,
        "public_edge_capacity_reserve_mib": 128,
        "default_capacity_budget_mib": 5312,
        "default_non_swap_headroom_mib": 2394,
        "edge_planning_non_swap_headroom_mib": 2266,
        "minimum_supported_combination_headroom_mib": 1280,
    }
    matrix = {item["name"]: item for item in report["resource_matrix"]}
    assert matrix["restore-check"]["resolved_limit_mib"] == 6080
    assert matrix["restore-check"]["non_swap_headroom_mib"] == 1498
    assert matrix["prod-stage"]["allowed"] is False
    assert report["real_credentials_used"] is False
    assert report["cloud_changes_performed"] is False
    assert report["failed"] == []


def test_explicit_secret_bind_contract_rejects_unsafe_mount_variants(tmp_path):
    path = ROOT / "scripts" / "check_l1_production.py"
    spec = importlib.util.spec_from_file_location("check_l1_production", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = tmp_path / "database_password"
    target = "/run/secrets/database_password"
    expected = {target: source}

    def service_with_mount(**changes):
        mount = {
            "type": "bind",
            "source": str(source),
            "target": target,
            "read_only": True,
            "bind": {"create_host_path": False},
        }
        mount.update(changes)
        return {"volumes": [mount]}

    assert module._secret_bind_contract(service_with_mount(), expected)
    assert not module._secret_bind_contract(
        service_with_mount(read_only=False), expected
    )
    assert not module._secret_bind_contract(
        service_with_mount(bind={"create_host_path": True}), expected
    )
    assert not module._secret_bind_contract(
        service_with_mount(source=str(tmp_path / "other")), expected
    )
    duplicated = service_with_mount()
    duplicated["volumes"].append(dict(duplicated["volumes"][0]))
    assert not module._secret_bind_contract(duplicated, expected)
    with_service_secret = service_with_mount()
    with_service_secret["secrets"] = ["database_password"]
    assert not module._secret_bind_contract(with_service_secret, expected)


def test_migration_service_requires_exact_application_import_path():
    path = ROOT / "scripts" / "check_l1_production.py"
    spec = importlib.util.spec_from_file_location("check_l1_migration_path", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    service = {
        "command": ["python", "/opt/tsing-radar/migration_with_lock.py"],
        "environment": {"PYTHONPATH": "/app"},
    }
    assert module._migration_import_contract(service)
    service["environment"].pop("PYTHONPATH")
    assert not module._migration_import_contract(service)
    service["environment"]["PYTHONPATH"] = "/srv/app"
    assert not module._migration_import_contract(service)


@pytest.mark.parametrize(
    "mutation",
    [
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
    ],
)
def test_l1_checker_rejects_security_mutations(mutation):
    completed = subprocess.run(
        [sys.executable, "scripts/check_l1_production.py", "--mutation", mutation],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert report["status"] == "failed"
    assert report["failed"]


def test_l1_checker_rejects_disallowed_high_load_combination():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_l1_production.py",
            "--require-combination",
            "prod-stage",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert "resources.requested_combination_allowed" in report["failed"]


def test_runbook_records_one_shot_order_and_container_exceptions():
    runbook = (DEPLOY / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "Start only infra" in runbook
    assert "prod-db-provision" in runbook
    assert "exactly one `migration` job" in runbook
    assert "restore it into the isolated restore-check" in runbook
    assert "Container exceptions pending cloud verification" in runbook
    assert "never overwrite the source database" in runbook
    assert "ListBucket" in runbook and "not pre-granted" in runbook
