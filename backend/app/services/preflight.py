"""Read-only, offline deployment preflight for A7.

The checker intentionally performs no DNS, network, cloud, scanner, or public
URL reachability probes. Those remain explicit manual release gates.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.security_validation import validate_production_secrets
from app.services.object_storage import (
    ObjectStorageError,
    validate_tencent_cos_configuration,
)

PREFLIGHT_VERSION = "a7-offline-preflight-v1"
L1_PREFLIGHT_VERSION = "l1-production-offline-v1"

_RESERVED_TEST_SUFFIXES = (
    ".example",
    ".test",
    ".invalid",
    ".example.com",
    ".example.net",
    ".example.org",
    ".example.edu",
)


def _check(check_id: str, passed: bool, reason_code: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "kind": "offline_static",
        "status": "passed" if passed else "failed",
        "reason_code": "ok" if passed else reason_code,
    }


def _public_base_is_plausibly_global(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value.rstrip("/"))
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        return False
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return False
    if (
        host == "localhost"
        or "." not in host
        or host.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
        or host in {"example.com", "example.net", "example.org", "example.edu"}
        or host.endswith(_RESERVED_TEST_SUFFIXES)
    ):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        # Offline mode cannot resolve DNS; shape passes but reachability remains
        # a separate manual release gate below.
        return True


def run_offline_preflight(
    app_settings: Settings,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Inspect configuration and repository shape without mutating anything."""
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "app.debug_disabled",
            not app_settings.DEBUG,
            "debug_must_be_disabled",
        )
    )
    checks.append(
        _check(
            "database.postgresql_configured",
            app_settings.DATABASE_URL.startswith(
                ("postgresql://", "postgresql+psycopg://")
            ),
            "production_database_not_postgresql",
        )
    )
    checks.append(
        _check(
            "database.schema_managed_by_migration",
            not app_settings.AUTO_CREATE_SCHEMA,
            "schema_auto_creation_must_be_disabled",
        )
    )
    checks.append(
        _check(
            "web.secure_cookie",
            app_settings.WEB_COOKIE_SECURE,
            "secure_cookie_disabled",
        )
    )
    try:
        validate_production_secrets(app_settings)
        secret_valid = True
    except RuntimeError:
        secret_valid = False
    checks.append(
        _check(
            "secrets.independent_32_byte_material_including_admin",
            secret_valid,
            "production_secret_policy_failed",
        )
    )
    checks.append(
        _check(
            "scanner.clamav_configured",
            app_settings.FILE_SCAN_MODE == "clamav"
            and bool(app_settings.CLAMAV_HOST),
            "clamav_not_configured",
        )
    )
    checks.append(
        _check(
            "storage.private_s3_configured",
            app_settings.OBJECT_STORE_BACKEND == "s3"
            and all(
                (
                    app_settings.S3_BUCKET,
                    app_settings.S3_ACCESS_KEY_ID,
                    app_settings.S3_SECRET_ACCESS_KEY,
                )
            ),
            "private_s3_not_configured",
        )
    )
    checks.append(
        _check(
            "storage.server_side_encryption_required",
            app_settings.S3_SERVER_SIDE_ENCRYPTION == "AES256",
            "s3_server_side_encryption_not_required",
        )
    )
    checks.append(
        _check(
            "qxd.inbound_and_user_claim_keys_configured",
            bool(
                app_settings.QXD_API_KEY
                and app_settings.QXD_END_USER_SIGNING_SECRET
            ),
            "qxd_credentials_not_configured",
        )
    )
    checks.append(
        _check(
            "delivery.public_base_shape",
            _public_base_is_plausibly_global(app_settings.PUBLIC_BASE_URL)
            and not app_settings.ALLOW_TEST_PUBLIC_BASE_URL,
            "public_base_not_production_plausible",
        )
    )
    checks.append(
        _check(
            "repository.alembic_head_present",
            (
                repository_root
                / "backend"
                / "alembic"
                / "versions"
                / "0006_a6_idempotency_and_audit.py"
            ).is_file(),
            "expected_migration_head_missing",
        )
    )
    checks.append(
        _check(
            "repository.a7_test_suite_present",
            (
                repository_root / "backend" / "tests" / "test_a7_operations.py"
            ).is_file(),
            "a7_test_suite_missing",
        )
    )

    manual_gates = [
        {
            "id": "a1.real_qxd_public_probe",
            "kind": "manual_external",
            "status": "not_run",
            "reason_code": "requires_approved_real_platform_probe",
        },
        {
            "id": "a2.release_content_and_history_audit",
            "kind": "manual_release",
            "status": "not_run",
            "reason_code": "release_audit_still_required",
        },
        {
            "id": "database.real_postgresql_two_connection_races",
            "kind": "manual_environment",
            "status": "not_run",
            "reason_code": "sql_compilation_is_not_runtime_validation",
        },
        {
            "id": "documents.office_or_libreoffice_docx_visual_review",
            "kind": "manual_environment",
            "status": "not_run",
            "reason_code": "office_renderer_not_validated",
        },
        {
            "id": "storage.object_read_streaming_hard_limit",
            "kind": "implementation",
            "status": "failed",
            "reason_code": "object_reads_are_not_stream_bounded",
        },
        {
            "id": "scanner.real_clamav_probe",
            "kind": "manual_external",
            "status": "not_run",
            "reason_code": "configuration_is_not_availability",
        },
        {
            "id": "storage.real_private_s3_probe",
            "kind": "manual_external",
            "status": "not_run",
            "reason_code": "configuration_is_not_availability",
        },
        {
            "id": "delivery.dns_tls_reachability_and_ssrf_review",
            "kind": "manual_external",
            "status": "not_run",
            "reason_code": "offline_shape_check_is_not_reachability",
        },
        {
            "id": "proxy.access_log_redaction_verification",
            "kind": "manual_environment",
            "status": "not_run",
            "reason_code": "application_filter_does_not_configure_proxy_logs",
        },
        {
            "id": "observability.production_sink_retention_and_alerts",
            "kind": "manual_environment",
            "status": "not_run",
            "reason_code": "local_structured_logs_are_not_a_production_sink",
        },
    ]
    blockers = [
        item["id"]
        for item in [*checks, *manual_gates]
        if item["status"] != "passed"
    ]
    return {
        "schema_version": PREFLIGHT_VERSION,
        "mode": "offline_read_only",
        "network_requests_performed": False,
        "external_credentials_used": False,
        "deployment_performed": False,
        "status": "blocked" if blockers else "ready",
        "checks": checks,
        "manual_release_gates": manual_gates,
        "blockers": blockers,
        "interpretation": (
            "A passed static check validates configuration shape only. It does "
            "not prove external service availability or production readiness."
        ),
    }


def run_l1_production_preflight(app_settings: Settings) -> dict[str, Any]:
    """Validate the additive production contract without external I/O.

    Values, fingerprints and stable hashes of secrets are intentionally never
    included in the report.
    """

    checks: list[dict[str, Any]] = []
    checks.extend(
        (
            _check(
                "deployment.production_flag",
                app_settings.PRODUCTION_DEPLOYMENT,
                "production_deployment_flag_disabled",
            ),
            _check(
                "app.debug_disabled",
                not app_settings.DEBUG,
                "debug_must_be_disabled",
            ),
            _check(
                "database.postgresql_file_secret",
                bool(
                    app_settings.DATABASE_PASSWORD_FILE
                    and app_settings.DATABASE_URL.startswith(
                        "postgresql+psycopg://"
                    )
                ),
                "database_file_secret_missing",
            ),
            _check(
                "redis.file_secret",
                bool(
                    app_settings.REDIS_PASSWORD_FILE
                    and app_settings.REDIS_URL
                    and app_settings.REDIS_URL.startswith("redis://")
                ),
                "redis_file_secret_missing",
            ),
            _check(
                "secrets.file_backed",
                app_settings.production_secret_files_configured,
                "production_secret_file_policy_failed",
            ),
            _check(
                "secrets.file_permissions",
                app_settings.production_secret_file_permissions_valid,
                "production_secret_file_permissions_failed",
            ),
            _check(
                "web.secure_cookie",
                app_settings.WEB_COOKIE_SECURE,
                "secure_cookie_disabled",
            ),
            _check(
                "scanner.clamav_configured",
                app_settings.FILE_SCAN_MODE == "clamav"
                and bool(app_settings.CLAMAV_HOST),
                "clamav_not_configured",
            ),
            _check(
                "storage.tencent_cos_selected",
                app_settings.OBJECT_STORE_BACKEND == "s3"
                and app_settings.S3_PROVIDER == "tencent_cos",
                "tencent_cos_not_selected",
            ),
            _check(
                "storage.server_side_encryption_required",
                app_settings.S3_SERVER_SIDE_ENCRYPTION == "AES256",
                "s3_server_side_encryption_not_required",
            ),
            _check(
                "qxd.disabled_by_default",
                not app_settings.QXD_API_KEY_FILE
                and not app_settings.QXD_END_USER_SIGNING_SECRET_FILE
                and not app_settings.QXD_REMOTE_MEDIA_FETCH_ENABLED
                and not app_settings.QXD_ATTACHMENTS_ENABLED
                and not app_settings.PUBLIC_BASE_URL,
                "qxd_or_media_enabled_without_release_gate",
            ),
            _check(
                "qxd.trial_mode_disabled",
                not app_settings.QXD_TRIAL_SINGLE_USER_MODE,
                "qxd_trial_mode_must_be_disabled",
            ),
        )
    )
    try:
        validate_production_secrets(app_settings)
        secret_policy_valid = True
    except RuntimeError:
        secret_policy_valid = False
    checks.append(
        _check(
            "secrets.independent_32_byte_material",
            secret_policy_valid,
            "production_secret_policy_failed",
        )
    )
    try:
        final_host = validate_tencent_cos_configuration(
            endpoint_url=app_settings.S3_ENDPOINT_URL,
            bucket=app_settings.S3_BUCKET,
            region=app_settings.S3_REGION,
            addressing_style=app_settings.S3_ADDRESSING_STYLE,
            server_side_encryption=app_settings.S3_SERVER_SIDE_ENCRYPTION,
        )
        cos_shape_valid = final_host.count(app_settings.S3_BUCKET or "") == 1
    except ObjectStorageError:
        cos_shape_valid = False
    checks.append(
        _check(
            "storage.tencent_cos_endpoint_contract",
            cos_shape_valid,
            "tencent_cos_endpoint_contract_failed",
        )
    )
    blockers = [item["id"] for item in checks if item["status"] != "passed"]
    return {
        "schema_version": L1_PREFLIGHT_VERSION,
        "mode": "offline_read_only",
        "network_requests_performed": False,
        "external_credentials_used": False,
        "deployment_performed": False,
        "status": "blocked",
        "checks": checks,
        "blockers": blockers,
        "manual_release_gates": [
            "cloud.tencent_cos_runtime_and_sse",
            "cloud.postgresql_backup_restore_and_races",
            "cloud.clamav_runtime_fail_closed",
            "public.dns_tls_icp_and_host_allowlist",
            "qxd.trusted_end_user_identity_or_transcript",
            "media.explicit_public_delivery_authorization",
            "release.git_history_data_license_dependency_audit",
        ],
        "interpretation": (
            "Static configuration shape passed where indicated; production, "
            "cloud and public reachability remain explicitly unverified."
        ),
    }
