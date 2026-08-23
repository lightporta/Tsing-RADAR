"""网页端 /v1/llm/chat 接入 Agent 编排（v4.3.x）的接线测试套件。

核心原则（红线，与 test_agent_orchestrator.py 一致）：
- 全部 GLM HTTP 交互用脚本化假 httpx.AsyncClient mock（monkeypatch 替换
  httpx.AsyncClient），绝不依赖真实 key、绝不发起真实网络请求；
- 凭据用明显假值 ("glm", "test-key")，通过 object.__setattr__ 显式覆盖
  全局 settings 实例 __dict__ 中的 _llm_credentials（conftest 已默认
  中和凭据，因此旧 enhance 路径测试不受影响）；
- Agent 激活闸门：凭据 + AGENT_ORCHESTRATION_ENABLED + 非 recommend_ready；
  任何 Agent 失败都确定性降级状态机文本，不再调 enhance_interview_reply；
- 本文件禁止出现任何真实 API key。
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import llm as llm_module
from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.dialogue_state import DialogueSession
from app.services.agent_orchestrator import AgentTurnResult
from app.services.chat_expression import MAX_PREVIOUS_REPLY_CHARS

# —— 测试凭据：明显假值（绝不使用真实 key）——
FAKE_GLM_KEY = "test-key"
FAKE_GLM_CREDENTIALS = (("glm", FAKE_GLM_KEY),)

client = TestClient(app)
WEB_HEADERS: dict[str, str] = {}

# research_mode 单选题（第二题）的全部选项原文（逐字锚点）
RESEARCH_MODE_OPTIONS = (
    "更爱追根究底：理论与原理",
    "更爱把想法做出来：工程与落地",
    "理论和落地都想兼顾",
    "还在探索，暂不确定",
)
RESEARCH_MODE_PROMPT = (
    "面对同一研究主题，你更偏好理论与原理、工程与落地，还是两者结合？"
)

# 脚本化 Agent 成功回复：自然承接 + 题干 + 全部选项原文（逐字锚点齐全）
AGENT_SUCCESS_REPLY = (
    "好嘞，人工智能和机器人这个组合挺有意思的～那接着聊聊你做事的口味：\n"
    f"{RESEARCH_MODE_PROMPT}\n"
    "1. 更爱追根究底：理论与原理\n"
    "2. 更爱把想法做出来：工程与落地\n"
    "3. 理论和落地都想兼顾\n"
    "4. 还在探索，暂不确定"
)

# 首条用户消息：回答研究兴趣题后，状态机推进到 research_mode 单选题
FIRST_USER_MESSAGE = "我想研究人工智能和机器人方向"


@pytest.fixture(autouse=True)
def _credentials_sandbox():
    """每个测试前保存、后恢复 settings 实例 __dict__ 中的凭据状态。

    凭据注入必须用 object.__setattr__（见 _use_fake_credentials 说明），
    它绕过 monkeypatch，因此这里手动还原，防止假凭据/空凭据状态泄漏到
    同进程的其它测试。
    """
    original_present = "_llm_credentials" in settings.__dict__
    original_value = settings.__dict__.get("_llm_credentials")
    yield
    if original_present:
        object.__setattr__(settings, "_llm_credentials", original_value)
    else:
        settings.__dict__.pop("_llm_credentials", None)


@pytest.fixture(autouse=True)
def _web_session_headers():
    """网页端 student 认证：/api/session 建立 Web 会话 + CSRF 头。"""
    response = client.get("/api/session")
    assert response.status_code == 200
    WEB_HEADERS.clear()
    WEB_HEADERS["X-CSRF-Token"] = client.cookies["tsing_radar_csrf"]


# ============================================================================
# 通用 mock 基建：脚本化 GLM HTTP（照抄 test_agent_orchestrator.py）
# ============================================================================


class _ScriptedResponse:
    """假 httpx.Response：只实现编排器用到的 raise_for_status / json。"""

    def __init__(self, *, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code < 400:
            return None
        # 用真实 httpx 异常类型，保证编排器的 except 分支与日志口径一致
        request = httpx.Request("POST", "https://fake-glm.invalid/chat/completions")
        raise httpx.HTTPStatusError(
            f"HTTP {self.status_code}",
            request=request,
            response=httpx.Response(self.status_code, request=request),
        )

    def json(self):
        return self._payload


def _patch_scripted_glm(monkeypatch, script: list) -> list[dict]:
    """把 httpx.AsyncClient 替换为脚本化假客户端，返回调用记录列表。

    超出脚本长度的调用直接 AssertionError —— 红线：绝不发生预期外的
    GLM 请求（更不会是真实网络请求）。
    """
    calls: list[dict] = []

    class _ScriptedClient:
        def __init__(self, *, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def post(self, url, *, headers=None, json=None):
            calls.append({"url": url, "headers": headers, "payload": json})
            if len(calls) > len(script):
                raise AssertionError("GLM 调用次数超出脚本预设（意外请求）")
            step = script[len(calls) - 1]
            if isinstance(step, Exception):
                raise step
            if isinstance(step, dict):
                return _ScriptedResponse(payload={"choices": [{"message": step}]})
            return step

    monkeypatch.setattr(httpx, "AsyncClient", _ScriptedClient)
    return calls


def _use_fake_credentials(credentials=FAKE_GLM_CREDENTIALS) -> None:
    """显式覆盖全局 settings 的 LLM 凭据（明显假值，绝不读真实 key）。"""
    object.__setattr__(settings, "_llm_credentials", credentials)


def _post_web_chat(session_id: str, message: str):
    """以网页端 student 认证调用 /v1/llm/chat?stream=false。"""
    return client.post(
        "/api/v1/llm/chat",
        params={"stream": "false"},
        headers=WEB_HEADERS,
        json={
            "session_id": session_id,
            "messages": [{"role": "user", "content": message}],
        },
    )


def _new_session_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _option_labels(payload: dict) -> list[str]:
    return [
        option["label"]
        for option in payload["current_question"]["options"]
    ]


# ============================================================================
# 接线场景
# ============================================================================


class TestWebAgentWiring:
    """网页端 /v1/llm/chat 的 Agent 激活、成功、降级与旧路径兼容。"""

    def test_agent_success_replaces_reply_and_persists_expression(
        self, monkeypatch
    ):
        """场景 1：Agent 成功（脚本化回复含全部锚点）→ assistant_message
        为 Agent 文本、assistant_mode=agent_orchestration；
        interview_last_expression 已持久化到会话存储。"""
        _use_fake_credentials()
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)
        calls = _patch_scripted_glm(
            monkeypatch, [{"content": AGENT_SUCCESS_REPLY}]
        )
        session_id = _new_session_id("web-agent-ok")

        response = _post_web_chat(session_id, FIRST_USER_MESSAGE)
        assert response.status_code == 200
        payload = response.json()
        # 单选题轮：状态机已推进到 research_mode
        assert payload["current_question"]["dimension"] == "research_mode"
        assert _option_labels(payload) == list(RESEARCH_MODE_OPTIONS)
        # Agent 接管回复渲染
        assert payload["assistant_mode"] == "agent_orchestration"
        assert payload["agent_status"] == "success"
        assert payload["agent_tools"] == "none"
        assert payload["assistant_message"] == AGENT_SUCCESS_REPLY
        assert len(calls) == 1
        # 请求头使用假凭据（绝不携带真实 key）
        assert calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_GLM_KEY}"
        # 状态注入：自然度标注 + 题干 + 选项原文（自然度措辞落地）
        system_message = calls[0]["payload"]["messages"][0]
        assert system_message["role"] == "system"
        assert RESEARCH_MODE_PROMPT in system_message["content"]
        for label in RESEARCH_MODE_OPTIONS:
            assert label in system_message["content"]
        assert "选项前后的承接语可自由发挥" in system_message["content"]
        assert "像一位真诚的学长/学姐在聊天" in system_message["content"]
        # interview_last_expression 已持久化（下一轮 Agent 据此防重复承接）
        with SessionLocal() as db:
            record = (
                db.query(DialogueSession)
                .filter(DialogueSession.session_id == session_id)
                .one()
            )
            assert record.state["interview_last_expression"] == (
                AGENT_SUCCESS_REPLY[:MAX_PREVIOUS_REPLY_CHARS]
            )

    def test_agent_http_failure_degrades_to_deterministic_reply(
        self, monkeypatch, caplog
    ):
        """场景 2：Agent HTTP 500 → assistant_message 等于状态机确定性
        文本（research_mode 题干），且不再调 enhance_interview_reply
        （无二次 LLM 延迟）。"""
        _use_fake_credentials()
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)
        calls = _patch_scripted_glm(
            monkeypatch, [_ScriptedResponse(status_code=500)]
        )

        async def boom_enhance(*_args, **_kwargs):
            raise AssertionError(
                "Agent 路径失败降级不应再调用 enhance_interview_reply"
            )

        monkeypatch.setattr(
            llm_module, "enhance_interview_reply", boom_enhance
        )
        session_id = _new_session_id("web-agent-http500")

        with caplog.at_level(logging.INFO, logger="tsing_radar.llm"):
            response = _post_web_chat(session_id, FIRST_USER_MESSAGE)
        assert response.status_code == 200
        payload = response.json()
        # 确定性降级：回复即状态机 research_mode 题干原文（非 Agent 文本）
        assert payload["assistant_mode"] == "agent_orchestration"
        assert payload["agent_status"] == "failed"
        assert payload["assistant_message"] == RESEARCH_MODE_PROMPT
        assert payload["assistant_message"] == payload["current_question"]["prompt"]
        assert len(calls) == 1  # 只有一次（失败的）Agent 调用
        # info 日志：web_agent_turn status/tools
        assert any(
            "web_agent_turn status=failed tools=none" in record.getMessage()
            for record in caplog.records
        )

    def test_anchor_retry_recovers_to_success(self, monkeypatch):
        """场景 3：初次回复缺锚点（只回承接语）→ 缺锚点重试 → 重试回复
        补齐全部选项原文 → success 路径。"""
        _use_fake_credentials()
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)
        weak_reply = "好嘞，方向收到～那接下来想了解你偏理论还是偏工程。"
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                # 生产实测的失败形态：只回承接语，未逐字引用选项原文
                {"content": weak_reply},
                {"content": AGENT_SUCCESS_REPLY},
            ],
        )
        session_id = _new_session_id("web-agent-retry")

        response = _post_web_chat(session_id, FIRST_USER_MESSAGE)
        assert response.status_code == 200
        payload = response.json()
        assert payload["assistant_mode"] == "agent_orchestration"
        assert payload["agent_status"] == "success"
        assert payload["assistant_message"] == AGENT_SUCCESS_REPLY
        # 恰好 2 次请求：初次缺锚点 → 重试一次补齐
        assert len(calls) == 2
        assert "tools" not in calls[1]["payload"]
        # 重试请求末尾：带缺失锚点清单的纠正指令
        retry_last = calls[1]["payload"]["messages"][-1]
        assert retry_last["role"] == "user"
        for label in RESEARCH_MODE_OPTIONS:
            assert label in retry_last["content"]

    def test_agent_switch_off_uses_enhance_path(self, monkeypatch):
        """场景 4：AGENT_ORCHESTRATION_ENABLED=False → 不进 Agent，
        走旧 enhance_interview_reply 路径（可观测桩），assistant_mode
        为旧值。"""
        _use_fake_credentials()
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", False)

        async def boom_agent(*_args, **_kwargs):
            raise AssertionError("开关关闭时不应进入 Agent 编排")

        monkeypatch.setattr(llm_module, "run_agent_turn", boom_agent)

        enhance_calls: list[dict] = []

        async def fake_enhance(*, user_message, fixed_reply):
            enhance_calls.append(
                {"user_message": user_message, "fixed_reply": fixed_reply}
            )
            return SimpleNamespace(
                text="表达层旧路径承接语", provider="glm", status="available"
            )

        monkeypatch.setattr(
            llm_module, "enhance_interview_reply", fake_enhance
        )
        http_calls = _patch_scripted_glm(monkeypatch, [])
        session_id = _new_session_id("web-agent-off")

        response = _post_web_chat(session_id, FIRST_USER_MESSAGE)
        assert response.status_code == 200
        payload = response.json()
        # 旧路径：mode/enhancement 字段结构与取值保持不变
        assert (
            payload["assistant_mode"]
            == "fixed_interview_with_optional_llm_enhancement"
        )
        assert payload["enhancement_provider"] == "glm"
        assert payload["enhancement_status"] == "available"
        assert payload["assistant_message"] == (
            f"表达层旧路径承接语\n\n{payload['current_question']['prompt']}"
        )
        assert len(enhance_calls) == 1
        assert enhance_calls[0]["user_message"] == FIRST_USER_MESSAGE
        assert http_calls == []  # 全程零 LLM HTTP

    def test_missing_credentials_use_enhance_path(self, monkeypatch):
        """场景 5：无凭据 → 不进 Agent（同款降级），走旧 enhance 路径。"""
        _use_fake_credentials(())
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)

        async def boom_agent(*_args, **_kwargs):
            raise AssertionError("无凭据时不应进入 Agent 编排")

        monkeypatch.setattr(llm_module, "run_agent_turn", boom_agent)

        enhance_calls: list = []

        async def disabled_enhance(*, user_message, fixed_reply):
            enhance_calls.append(user_message)
            return SimpleNamespace(text=None, provider=None, status="disabled")

        monkeypatch.setattr(
            llm_module, "enhance_interview_reply", disabled_enhance
        )
        http_calls = _patch_scripted_glm(monkeypatch, [])
        session_id = _new_session_id("web-agent-nocred")

        response = _post_web_chat(session_id, FIRST_USER_MESSAGE)
        assert response.status_code == 200
        payload = response.json()
        # 旧路径 + 表达层 disabled 降级：确定性题干原文
        assert (
            payload["assistant_mode"]
            == "fixed_interview_with_optional_llm_enhancement"
        )
        assert payload["enhancement_status"] == "disabled"
        assert payload["assistant_message"] == RESEARCH_MODE_PROMPT
        assert enhance_calls == [FIRST_USER_MESSAGE]
        assert http_calls == []

    def test_state_context_and_anchors_passed_to_agent(self, monkeypatch):
        """场景 6：单选题轮的 run_agent_turn 入参——state_context 含
        题干与选项原文，required_anchors 为选项 label 列表。"""
        _use_fake_credentials()
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)
        captured: dict = {}

        async def spy_agent(_db, **kwargs):
            captured.update(kwargs)
            return AgentTurnResult(None, "failed", ())

        monkeypatch.setattr(llm_module, "run_agent_turn", spy_agent)
        http_calls = _patch_scripted_glm(monkeypatch, [])
        session_id = _new_session_id("web-agent-spy")

        response = _post_web_chat(session_id, FIRST_USER_MESSAGE)
        assert response.status_code == 200
        # 状态注入文本：题干 + 全部选项原文 + 画像进度
        state_context = captured["state_context"]
        assert RESEARCH_MODE_PROMPT in state_context
        for label in RESEARCH_MODE_OPTIONS:
            assert label in state_context
        assert "画像进度" in state_context
        # 锚点 = 全部选项 label 原文列表
        assert captured["required_anchors"] == list(RESEARCH_MODE_OPTIONS)
        # 消息过滤：只送 user/assistant（system 被剔除）
        assert [m.role for m in captured["messages"]] == ["user"]
        assert captured["messages"][0].content == FIRST_USER_MESSAGE
        assert captured["session_id"] == session_id
        assert http_calls == []  # spy 替换了编排器，零 HTTP
