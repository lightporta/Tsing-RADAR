"""网页免认证测试模式与清小搭 P-A user 字段映射。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.identity import resolve_qxd_user_principal

client = TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-qxd-key"}


def _cleanup_pa_identities() -> None:
    from app.db.session import SessionLocal
    from app.models.identity import ExternalIdentity
    from app.models.questionnaire_session import QuestionnaireSession

    with SessionLocal() as db:
        db.query(ExternalIdentity).filter(
            ExternalIdentity.provider == "qxd_user"
        ).delete(synchronize_session=False)
        db.query(QuestionnaireSession).filter(
            QuestionnaireSession.student_id.like("usr_%")
        ).delete(synchronize_session=False)
        db.commit()


# —— 网页测试模式 ——


def test_web_test_mode_status_endpoint_defaults_active():
    resp = client.get("/api/web-test-mode")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["enabled"] is True
    assert payload["active"] is True
    assert payload["label"] == "未实名认证测试身份"


def test_web_test_mode_expired_blocks_web_channel(monkeypatch):
    from app.core.config import settings

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    monkeypatch.setattr(settings, "WEB_TEST_MODE_EXPIRES_AT", past)
    assert client.get("/api/session").status_code == 403
    documents = client.get("/api/documents")
    assert documents.status_code == 403
    assert "测试模式已到期" in documents.json()["detail"]
    # 公开状态端点保持可用：前端要能展示到期标注
    status = client.get("/api/web-test-mode")
    assert status.status_code == 200
    assert status.json()["active"] is False


def test_web_test_mode_disabled_fails_closed(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WEB_TEST_MODE_ENABLED", False)
    assert client.get("/api/session").status_code == 503


def test_web_test_mode_future_expiry_keeps_channel_open(monkeypatch):
    from app.core.config import settings

    future = datetime.now(timezone.utc) + timedelta(days=7)
    monkeypatch.setattr(settings, "WEB_TEST_MODE_EXPIRES_AT", future)
    assert client.get("/api/session").status_code == 200
    status = client.get("/api/web-test-mode").json()
    assert status["active"] is True
    assert status["expires_at"] is not None


def test_production_preflight_requires_web_test_mode_expiry(monkeypatch):
    from app.core.config import settings
    from app.services.preflight import run_l1_production_preflight

    monkeypatch.setattr(settings, "PRODUCTION_DEPLOYMENT", True)
    monkeypatch.setattr(settings, "WEB_TEST_MODE_ENABLED", True)
    monkeypatch.setattr(settings, "WEB_TEST_MODE_EXPIRES_AT", None)
    report = run_l1_production_preflight(settings)
    blockers = set(report["blockers"])
    assert "web.test_mode_expiry_configured" in blockers


# —— 清小搭 P-A：body 稳定 user 字段映射持久主体 ——


def test_pa_user_principal_mapping_is_stable_and_isolated():
    from app.db.session import SessionLocal

    _cleanup_pa_identities()
    try:
        with SessionLocal() as db:
            first = resolve_qxd_user_principal(db, user_id="pa-user-1")
            repeat = resolve_qxd_user_principal(db, user_id="pa-user-1")
            other = resolve_qxd_user_principal(db, user_id="pa-user-2")
        assert first.persistent is True
        assert first.channel == "qxd"
        assert first.subject_id == repeat.subject_id
        assert first.subject_id != other.subject_id
    finally:
        _cleanup_pa_identities()


def test_chat_body_user_field_yields_persistent_principal():
    from app.db.session import SessionLocal
    from app.models.questionnaire_session import QuestionnaireSession

    _cleanup_pa_identities()
    try:
        body = {
            "user": "pa-chat-user-1",
            "messages": [{"role": "user", "content": "你好"}],
        }
        resp = client.post(
            "/v1/chat/completions",
            json=body,
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        with SessionLocal() as db:
            sessions = (
                db.query(QuestionnaireSession)
                .filter(
                    QuestionnaireSession.student_id.like("usr_%")
                )
                .all()
            )
            assert sessions, "P-A user 字段应产生持久主体访谈会话"
            assert all(
                not session.student_id.startswith("qreq_")
                for session in sessions
            )
    finally:
        _cleanup_pa_identities()


def test_chat_without_user_and_headers_stays_request_scoped():
    from app.db.session import SessionLocal
    from app.models.questionnaire_session import QuestionnaireSession

    body = {"messages": [{"role": "user", "content": "你好"}]}
    resp = client.post(
        "/v1/chat/completions",
        json=body,
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        sessions = (
            db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.student_id.like("qreq_%"))
            .all()
        )
        assert sessions, "无 user 字段且无 header claim 时保持单请求主体"
