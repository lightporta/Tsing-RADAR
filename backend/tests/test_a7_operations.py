"""A7 offline evaluation, observability, preflight, and rehearsal tests."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging_filters import (
    ArtifactTokenRedactionFilter,
    redact_artifact_token,
)
from app.core.security_validation import validate_production_secrets
from app.db.session import SessionLocal
from app.main import app
from app.models.feedback import Feedback
from app.models.questionnaire_session import QuestionnaireSession
from app.services.evaluation import (
    assess_learning_readiness,
    run_synthetic_contract_evaluation,
)
from app.services.observability import metrics_snapshot, operational_metrics
from app.services.preflight import run_offline_preflight
from app.services.training import get_model_weights, train

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_synthetic_evaluation_covers_contracts_without_accuracy_claim():
    report = run_synthetic_contract_evaluation()
    assert report["summary"] == {
        "total": 7,
        "passed": 7,
        "failed": 0,
        "status": "passed",
    }
    assert report["fixture_classification"] == "synthetic_only"
    assert report["real_recommendation_accuracy_measured"] is False
    assert report["learned_ranking_evaluated"] is False
    assert "do not establish real recommendation quality" in report["claim_limit"]
    hard_constraint = next(
        item
        for item in report["assertions"]
        if item["id"] == "hard_constraints_precede_recall"
    )
    assert hard_constraint["observed"] == {
        "input_candidates": 3,
        "after_hard_constraints": 2,
        "excluded_by_hard_constraints": 1,
        "high_recall_constraint_violation_returned": False,
    }


def test_learning_gate_does_not_relabel_feedback_or_interview_completion():
    with SessionLocal() as db:
        feedback = Feedback(
            student_id="a7-private-subject",
            advisor_id="synthetic-advisor",
            rating=1,
            comment="synthetic preference",
        )
        interview = QuestionnaireSession(
            student_id="a7-private-subject",
            messages=[],
            portrait={},
            status="confirmed",
            answered_dimensions=[],
        )
        db.add_all([feedback, interview])
        db.commit()
        try:
            readiness = assess_learning_readiness(db)
        finally:
            db.delete(feedback)
            db.delete(interview)
            db.commit()

    assert readiness["status"] == "blocked"
    assert readiness["learned_ranking_enabled"] is False
    assert readiness["observed_non_training_counts"]["preference_feedback"] >= 1
    assert readiness["observed_non_training_counts"]["confirmed_interviews"] >= 1
    serialized = json.dumps(readiness)
    assert "a7-private-subject" not in serialized
    assert "synthetic preference" not in serialized


def test_train_is_a_fail_closed_readiness_check_and_creates_no_weights():
    result = train()
    assert result["status"] == "blocked_by_data_readiness_gate"
    assert result["training_started"] is False
    assert result["weights"] is None
    assert get_model_weights() is None


def test_health_separates_liveness_from_local_readiness():
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.status_code == 200
    assert live.json()["external_dependencies_probed"] is False
    assert ready.status_code == 200
    assert ready.json()["scope"] == "local_dependencies_only"
    assert ready.json()["external_dependencies_probed"] is False


def test_observability_uses_route_templates_and_never_records_token(caplog):
    operational_metrics.reset_for_tests()
    token = "v1.secret-grant.secret-nonce.secret-signature"
    with caplog.at_level(logging.INFO, logger="tsing_radar.operations"):
        with TestClient(app) as client:
            response = client.post(
                f"/api/artifacts/download/{token}",
                headers={"X-Request-ID": "untrusted-client-request-id"},
            )
    assert response.status_code in {401, 403}
    snapshot = metrics_snapshot()
    serialized = json.dumps(snapshot)
    assert token not in serialized
    assert "/api/artifacts/download/{token}" in serialized
    assert response.headers["X-Request-ID"] != "untrusted-client-request-id"
    assert all(token not in record.getMessage() for record in caplog.records)
    assert all(
        "untrusted-client-request-id" not in record.getMessage()
        for record in caplog.records
    )
    assert all(
        record.getMessage().count("request_id") <= 1 for record in caplog.records
    )


def test_access_log_filter_redacts_path_and_sensitive_query_values():
    secret = "top-secret-value"
    message = (
        f'POST /api/artifacts/download/{secret}?token={secret}'
        f"&signature={secret}&safe=ok"
    )
    redacted = redact_artifact_token(message)
    assert secret not in redacted
    assert redacted.count("[REDACTED]") == 3
    assert "safe=ok" in redacted

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        "%s",
        (message,),
        None,
    )
    assert ArtifactTokenRedactionFilter().filter(record) is True
    assert secret not in str(record.args)

    class URLLike:
        def __str__(self) -> str:
            return f"http://testserver/api/artifacts/download/{secret}"

    object_record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "HTTP Request: %s",
        (URLLike(),),
        None,
    )
    assert ArtifactTokenRedactionFilter().filter(object_record) is True
    assert secret not in object_record.getMessage()


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: Bearer top-secret-value",
        "X-Admin-Token: top-secret-value",
        "X-Student-Token=top-secret-value",
        "X-CSRF-Token: top-secret-value",
        "Idempotency-Key: top-secret-value",
        "Bearer top-secret-value",
        "https://service-user:top-secret-value@example.invalid/path",
        "GET /path?idempotency_key=top-secret-value&safe=ok",
    ],
)
def test_access_log_filter_redacts_header_and_basic_auth_credentials(message):
    redacted = redact_artifact_token(message)
    assert "top-secret-value" not in redacted
    assert "[REDACTED]" in redacted


def _production_shaped_settings() -> Settings:
    return Settings(
        DEBUG=False,
        DATABASE_URL="postgresql://database.invalid/tsing_radar",
        AUTO_CREATE_SCHEMA=False,
        ADMIN_TOKEN="M" * 32,
        SESSION_HMAC_SECRET="S" * 32,
        ARTIFACT_SIGNING_SECRET="A" * 32,
        QXD_API_KEY="K" * 32,
        QXD_END_USER_SIGNING_SECRET="Q" * 32,
        WEB_COOKIE_SECURE=True,
        FILE_SCAN_MODE="clamav",
        CLAMAV_HOST="scanner.internal.example",
        OBJECT_STORE_BACKEND="s3",
        S3_BUCKET="private-bucket",
        S3_ACCESS_KEY_ID="configured-but-not-used",
        S3_SECRET_ACCESS_KEY="configured-but-not-used",
        S3_SERVER_SIDE_ENCRYPTION="AES256",
        PUBLIC_BASE_URL="https://radar.tsinghua.edu.cn",
        ALLOW_TEST_PUBLIC_BASE_URL=False,
    )


def test_offline_preflight_never_promotes_static_shape_to_production_ready():
    settings = _production_shaped_settings()
    report = run_offline_preflight(settings, repository_root=REPOSITORY_ROOT)
    assert report["network_requests_performed"] is False
    assert report["external_credentials_used"] is False
    assert report["deployment_performed"] is False
    assert report["status"] == "blocked"
    assert all(item["status"] == "passed" for item in report["checks"])
    assert "database.real_postgresql_two_connection_races" in report["blockers"]
    assert "storage.object_read_streaming_hard_limit" in report["blockers"]
    serialized = json.dumps(report)
    assert settings.S3_ACCESS_KEY_ID not in serialized
    assert settings.S3_SECRET_ACCESS_KEY not in serialized
    assert settings.QXD_API_KEY not in serialized


def test_reserved_test_domain_is_not_a_production_preflight_pass():
    settings = _production_shaped_settings()
    settings.PUBLIC_BASE_URL = "https://agent.example.edu"
    settings.ALLOW_TEST_PUBLIC_BASE_URL = True
    report = run_offline_preflight(settings, repository_root=REPOSITORY_ROOT)
    public_base = next(
        item
        for item in report["checks"]
        if item["id"] == "delivery.public_base_shape"
    )
    assert public_base["status"] == "failed"


def test_default_short_and_reused_admin_tokens_fail_production_preflight():
    settings = _production_shaped_settings()
    for admin_token in (None, "short", settings.SESSION_HMAC_SECRET):
        settings.ADMIN_TOKEN = admin_token
        report = run_offline_preflight(
            settings,
            repository_root=REPOSITORY_ROOT,
        )
        secret_check = next(
            item
            for item in report["checks"]
            if item["id"]
            == "secrets.independent_32_byte_material_including_admin"
        )
        assert secret_check["status"] == "failed"


def test_production_rejects_single_user_qxd_trial_compatibility_mode():
    settings = _production_shaped_settings()
    settings.QXD_TRIAL_SINGLE_USER_MODE = True
    with pytest.raises(RuntimeError, match="不得启用清小搭单人试聊"):
        validate_production_secrets(settings)


def test_admin_tokens_never_appear_in_response_or_request_logs(caplog):
    real_test_token = "test-admin-token-not-for-production"
    wrong_test_token = "wrong-admin-token-must-not-leak"
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            accepted = client.post(
                "/api/train/trigger",
                headers={"X-Admin-Token": real_test_token},
            )
            rejected = client.post(
                "/api/train/trigger",
                headers={"X-Admin-Token": wrong_test_token},
            )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "blocked_by_data_readiness_gate"
    assert accepted.json()["weights"] is None
    assert rejected.status_code == 403
    combined = "\n".join(
        [
            accepted.text,
            rejected.text,
            *(record.getMessage() for record in caplog.records),
        ]
    )
    assert real_test_token not in combined
    assert wrong_test_token not in combined
    assert get_model_weights() is None


def test_isolated_rehearsal_cli_passes_without_external_actions():
    completed = subprocess.run(
        [sys.executable, "backend/scripts/a7_rehearsal.py"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "passed"
    assert report["summary"]["failed"] == 0
    assert report["safety"] == {
        "network_requests_performed": False,
        "real_credentials_used": False,
        "public_urls_created": False,
        "external_applications_submitted": False,
        "real_user_data_used": False,
    }
    by_id = {item["id"]: item for item in report["steps"]}
    assert by_id["qxd_preconfirmation_state"]["status"] == "passed"
    assert (
        by_id["qxd_preconfirmation_state"]["evidence"][
            "recommendation_before_confirmation"
        ]
        is False
    )
    assert (
        by_id["qxd_interview_confirm_match"]["evidence"][
            "sequential_http_rounds"
        ]
        == 7
    )
    assert (
        by_id["qxd_interview_confirm_match"]["evidence"][
            "assistant_messages_carried_forward"
        ]
        is True
    )
    assert (
        by_id["qxd_interview_confirm_match"]["evidence"][
            "final_sse_contract"
        ]
        is True
    )
