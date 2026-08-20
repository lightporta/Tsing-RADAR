"""导师邮箱验证码登录：签发/限频/校验/会话绑定/登出/CSRF。"""

from __future__ import annotations

import logging
import re

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.mentor_account import MentorAccount
from tests.mentor_helpers import (
    _code_from_logs,
    mentor_login,
    mentor_web_client,
)

EMAIL = "mentor01@tsinghua.edu.cn"


def test_email_code_requires_tsinghua_suffix_and_prints_code_to_console_log(
    caplog,
):
    client, headers = mentor_web_client()
    with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
        response = client.post(
            "/api/mentor/auth/email-code",
            headers=headers,
            json={"email": "someone@gmail.com"},
        )
    assert response.status_code == 422
    assert "清华邮箱" in response.json()["detail"]

    with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
        response = client.post(
            "/api/mentor/auth/email-code",
            headers=headers,
            json={"email": EMAIL},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert body["expires_in"] > 0
    code = _code_from_logs(caplog, EMAIL)
    assert re.fullmatch(r"\d{6}", code)


def test_email_code_resend_is_rate_limited_and_respects_daily_limit(caplog):
    client, headers = mentor_web_client()
    for _ in range(2):
        with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
            response = client.post(
                "/api/mentor/auth/email-code",
                headers=headers,
                json={"email": EMAIL},
            )
    # 第二次（60 秒内）被限频拒绝
    assert response.status_code == 429


def test_wrong_code_fails_and_exhausts_attempts(caplog):
    client, headers = mentor_web_client()
    with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
        client.post(
            "/api/mentor/auth/email-code",
            headers=headers,
            json={"email": EMAIL},
        )
    code = _code_from_logs(caplog, EMAIL)
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(6):
        response = client.post(
            "/api/mentor/auth/login",
            headers=headers,
            json={"email": EMAIL, "code": wrong},
        )
    assert response.status_code == 422
    assert "次数过多" in response.json()["detail"]


def test_login_binds_web_session_and_logout_unbinds(caplog):
    client, headers = mentor_web_client()

    status = client.get("/api/mentor/auth/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["logged_in"] is False

    mentor_login(client, headers, caplog, email=EMAIL)
    status = client.get("/api/mentor/auth/status", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["logged_in"] is True
    assert body["status"] == "unclaimed"
    assert body["advisor_id"] is None

    with SessionLocal() as db:
        account = (
            db.query(MentorAccount)
            .filter(MentorAccount.email == EMAIL)
            .one()
        )
        assert account.bound_session_id is not None
        assert account.email_verified_at is not None

    response = client.post("/api/mentor/auth/logout", headers=headers)
    assert response.status_code == 200
    assert response.json()["logged_in"] is False
    status = client.get("/api/mentor/auth/status", headers=headers)
    assert status.json()["logged_in"] is False

    with SessionLocal() as db:
        account = (
            db.query(MentorAccount)
            .filter(MentorAccount.email == EMAIL)
            .one()
        )
        assert account.bound_session_id is None


def test_login_requires_csrf_and_protected_endpoint_requires_binding(caplog):
    client, _ = mentor_web_client()
    response = client.post(
        "/api/mentor/auth/email-code",
        json={"email": EMAIL},
    )
    assert response.status_code == 403

    client, headers = mentor_web_client()
    response = client.get("/api/mentor", headers=headers)
    assert response.status_code == 401
