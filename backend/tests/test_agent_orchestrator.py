"""v4.3.0 全 Agent 化 GLM 编排（agent_orchestrator）红线测试套件。

核心原则（红线）：
- 全部 GLM HTTP 交互用脚本化假 httpx.AsyncClient mock（与
  test_llm_configuration.py 同款做法：monkeypatch 替换 httpx.AsyncClient），
  绝不依赖真实 key、绝不发起真实网络请求；
- 凭据用明显假值 ("glm", "test-key")，通过 object.__setattr__ 显式覆盖
  全局 settings 实例 __dict__ 中的 _llm_credentials（普通 setattr 会被
  __pydantic_private__ 遮蔽不生效），不受本机 backend/.env 影响；
- 任何失败（无凭据 / HTTP 与网络异常 / 空回复 / 超长 / 锚点缺失）都必须
  fail-closed：text=None + status 明确，由调用方降级确定性管线；
- 本文件禁止出现任何真实 API key。
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import app.services.prompts as prompts_module
from app.api.v1 import chat as qxd_chat
from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.schemas.advisor import LLMMessage
from app.services import agent_orchestrator as orchestrator
from app.services import tools_registry
from app.services.agent_orchestrator import AgentTurnResult, run_agent_turn
from app.services.prompts import load_prompt_template

# —— 测试凭据：明显假值（绝不使用真实 key）——
FAKE_GLM_KEY = "test-key"
FAKE_GLM_CREDENTIALS = (("glm", FAKE_GLM_KEY),)

# 常用的最终回复文本（无锚点要求场景的通用收尾）
FINAL_TEXT = "明白了，那我们继续聊聊：你更偏好算法理论研究，还是实际应用？"

# 清小搭协议端点鉴权（conftest 注入的测试用 QXD key）
AUTH = {"Authorization": "Bearer test-qxd-key"}

client = TestClient(app)


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


# ============================================================================
# 通用 mock 基建：脚本化 GLM HTTP（绝不真实网络请求）
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

    script 每项（按调用顺序消费）：
    - dict：GLM choices[0].message 载荷 → 200 响应；
    - Exception 实例：post 直接抛出（网络 / HTTP 异常场景）；
    - _ScriptedResponse：原样返回（自定义状态码场景）。
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
    """显式覆盖全局 settings 的 LLM 凭据（明显假值，绝不读真实 key）。

    注意：不能用 monkeypatch.setattr / 普通 setattr —— Settings 的
    model_validator 用 object.__setattr__ 把 _llm_credentials 写进实例
    __dict__，普通 setattr 只会更新 __pydantic_private__，被 __dict__
    遮蔽而不生效（test_consultation.py 的同款注入在本机即因此失效）。
    这里同样用 object.__setattr__ 直写 __dict__，由 _credentials_sandbox
    夹具在测试结束后还原；agent_orchestrator / chat / chat_expression
    共享同一个 settings 单例，覆盖后三处一致生效。
    """
    object.__setattr__(settings, "_llm_credentials", credentials)


def _tool_call(call_id: str, name: str, arguments: str) -> dict:
    """构造 OpenAI function-calling 形态的 tool_call 条目。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _tool_call_message(*calls: dict) -> dict:
    """构造带 tool_calls 的 GLM assistant 消息。"""
    return {"content": None, "tool_calls": list(calls)}


def _user_messages() -> list[LLMMessage]:
    """标准输入消息（单条用户消息）。"""
    return [LLMMessage(role="user", content="我对强化学习感兴趣")]


def _tool_messages_of(call: dict) -> list[dict]:
    """从某次 GLM 请求载荷中取出全部 role=tool 的回填消息。"""
    return [m for m in call["payload"]["messages"] if m.get("role") == "tool"]


# ============================================================================
# A. 编排器单元（直接调 run_agent_turn）
# ============================================================================


class TestCredentialAndPlainTurn:
    """场景 1-2：凭据闸门与纯文本回合。"""

    @pytest.mark.asyncio
    async def test_no_credentials_disabled_without_http(self, monkeypatch):
        """场景 1：无凭据 → status=disabled、text=None，HTTP post 从未被调用。"""
        _use_fake_credentials(())
        calls = _patch_scripted_glm(monkeypatch, [])
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-no-cred",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "disabled"
        assert result.text is None
        assert result.tool_names == ()
        assert calls == []

    @pytest.mark.asyncio
    async def test_plain_text_turn_success(self, monkeypatch):
        """场景 2：纯文本回合 → success、text 正确、tool_names 为空。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(monkeypatch, [{"content": FINAL_TEXT}])
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-plain",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "success"
        assert result.text == FINAL_TEXT
        assert result.tool_names == ()
        assert len(calls) == 1
        # 请求头使用假凭据（绝不携带真实 key），载荷为标准 GLM 形态
        assert calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_GLM_KEY}"
        assert calls[0]["url"] == f"{settings.GLM_BASE_URL}/chat/completions"
        assert calls[0]["payload"]["model"] == settings.GLM_CHAT_MODEL
        # 系统消息置顶且注入确定性状态上下文
        first_message = calls[0]["payload"]["messages"][0]
        assert first_message["role"] == "system"
        assert "当前题目：第 1 题" in first_message["content"]


class TestToolLoop:
    """场景 3-7：工具调用循环与上限 / fail-closed 行为。"""

    @pytest.mark.asyncio
    async def test_single_tool_call_round_trip(self, monkeypatch):
        """场景 3：一次工具调用 + 最终文本 → 两次 GLM 请求、工具名被记录。"""
        _use_fake_credentials()
        final = "李琦老师的相关情况如下：同学们普遍提到组会节奏稳定。"
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(
                    _tool_call(
                        "call_1", "query_mentor_knowledge", '{"name": "李琦"}'
                    )
                ),
                {"content": final},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-one-tool",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "success"
        assert result.text == final
        assert result.tool_names == ("query_mentor_knowledge",)
        assert len(calls) == 2
        # 第二次请求回填了 assistant(tool_calls) + tool 结果消息
        tool_messages = _tool_messages_of(calls[1])
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "call_1"
        assert "李琦" in tool_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_multi_round_tool_loop_drops_tools_after_cap(self, monkeypatch):
        """场景 4：三轮工具循环 → 共 4 次请求；最后一次不再携带 tools 键。"""
        _use_fake_credentials()
        loop_call = _tool_call("call_loop", "recall_memory", "{}")
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(loop_call),
                _tool_call_message(loop_call),
                _tool_call_message(loop_call),
                {"content": FINAL_TEXT},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-loop",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "success"
        assert result.text == FINAL_TEXT
        assert result.tool_names == ("recall_memory",) * 3
        assert len(calls) == 4
        # 前 3 次带 tools（tool_choice=auto），第 4 次达到上限后强制纯文本收尾
        for call in calls[:3]:
            assert "tools" in call["payload"]
            assert call["payload"]["tool_choice"] == "auto"
        assert "tools" not in calls[3]["payload"]

    @pytest.mark.asyncio
    async def test_tool_call_batch_capped_at_three(self, monkeypatch):
        """场景 5：单次响应 5 个 tool_calls → 只执行前 3 个（总量封顶）。"""
        _use_fake_credentials()
        executed: list[str] = []

        def fake_dispatch(runtime, *, name, arguments):
            executed.append(name)
            return f"工具 {name} 的确定性结果"

        # 场景允许 mock dispatch 直接断言执行数（避免依赖具体工具副作用）
        monkeypatch.setattr(orchestrator, "dispatch_tool_call", fake_dispatch)
        five_calls = [
            _tool_call(f"call_{index}", "recall_memory", "{}")
            for index in range(1, 6)
        ]
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(*five_calls),
                {"content": FINAL_TEXT},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-cap",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "success"
        assert result.text == FINAL_TEXT
        # 只执行前 3 个；超出的两个不执行（tool_names 同样只含 3 个）
        assert executed == ["recall_memory"] * 3
        assert result.tool_names == ("recall_memory",) * 3
        # 第二次请求里 5 个 tool_call_id 都有对应 tool 消息（消息序列完整），
        # 其中 2 条为「已达上限」确定性提示
        tool_messages = _tool_messages_of(calls[1])
        assert len(tool_messages) == 5
        capped = [
            m for m in tool_messages if m["content"] == "工具调用次数已达上限"
        ]
        assert len(capped) == 2
        # 达到上限后的收尾请求不再携带 tools
        assert "tools" not in calls[1]["payload"]

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_deterministic_error_and_continues(
        self, monkeypatch
    ):
        """场景 6：未知工具名 → dispatch 返回确定性错误文本，流程不崩、
        循环继续到最终文本。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(
                    _tool_call("call_1", "no_such_tool", "{}")
                ),
                {"content": FINAL_TEXT},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-unknown-tool",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "success"
        assert result.text == FINAL_TEXT
        assert result.tool_names == ("no_such_tool",)
        tool_messages = _tool_messages_of(calls[1])
        assert len(tool_messages) == 1
        assert tool_messages[0]["content"].startswith("未知工具「no_such_tool」")
        assert "可用工具" in tool_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_invalid_arguments_json_falls_back_to_empty_dict(
        self, monkeypatch
    ):
        """场景 7：arguments 非法 JSON 字符串 → 按 {} 处理 → 工具返回
        参数无效文本，不崩、继续到最终文本。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(
                    _tool_call(
                        "call_1",
                        "query_mentor_knowledge",
                        "{不是合法JSON",
                    )
                ),
                {"content": FINAL_TEXT},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-bad-args",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "success"
        assert result.text == FINAL_TEXT
        tool_messages = _tool_messages_of(calls[1])
        # 空 {} 缺少必填参数 name → 注册表 fail-closed 的确定性错误文本
        assert "工具参数无效" in tool_messages[0]["content"]
        assert "name" in tool_messages[0]["content"]


class TestFailureModes:
    """场景 8-11：HTTP / 网络 / 空回复 / 超长回复的 fail-closed 行为。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [401, 500])
    async def test_http_error_fails_closed(self, monkeypatch, status_code):
        """场景 8：HTTP 401/500 异常 → status=failed、text=None。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch, [_ScriptedResponse(status_code=status_code)]
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-http-error",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "failed"
        assert result.text is None
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_network_error_fails_closed(self, monkeypatch):
        """场景 9：网络异常（httpx.ConnectError）→ status=failed。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch, [httpx.ConnectError("合成连接失败（仅测试）")]
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-network-error",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "failed"
        assert result.text is None
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_blank_reply_fails_closed(self, monkeypatch):
        """场景 10：content 为空白字符串 → status=failed（空回复语义）。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(monkeypatch, [{"content": "   \n\t "}])
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-empty",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "failed"
        assert result.text is None
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_oversized_reply_rejected_by_gate(self, monkeypatch):
        """场景 11：超长回复（>2000 字）→ rejected_by_gate（按实现断言）。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch,
            [{"content": "超" * (orchestrator._MAX_REPLY_CHARS + 1)}],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-oversize",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
            )
        assert result.status == "rejected_by_gate"
        assert result.text is None
        assert len(calls) == 1


class TestAnchorGate:
    """场景 12-14：最终回复逐字锚点校验闸门。"""

    @pytest.mark.asyncio
    async def test_anchor_present_passes(self, monkeypatch):
        """场景 12：最终文本包含全部锚点 → success。"""
        _use_fake_credentials()
        _patch_scripted_glm(
            monkeypatch,
            [{"content": "你可以深度参与导师课题，比如先从文献调研做起。"}],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-anchor-pass",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
                required_anchors=["深度参与导师课题"],
            )
        assert result.status == "success"
        assert "深度参与导师课题" in result.text

    @pytest.mark.asyncio
    async def test_missing_anchor_rejected_by_gate(self, monkeypatch):
        """场景 13：最终文本缺失任一锚点 → 触发一次缺锚点重试，重试回复
        仍缺 → rejected_by_gate、text=None；恰好 2 次请求，重试请求不
        携带 tools。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                {"content": "你可以深度参与导师课题，其余内容略。"},
                {"content": "抱歉，契合度分数这里确实给不了，先聊聊别的？"},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-anchor-miss",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
                required_anchors=["深度参与导师课题", "契合度 87 分"],
            )
        assert result.status == "rejected_by_gate"
        assert result.text is None
        # 恰好 2 次请求：初次回复缺锚点 → 缺锚点重试一次 → 仍缺即拒绝
        assert len(calls) == 2
        # 重试请求不带 tools（纯文本收尾，与达到工具上限后的语义一致）
        assert "tools" not in calls[1]["payload"]
        # 重试请求末尾：回填被拒回复 + 带缺失锚点清单的纠正指令
        retry_messages = calls[1]["payload"]["messages"]
        assert retry_messages[-2]["role"] == "assistant"
        assert retry_messages[-2]["content"] == "你可以深度参与导师课题，其余内容略。"
        assert retry_messages[-1]["role"] == "user"
        assert "契合度 87 分" in retry_messages[-1]["content"]
        assert "必须逐字保留" in retry_messages[-1]["content"]

    @pytest.mark.asyncio
    async def test_anchor_retry_recovers_to_success(self, monkeypatch):
        """场景 13b（v4.3.1 生产缺陷修复）：初次回复只回承接语（缺全部
        锚点，复现生产 glm-4-flash 失败形态）→ 缺锚点重试 → 重试回复
        补齐全部锚点 → success；最终 text 为重试回复、tool_names 保持
        不变、恰好 2 次请求且重试不带 tools。"""
        _use_fake_credentials()
        retry_final = (
            "好嘞，已记下你的兴趣！本次匹配契合度 87 分，建议深度参与导师课题。"
        )
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                # 生产实测的失败形态：36 字承接语，未逐字引用锚点原文
                {"content": "好嘞，已记下你的兴趣！接下来聊聊研究方式～"},
                {"content": retry_final},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-anchor-retry-ok",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
                required_anchors=["契合度 87 分", "深度参与导师课题"],
            )
        assert result.status == "success"
        assert result.text == retry_final
        assert result.tool_names == ()
        assert len(calls) == 2
        assert "tools" not in calls[1]["payload"]
        # 纠正指令携带全部缺失锚点清单（模型据此一次改正）
        retry_last = calls[1]["payload"]["messages"][-1]
        assert retry_last["role"] == "user"
        assert "契合度 87 分" in retry_last["content"]
        assert "深度参与导师课题" in retry_last["content"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "retry_content",
        [
            pytest.param("超" * (orchestrator._MAX_REPLY_CHARS + 1), id="oversized"),
            pytest.param("   \n\t ", id="blank"),
        ],
    )
    async def test_anchor_retry_bad_reply_rejected_no_third_call(
        self, monkeypatch, retry_content
    ):
        """场景 13c：缺锚点重试后的回复超长/为空 → 对重试回复跑完整
        校验后 rejected_by_gate，不发起第三次调用（脚本化客户端超出
        脚本长度即报错，双重保险）。"""
        _use_fake_credentials()
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                {"content": "好嘞，已记下你的兴趣！接下来聊聊研究方式～"},
                {"content": retry_content},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-anchor-retry-bad",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="当前题目：第 1 题",
                required_anchors=["契合度 87 分"],
            )
        assert result.status == "rejected_by_gate"
        assert result.text is None
        assert len(calls) == 2

    @staticmethod
    def _fake_match_services(monkeypatch, *, fit_score: int) -> None:
        """monkeypatch tools_registry 命名空间内的匹配服务函数。

        真实 compute_match 依赖「已确认画像」的 DB 状态（需走完整访谈
        确认流程，见 tools_registry._run_confirmed_match_text）。这里只
        替换数据来源（run_confirmed_match / format_match_outcome 等），
        保留 anchor_sink 收集代码路径真实执行：_FIT_SCORE_ANCHOR_RE 从
        渲染文本提取「契合度 N 分」的精确数值并 append 进 anchor_sink
        （与 chat.py 匹配后 Agent 钩子的防篡改语义等价）。
        """
        monkeypatch.setattr(
            tools_registry, "confirmed_portrait", lambda *a, **k: SimpleNamespace()
        )
        monkeypatch.setattr(
            tools_registry, "persisted_refine_constraints", lambda *a, **k: {}
        )
        monkeypatch.setattr(
            tools_registry,
            "run_confirmed_match",
            lambda *a, **k: SimpleNamespace(items=[{"advisor_id": "A001"}]),
        )
        monkeypatch.setattr(
            tools_registry, "get_gated_summary", lambda *a, **k: None
        )
        monkeypatch.setattr(
            tools_registry, "derive_user_dimension_scores", lambda confirmed: {}
        )
        monkeypatch.setattr(
            tools_registry,
            "format_match_outcome",
            lambda *a, **k: (
                "1) 张三 · 计算机科学与技术系 教授\n"
                f"契合度 {fit_score} 分\n推荐理由（略）"
            ),
        )

    @pytest.mark.asyncio
    async def test_compute_match_anchor_blocks_tampered_score(self, monkeypatch):
        """场景 14（关键红线）：compute_match 工具结果含「契合度 87 分」，
        最终回复改写成「契合度 92 分」→ 触发缺锚点重试，重试仍篡改 →
        rejected_by_gate。

        等价简化说明：本用例 required_anchors 传空列表，锚点「87」只能
        来自 compute_match 执行体写入 anchor_sink 的真实代码路径
        （_FIT_SCORE_ANCHOR_RE 提取 + append），因此被拒绝即证明
        工具注册锚点确实参与了最终校验（防 LLM 篡改分数），且缺锚点
        重试同样不放行篡改结果。
        """
        _use_fake_credentials()
        self._fake_match_services(monkeypatch, fit_score=87)
        calls = _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(
                    _tool_call(
                        "call_match", "compute_match", '{"confirm_profile": true}'
                    )
                ),
                {"content": "根据匹配结果，你和张三老师的契合度 92 分，非常合适。"},
                {"content": "我再确认一次：你和张三老师的契合度是 92 分。"},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-anchor-tamper",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="画像已确认，可执行匹配",
                required_anchors=[],
            )
        # 前提：工具结果文本真实包含「契合度 87 分」（防篡改的比对基准）
        tool_messages = _tool_messages_of(calls[1])
        assert len(tool_messages) == 1
        assert "契合度 87 分" in tool_messages[0]["content"]
        # 最终回复缺失锚点「87」→ 缺锚点重试一次后仍篡改 → 逐字校验拒绝
        # （fail-closed，不降级放行）
        assert result.status == "rejected_by_gate"
        assert result.text is None
        assert result.tool_names == ("compute_match",)
        # 共 3 次请求：工具调用 → 篡改回复 → 缺锚点重试；重试不带 tools
        assert len(calls) == 3
        assert "tools" not in calls[2]["payload"]

    @pytest.mark.asyncio
    async def test_compute_match_anchor_passes_with_verbatim_score(
        self, monkeypatch
    ):
        """场景 14 对照组：最终回复逐字保留「契合度 87 分」→ success。"""
        _use_fake_credentials()
        self._fake_match_services(monkeypatch, fit_score=87)
        _patch_scripted_glm(
            monkeypatch,
            [
                _tool_call_message(
                    _tool_call(
                        "call_match", "compute_match", '{"confirm_profile": true}'
                    )
                ),
                {"content": "根据匹配结果，你和张三老师的契合度 87 分，非常合适。"},
            ],
        )
        with SessionLocal() as db:
            result = await run_agent_turn(
                db,
                session_id="agent-test-anchor-verbatim",
                student_id="student-agent-test",
                messages=_user_messages(),
                state_context="画像已确认，可执行匹配",
                required_anchors=[],
            )
        assert result.status == "success"
        assert "契合度 87 分" in result.text
        assert result.tool_names == ("compute_match",)


class TestPromptFallback:
    """场景 15：Agent 系统提示词加载降级（兜底常量生效不崩）。"""

    def test_fallback_constant_and_degradation(self, monkeypatch):
        """兜底常量存在且非空；加载失效路径回退常量；注入后构建不崩。"""
        fallback = orchestrator._AGENT_SYSTEM_PROMPT_FALLBACK_V1
        # 兜底常量存在且非空
        assert fallback.strip()
        # 模块加载期常量已就绪（真实文件或兜底，二者必居其一且非空）
        assert orchestrator.AGENT_SYSTEM_PROMPT.strip()
        # 正常路径：版本清单一致时加载真实模板（非空）
        loaded = load_prompt_template("agent_system_prompt", fallback=fallback)
        assert loaded.strip()
        # 降级路径：版本清单不一致（模拟文件缺失/损坏）→ 返回兜底常量
        monkeypatch.setattr(prompts_module, "_CURRENT_VERSIONS", {})
        degraded = load_prompt_template("agent_system_prompt", fallback=fallback)
        assert degraded == fallback
        # 兜底常量作为系统提示词时消息构建照常工作（不崩、状态注入保留）
        monkeypatch.setattr(orchestrator, "AGENT_SYSTEM_PROMPT", fallback)
        payload = orchestrator._build_agent_messages(
            _user_messages(), "当前题目：第 1 题"
        )
        assert payload[0]["role"] == "system"
        assert payload[0]["content"].startswith(fallback)
        assert "当前题目：第 1 题" in payload[0]["content"]

    def test_build_agent_messages_injects_system_and_truncates_history(self):
        """消息序列构建：系统提示词 + 状态注入置顶；历史只保留最近
        user/assistant（截断到 _HISTORY_LIMIT），system 历史不进入。"""
        long_history = [
            LLMMessage(
                role="user" if i % 2 == 0 else "assistant", content=f"消息{i}"
            )
            for i in range(16)
        ]
        messages = [LLMMessage(role="system", content="旧系统消息"), *long_history]
        payload = orchestrator._build_agent_messages(messages, "当前题目：第 1 题")
        assert payload[0]["role"] == "system"
        assert orchestrator.AGENT_SYSTEM_PROMPT in payload[0]["content"]
        assert "当前题目：第 1 题" in payload[0]["content"]
        # v4.3.1：状态注入头部为最高优先级声明（压过前文「不超过 300 字」
        # 等通用工作流指令），逐字保留要求显式下达
        assert "最高优先级指令" in payload[0]["content"]
        assert "效力高于本提示词前文的一切工作流描述与示例" in payload[0]["content"]
        assert "必须原样出现在你的最终回复里" in payload[0]["content"]
        history = payload[1:]
        assert len(history) == orchestrator._HISTORY_LIMIT
        assert all(m["role"] in ("user", "assistant") for m in history)
        # 保留的是最近的消息
        assert history[-1]["content"] == "消息15"


class TestPureHelpers:
    """编排器纯函数与常量（被测核心的直接单元覆盖）。"""

    def test_extract_tool_calls_filters_malformed(self):
        """tool_calls 缺失 / 类型异常 / 非法条目 → 返回空列表。"""
        extract = orchestrator._extract_tool_calls
        assert extract({}) == []
        assert extract({"tool_calls": None}) == []
        assert extract({"tool_calls": "不是列表"}) == []
        assert extract({"tool_calls": ["非法", 1, None]}) == []
        valid = [{"id": "call_1"}, {"id": "call_2"}]
        assert extract({"tool_calls": valid}) == valid

    def test_validate_final_reply_gate_branches(self):
        """校验闸门分支：非字符串 / 空白 / 超长 / 锚点缺失 / 空白锚点。

        v4.3.1 起返回 (是否通过, 缺失锚点数, 缺失锚点列表)，缺失列表
        供缺锚点重试构造纠正指令；非字符串/空白/超长的缺失列表为空。
        """
        validate = orchestrator._validate_final_reply
        assert validate(None, []) == (False, 0, [])
        assert validate("   ", []) == (False, 0, [])
        assert validate("长" * (orchestrator._MAX_REPLY_CHARS + 1), []) == (
            False,
            0,
            [],
        )
        # 锚点全命中 → 通过
        assert validate(
            "契合度 87 分，可深度参与导师课题", ["87", "深度参与导师课题"]
        ) == (True, 0, [])
        # 缺失 1 个锚点 → 拒绝并报告缺失数与缺失锚点原文清单
        assert validate("契合度 87 分", ["87", "深度参与导师课题"]) == (
            False,
            1,
            ["深度参与导师课题"],
        )
        # 空白锚点跳过（不误伤）
        assert validate("任意非空文本", ["", "   "]) == (True, 0, [])

    def test_gate_constants_pinned(self):
        """服务端确定性闸门常量（红线：不得意外放宽）。"""
        assert orchestrator._MAX_TOOL_CALLS_PER_TURN == 3
        assert orchestrator._MAX_REPLY_CHARS == 2000
        assert orchestrator._HISTORY_LIMIT == 12


# ============================================================================
# B. chat 接线（FastAPI TestClient 走 /v1/chat/completions）
# ============================================================================


class TestChatWiring:
    """场景 16-19：chat.py 两个 Agent 接线点的激活条件与降级行为。"""

    def test_probe_request_never_enters_agent(self, monkeypatch):
        """场景 16：probe 请求（max_tokens:1 形态）→ 不进 Agent、零 LLM HTTP。"""
        _use_fake_credentials()  # 凭据在位：probe 是唯一拦截因素
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)

        async def boom_agent(*_args, **_kwargs):
            raise AssertionError("连接探测请求不应进入 Agent 编排")

        monkeypatch.setattr(qxd_chat, "run_agent_turn", boom_agent)

        async def boom_render(_pack):
            raise AssertionError("连接探测请求不应触发表达层")

        monkeypatch.setattr(qxd_chat, "render_interview_reply", boom_render)
        http_calls = _patch_scripted_glm(monkeypatch, [])

        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "你好"}],
                "stream": True,
                "max_tokens": 1,
            },
        )
        assert response.status_code == 200
        assert http_calls == []

    def test_agent_failure_degrades_to_deterministic_reply(self, monkeypatch):
        """场景 17：Agent 失败降级 → 回复为状态机确定性文本，
        与开关关闭（旧路径）时完全一致。"""
        _use_fake_credentials()
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)

        agent_calls: list[dict] = []

        async def failed_agent_turn(*_args, **kwargs):
            agent_calls.append(kwargs)
            return AgentTurnResult(None, "failed", ())

        monkeypatch.setattr(qxd_chat, "run_agent_turn", failed_agent_turn)

        async def disabled_render(_pack):
            # 表达层兜底为不可用（与无凭据时的真实行为一致）
            return SimpleNamespace(text=None, provider=None, status="disabled")

        monkeypatch.setattr(qxd_chat, "render_interview_reply", disabled_render)
        http_calls = _patch_scripted_glm(monkeypatch, [])

        body = {"messages": [{"role": "user", "content": "我对强化学习感兴趣"}]}
        degraded = client.post("/v1/chat/completions", headers=AUTH, json=body)
        assert degraded.status_code == 200
        degraded_content = degraded.json()["choices"][0]["message"]["content"]

        # 对照：关闭开关（旧路径）+ 表达层不可用 → 同输入的确定性回复
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", False)
        baseline = client.post("/v1/chat/completions", headers=AUTH, json=body)
        assert baseline.status_code == 200
        baseline_content = baseline.json()["choices"][0]["message"]["content"]

        assert len(agent_calls) == 1  # 确实先进了 Agent（是降级而非未激活）
        assert degraded_content  # 确定性文本非空
        assert degraded_content == baseline_content  # 与开关关闭时一致
        assert http_calls == []  # 全程零 LLM HTTP

    def test_agent_switch_off_uses_expression_path(self, monkeypatch):
        """场景 18：AGENT_ORCHESTRATION_ENABLED=False → 不进 Agent，
        走 render_interview_reply 旧路径。"""
        _use_fake_credentials()  # 凭据在位：开关是唯一拦截因素
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", False)

        async def boom_agent(*_args, **_kwargs):
            raise AssertionError("开关关闭时不应进入 Agent 编排")

        monkeypatch.setattr(qxd_chat, "run_agent_turn", boom_agent)

        render_calls: list = []

        async def fake_render(pack):
            render_calls.append(pack)
            return SimpleNamespace(
                text="表达层旧路径改写文本", provider="glm", status="available"
            )

        monkeypatch.setattr(qxd_chat, "render_interview_reply", fake_render)
        http_calls = _patch_scripted_glm(monkeypatch, [])

        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "我对强化学习感兴趣"}]},
        )
        assert response.status_code == 200
        content = response.json()["choices"][0]["message"]["content"]
        assert content == "表达层旧路径改写文本"
        assert render_calls  # 旧表达层路径确实被调用
        assert http_calls == []

    def test_missing_credentials_skip_agent(self, monkeypatch):
        """场景 19：无凭据 → 不进 Agent（回归等价），走旧表达层路径
        并降级为状态机确定性文本。"""
        _use_fake_credentials(())
        monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_ENABLED", True)

        async def boom_agent(*_args, **_kwargs):
            raise AssertionError("无凭据时不应进入 Agent 编排")

        monkeypatch.setattr(qxd_chat, "run_agent_turn", boom_agent)

        render_calls: list = []

        async def disabled_render(pack):
            render_calls.append(pack)
            return SimpleNamespace(text=None, provider=None, status="disabled")

        monkeypatch.setattr(qxd_chat, "render_interview_reply", disabled_render)
        http_calls = _patch_scripted_glm(monkeypatch, [])

        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "我对强化学习感兴趣"}]},
        )
        assert response.status_code == 200
        content = response.json()["choices"][0]["message"]["content"]
        assert content  # 状态机确定性访谈文本非空
        assert render_calls  # 走了旧表达层路径（真实行为=disabled 降级）
        assert http_calls == []
