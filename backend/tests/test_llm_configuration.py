"""Unified development/production LLM credential contracts."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.advisor import LLMMessage
from app.services import data_loader
from app.services import llm as llm_service
from app import main as main_module


SYNTHETIC_KEY = "synthetic-llm-credential-not-live"


def _secret(path: Path, content: str = SYNTHETIC_KEY) -> str:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return str(path)


@pytest.mark.parametrize("provider", ["glm", "deepseek"])
def test_production_resolves_one_file_backed_provider(tmp_path, provider):
    path = _secret(tmp_path / "llm_api_key")
    configured = Settings(
        _env_file=None,
        PRODUCTION_DEPLOYMENT=True,
        LLM_PROVIDER=provider,
        LLM_API_KEY_FILE=path,
    )

    assert configured.configured_llm_providers == (provider,)
    assert configured.llm_credentials == ((provider, SYNTHETIC_KEY),)
    assert configured.llm_secret_file_permissions_valid is True
    assert SYNTHETIC_KEY not in repr(configured)


def test_development_keeps_existing_direct_provider_order():
    configured = Settings(
        _env_file=None,
        GLM_API_KEY="synthetic-development-glm",
        DEEPSEEK_API_KEY="synthetic-development-deepseek",
    )
    assert configured.configured_llm_providers == ("glm", "deepseek")


def test_production_can_explicitly_disable_llm_without_credentials():
    configured = Settings(
        _env_file=None,
        PRODUCTION_DEPLOYMENT=True,
        LLM_ENABLED=False,
    )

    assert configured.configured_llm_providers == ()
    assert configured.llm_credentials == ()
    assert configured.llm_secret_file_permissions_valid is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"LLM_PROVIDER": "glm"},
        {"GLM_API_KEY": SYNTHETIC_KEY},
    ],
)
def test_disabled_llm_rejects_credentials(kwargs):
    with pytest.raises(ValidationError, match="LLM_ENABLED=true"):
        Settings(_env_file=None, LLM_ENABLED=False, **kwargs)


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"PRODUCTION_DEPLOYMENT": True}, "requires LLM_PROVIDER"),
        (
            {
                "PRODUCTION_DEPLOYMENT": True,
                "LLM_PROVIDER": "glm",
                "GLM_API_KEY": "synthetic-direct-key",
            },
            "rejects direct",
        ),
        (
            {
                "LLM_PROVIDER": "glm",
                "DEEPSEEK_API_KEY": "synthetic-wrong-branch",
            },
            "must match",
        ),
    ],
)
def test_ambiguous_or_mismatched_provider_configuration_is_rejected(
    kwargs,
    reason,
):
    with pytest.raises(ValidationError, match=reason):
        Settings(_env_file=None, **kwargs)


def test_file_and_direct_provider_credentials_are_mutually_exclusive(tmp_path):
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings(
            _env_file=None,
            LLM_PROVIDER="glm",
            LLM_API_KEY_FILE=_secret(tmp_path / "llm_api_key"),
            GLM_API_KEY="synthetic-direct-key",
        )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "synthetic\x00invalid",
        "x" * (64 * 1024 + 1),
    ],
)
def test_invalid_llm_secret_file_content_fails_closed(tmp_path, content):
    path = tmp_path / "llm_api_key"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError, match="secret file"):
        Settings(
            _env_file=None,
            LLM_PROVIDER="glm",
            LLM_API_KEY_FILE=str(path),
        )


def test_missing_and_symlinked_llm_secret_files_fail_closed(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValidationError, match="unavailable"):
        Settings(
            _env_file=None,
            LLM_PROVIDER="glm",
            LLM_API_KEY_FILE=str(missing),
        )

    target = tmp_path / "target"
    _secret(target)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValidationError, match="unavailable"):
        Settings(
            _env_file=None,
            LLM_PROVIDER="glm",
            LLM_API_KEY_FILE=str(link),
        )


def test_llm_secret_permissions_reject_group_or_other_access(tmp_path):
    path = Path(_secret(tmp_path / "llm_api_key"))
    path.chmod(0o640)
    configured = Settings(
        _env_file=None,
        PRODUCTION_DEPLOYMENT=True,
        LLM_PROVIDER="glm",
        LLM_API_KEY_FILE=str(path),
    )
    assert configured.llm_secret_file_permissions_valid is False


@pytest.mark.asyncio
async def test_llm_service_uses_only_resolved_selected_provider(monkeypatch):
    configured = Settings(
        _env_file=None,
        LLM_PROVIDER="deepseek",
        DEEPSEEK_API_KEY=SYNTHETIC_KEY,
    )
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return Response()

    monkeypatch.setattr(llm_service, "settings", configured)
    monkeypatch.setattr(llm_service.httpx, "AsyncClient", Client)
    monkeypatch.setattr(llm_service.logger, "disabled", False)
    monkeypatch.setattr(llm_service.logger, "propagate", True)
    reply = await llm_service.llm_complete(
        [LLMMessage(role="user", content="synthetic prompt")]
    )

    assert reply == "ok"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"] == {
        "Authorization": f"Bearer {SYNTHETIC_KEY}",
        "Content-Type": "application/json",
    }
    assert captured["payload"]["model"] == "deepseek-chat"


@pytest.mark.asyncio
async def test_interview_enhancement_rejects_questions(monkeypatch):
    configured = Settings(
        _env_file=None,
        LLM_PROVIDER="glm",
        GLM_API_KEY=SYNTHETIC_KEY,
    )

    async def fake_result(_messages, **_kwargs):
        return llm_service.LLMCompletionResult(
            text="听起来很棒，要不要继续聊聊？",
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(llm_service, "settings", configured)
    monkeypatch.setattr(llm_service, "_llm_complete_result", fake_result)
    result = await llm_service.enhance_interview_reply(
        user_message="我喜欢机器人",
        fixed_reply="你更偏好理论还是工程？",
    )
    assert result.status == "unavailable"
    assert result.text is None
    assert result.provider == "glm"


@pytest.mark.asyncio
async def test_llm_failure_logs_safe_provider_metadata(monkeypatch, caplog):
    configured = Settings(
        _env_file=None,
        LLM_PROVIDER="glm",
        GLM_API_KEY=SYNTHETIC_KEY,
    )

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            raise RuntimeError("synthetic provider failure without secret")

    monkeypatch.setattr(llm_service, "settings", configured)
    monkeypatch.setattr(llm_service.httpx, "AsyncClient", Client)
    monkeypatch.setattr(llm_service.logger, "disabled", False)
    monkeypatch.setattr(llm_service.logger, "propagate", True)
    with caplog.at_level(logging.WARNING, logger="app.services.llm"):
        reply = await llm_service.llm_complete(
            [LLMMessage(role="user", content="synthetic prompt")]
        )
    assert reply is None
    assert "provider=glm" in caplog.text
    assert "model=glm-4-flash" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert SYNTHETIC_KEY not in caplog.text


@pytest.mark.asyncio
async def test_startup_log_exposes_provider_but_not_secret(
    monkeypatch,
    caplog,
):
    configured = Settings(
        _env_file=None,
        GLM_API_KEY=SYNTHETIC_KEY,
    )
    monkeypatch.setattr(main_module, "settings", configured)
    monkeypatch.setattr(main_module.logger, "disabled", False)
    monkeypatch.setattr(main_module.logger, "propagate", True)
    monkeypatch.setattr("app.db.session.init_db", lambda: None)
    monkeypatch.setattr(
        data_loader,
        "mentor_data_summary",
        lambda: {
            "total_records": 0,
            "published_records": 0,
            "withheld_records": 0,
            "policy": "verified_only",
        },
    )

    with caplog.at_level(logging.INFO, logger="app.main"):
        await main_module.startup_event()

    assert "provider=glm" in caplog.text
    assert "密钥已配置" in caplog.text
    assert SYNTHETIC_KEY not in caplog.text
