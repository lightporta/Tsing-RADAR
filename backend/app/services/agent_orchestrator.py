"""v4.3.0 全 Agent 化 GLM 编排服务。

全 Agent 化——GLM 负责对话编排与工具调用（08 文档）：事实、分数、
检索结果全部由确定性工具（tools_registry）产出，模型只组织语言；
服务端只做校验闸门（参数 fail-closed、确认门、循环上限、逐字锚点
校验）。任何失败（无凭据 / HTTP 与解析异常 / 预算耗尽 / 空回复 /
锚点缺失）都返回 text=None 的 AgentTurnResult，由调用方降级确定性
管线；本模块不抛异常、不编造事实，日志绝不记录 API key 与用户消息
全文。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.advisor import LLMMessage
from app.services.prompts import load_prompt_template
from app.services.tools_registry import (
    TOOL_SCHEMAS,
    build_tool_runtime,
    dispatch_tool_call,
)

logger = logging.getLogger(__name__)

# v4.3.0 全 Agent 化：Agent 系统提示词版本化。内嵌 v1 文本为兜底常量，
# 运行期从 app/services/prompts/agent_system_prompt_v1.txt 加载（版本
# 清单不一致/文件缺失 → 回退本常量），模式与 llm.py 的 LLM_SYSTEM_PROMPT
# 完全一致。
_AGENT_SYSTEM_PROMPT_FALLBACK_V1 = (
    "你是清研寻师雷达，为清华大学学生提供选导师访谈与咨询服务。"
    "请严格按服务端在系统消息中下发的当前题目与选项推进访谈，"
    "不跳题、不改写题干与选项。"
    "所有导师事实、分数与检索结果必须来自工具返回值，"
    "禁止编造任何分数或事实。"
    "最终回复必须完整、逐字包含服务端要求的选项与数字原文。"
)
AGENT_SYSTEM_PROMPT = load_prompt_template(
    "agent_system_prompt", fallback=_AGENT_SYSTEM_PROMPT_FALLBACK_V1
)

# —— 编排参数（确定性上限，全部属于服务端校验闸门）——
# 单轮最多执行的工具调用次数；达到后不再向 GLM 下发 tools（强制纯文本收尾）
_MAX_TOOL_CALLS_PER_TURN = 3
# 最终回复长度上限（超长 → rejected_by_gate）
_MAX_REPLY_CHARS = 2000
# 单轮编排总预算（秒）：覆盖该轮全部 GLM 调用与工具执行
_TURN_TOTAL_BUDGET_SECONDS = 75.0
# GLM 采样参数（低温保证事实转述稳定，不鼓励发散）
_TEMPERATURE = 0.3
_MAX_TOKENS = 800
# 送入 GLM 的历史消息条数上限（仅 user/assistant 角色）
_HISTORY_LIMIT = 12
# v4.3.1 缺锚点重试的最小剩余预算（秒）：剩余预算不高于该值时不再重试，
# 直接维持 rejected_by_gate 现状（防止重试调用拖垮请求总延迟）
_ANCHOR_RETRY_MIN_BUDGET_SECONDS = 2.0


@dataclass(frozen=True)
class AgentTurnResult:
    """单轮编排结果：text 仅在 status=success 时非空。"""

    text: str | None
    status: str  # success / disabled / failed / rejected_by_gate
    tool_names: tuple[str, ...]


def _build_agent_messages(
    messages: list[LLMMessage], state_context: str
) -> list[dict[str, str]]:
    """构建送入 GLM 的消息序列。

    system = Agent 系统提示词 + 服务端确定性状态注入（当前题目/选项/
    画像进度等，其中要求逐字保留的内容不可改写）；历史只保留最近的
    user/assistant 消息（截断到 _HISTORY_LIMIT 条），system 消息不进入
    历史以免与注入状态重复。
    """
    history = [
        {"role": m.role, "content": m.content}
        for m in messages
        if m.role in ("user", "assistant")
    ][-_HISTORY_LIMIT:]
    # v4.3.1 修复（生产实测）：原标题「必须遵守」会被前文系统提示词里
    # 「每次回复不超过 300 字、不啰嗦」的通用指令压过（glm-4-flash 只回
    # 承接语、不逐字引用选项原文 → 永久降级确定性文本），此处升级为
    # 最高优先级声明：显式声明效力高于前文一切工作流描述与示例，并说明
    # 编号选项不计入字数限制、不得用模型自拟问题或工具调用替代当前题目。
    # v4.3.x 自然度许可：锚点原文逐字保留的红线不变，同时显式允许/鼓励
    # 模型在原文前后加自然口语化承接，消除「一问一答复读机」观感。
    system_content = (
        AGENT_SYSTEM_PROMPT
        + "\n\n【服务端确定性状态——最高优先级指令，效力高于本提示词前文的一切工作流描述与示例】\n"
        + "当前轮次必须以下方状态为准：若下方已下发当前题目与选项，"
        "必须把题干与全部选项原文完整呈现在回复中（编号选项不计入字数限制），"
        "不得用你自己的问题或工具调用替代当前题目；"
        + '其中标注"必须逐字保留"的内容必须原样出现在你的最终回复里。\n'
        + "语气要求：像一位真诚的学长/学姐在聊天——回复先用一两句自然、"
        "口语化的承接（可带一点温度或轻幽默，不空洞夸赞、不客服腔），"
        "再完整呈现题干与全部选项原文；选项原文必须逐字保留"
        "（可加编号排版），除选项外全回复仍不超过 300 字。\n"
        + state_context
    )
    return [{"role": "system", "content": system_content}, *history]


def _extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """从 GLM 响应 message 中提取 tool_calls 列表；缺失/类型异常返回空。"""
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    return [call for call in tool_calls if isinstance(call, dict)]


def _validate_final_reply(
    text: str | None, anchors: list[str]
) -> tuple[bool, int, list[str]]:
    """最终回复校验闸门。

    返回 (是否通过, 缺失锚点数, 缺失锚点列表)：text 非空、长度不超过
    _MAX_REPLY_CHARS、anchors 中每个非空字符串都在 text 中逐字出现
    （空白锚点跳过）。非字符串 / 空白 / 超长时缺失列表为空（缺失数为
    0，调用方据此区分「纯超长/空文本」与「缺锚点」两类失败——前者
    不触发缺锚点重试）。
    """
    if not isinstance(text, str) or not text.strip():
        return False, 0, []
    if len(text) > _MAX_REPLY_CHARS:
        return False, 0, []
    missing_anchors = [
        anchor
        for anchor in anchors
        if isinstance(anchor, str) and anchor.strip() and anchor not in text
    ]
    return len(missing_anchors) == 0, len(missing_anchors), missing_anchors


async def _post_glm_chat(
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """发起一次 GLM chat/completions 请求，返回 choices[0].message。

    HTTP 错误 / 超时 / JSON 解析 / KeyError 原样抛出，由调用方统一
    fail-closed（日志不含 key、不含消息内容）；编排主循环与缺锚点
    重试共用本函数。
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.post(
            f"{settings.GLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


async def run_agent_turn(
    db,
    *,
    session_id: str,
    student_id: str | None,
    messages: list[LLMMessage],
    state_context: str,
    required_anchors: list[str] | None = None,
    portrait=None,
) -> AgentTurnResult:
    """执行一轮全 Agent 化编排：GLM 对话 + 确定性工具调用循环。

    事实/分数/检索全部由 tools_registry 的确定性工具产出，模型只组织
    语言；服务端逐层闸门（凭据 / 预算 / 工具循环上限 / 逐字锚点），
    任何失败返回 text=None 的结果，由调用方降级确定性管线。
    """
    # —— 闸门 1：凭据（无凭据不发起任何 HTTP，直接 disabled）——
    if not settings.llm_credentials:
        return AgentTurnResult(None, "disabled", ())
    provider, api_key = settings.llm_credentials[0]
    if provider != "glm":
        # 与 llm.py 同款 fail-closed：仅支持 GLM，其余 provider 一律禁用
        logger.error("agent_turn status=rejected_unsupported_provider")
        return AgentTurnResult(None, "disabled", ())

    # —— 消息序列：Agent 系统提示词 + 确定性状态注入 + 截断历史 ——
    payload_messages = _build_agent_messages(messages, state_context)

    # —— 确定性工具执行体 + 锚点收集槽 ——
    # anchor_sink 为调用方锚点的副本；工具执行期（如 compute_match）会把
    # 必须逐字保留的分数/事实追加进同一列表（调用方锚点 + 工具注册锚点
    # 合并），最终统一做逐字校验。
    anchor_sink: list[str] = list(required_anchors or [])
    runtime = build_tool_runtime(
        db=db,
        student_id=student_id,
        session_id=session_id,
        portrait=portrait,
        anchor_sink=anchor_sink,
    )

    model = settings.GLM_CHAT_MODEL
    used_tool_names: list[str] = []
    tool_calls_used = 0
    # v4.3.1 缺锚点重试标记：单轮最多重试 1 次（重试后仍失败即拒绝）
    anchor_retried = False
    started = time.monotonic()

    while True:
        # —— 闸门 2：单轮总预算（剩余 ≤1s 直接失败，防慢循环拖垮请求）——
        remaining_budget = _TURN_TOTAL_BUDGET_SECONDS - (
            time.monotonic() - started
        )
        if remaining_budget <= 1.0:
            logger.warning(
                "agent_turn provider=glm model=%s status=failed "
                "error_type=budget_exhausted tool_calls=%d latency_ms=%d",
                model,
                tool_calls_used,
                round((time.monotonic() - started) * 1000),
            )
            return AgentTurnResult(None, "failed", tuple(used_tool_names))
        # 单次超时：不超过全局 LLM 超时，也不超过剩余预算，下限 1 秒
        timeout_seconds = max(
            1.0, min(float(settings.LLM_TIMEOUT), remaining_budget)
        )

        payload: dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "temperature": _TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
            "stream": False,
        }
        # —— 闸门 3：工具调用循环上限——达到后不再下发 tools，
        # 强制模型纯文本收尾 ——
        if tool_calls_used < _MAX_TOOL_CALLS_PER_TURN:
            payload["tools"] = TOOL_SCHEMAS
            payload["tool_choice"] = "auto"

        try:
            message = await _post_glm_chat(
                api_key, payload, timeout_seconds=timeout_seconds
            )
        except Exception as exc:
            # HTTP 错误 / 超时 / JSON 解析 / KeyError 统一 fail-closed
            #（日志模式照抄 llm.py：不含 key、不含消息内容）
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "agent_turn provider=glm model=%s status=failed "
                "error_type=%s http_status=%s latency_ms=%d",
                model,
                type(exc).__name__,
                status_code if status_code is not None else "none",
                round((time.monotonic() - started) * 1000),
            )
            return AgentTurnResult(None, "failed", tuple(used_tool_names))

        tool_calls = _extract_tool_calls(message)
        if tool_calls:
            # 含 tool_calls 的 assistant 消息原样回填（tool_calls 保持原始
            # 结构、arguments 保留原始 JSON 字符串），保证消息序列完整、
            # 可继续多轮工具循环
            raw_content = message.get("content")
            payload_messages.append(
                {
                    "role": "assistant",
                    "content": raw_content if isinstance(raw_content, str) else "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                call_id = str(call.get("id") or "")
                function_spec = call.get("function")
                if isinstance(function_spec, dict):
                    name = str(function_spec.get("name") or "")
                    raw_arguments = function_spec.get("arguments")
                else:
                    name = ""
                    raw_arguments = None
                if tool_calls_used >= _MAX_TOOL_CALLS_PER_TURN:
                    # 总量封顶：单次响应里超出的 tool_call 不执行，直接把
                    # 确定性提示作为该 tool_call_id 的 tool 结果回填，
                    # 保持消息序列完整（每个 tool_call_id 都有对应结果）
                    payload_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": "工具调用次数已达上限",
                        }
                    )
                    continue
                # arguments 解析失败按空对象处理，交给注册表做参数校验
                #（注册表 fail-closed：非法参数返回确定性错误文本）
                try:
                    arguments = json.loads(raw_arguments or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                result_text = dispatch_tool_call(
                    runtime, name=name, arguments=arguments
                )
                tool_calls_used += 1
                used_tool_names.append(name)
                payload_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_text,
                    }
                )
            # 本批工具执行完毕，回到循环头（重算预算；达到上限后下一次
            # 请求不再携带 tools）
            continue

        # —— 无 tool_calls：content 即最终回复 ——
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            logger.warning(
                "agent_turn provider=glm model=%s status=failed "
                "error_type=empty_reply tool_calls=%d latency_ms=%d",
                model,
                tool_calls_used,
                round((time.monotonic() - started) * 1000),
            )
            return AgentTurnResult(None, "failed", tuple(used_tool_names))

        # —— 闸门 4：最终回复校验（非空 / 长度 / 逐字锚点全命中）——
        passed, missing_count, missing_anchors = _validate_final_reply(
            content, anchor_sink
        )
        if not passed:
            # —— v4.3.1 缺锚点重试：生产实测 glm-4-flash 会只回承接语、
            # 不逐字引用选项原文（被前文「不超过 300 字」指令压过），
            # 原实现一次失败即永久降级确定性文本；这里给模型一次带着
            # 缺失清单的改正机会。仅锚点缺失触发（纯超长/空文本不重试）、
            # 最多 1 次，且剩余预算须大于 _ANCHOR_RETRY_MIN_BUDGET_SECONDS ——
            if (
                missing_count > 0
                and not anchor_retried
                and _TURN_TOTAL_BUDGET_SECONDS - (time.monotonic() - started)
                > _ANCHOR_RETRY_MIN_BUDGET_SECONDS
            ):
                anchor_retried = True
                logger.info(
                    "agent_turn status=anchor_retry provider=glm model=%s "
                    "missing_count=%d tool_calls=%d latency_ms=%d",
                    model,
                    missing_count,
                    tool_calls_used,
                    round((time.monotonic() - started) * 1000),
                )
                # 回填被拒回复（模型需要看到自己上一条回复才能保留承接
                # 语气），再追加带缺失锚点清单的纠正指令；重试请求不带
                # tools（与达到工具上限后的纯文本收尾语义一致）。
                # 自然度：被拒回复用户不可见，重试回复不要向用户道歉或
                # 提及"刚才的回复"，像首次回答一样自然给出完整版。
                payload_messages.append({"role": "assistant", "content": content})
                payload_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你的上一条回复缺少以下必须逐字保留的内容：\n"
                            + "\n".join(missing_anchors)
                            + "\n请重新给出完整回复：保留你刚才承接语的语气，"
                            "但必须逐字原样包含上述全部内容"
                            "（编号选项不计入字数限制）；"
                            "注意被拒回复用户并不可见，不要道歉或提及"
                            "刚才的回复，像首次回答一样自然。"
                        ),
                    }
                )
                retry_payload: dict[str, Any] = {
                    "model": model,
                    "messages": payload_messages,
                    "temperature": _TEMPERATURE,
                    "max_tokens": _MAX_TOKENS,
                    "stream": False,
                }
                retry_timeout = max(
                    1.0,
                    min(
                        float(settings.LLM_TIMEOUT),
                        _TURN_TOTAL_BUDGET_SECONDS
                        - (time.monotonic() - started),
                    ),
                )
                try:
                    retry_message = await _post_glm_chat(
                        api_key, retry_payload, timeout_seconds=retry_timeout
                    )
                except Exception as exc:
                    # 重试请求的 HTTP/解析异常与主循环同款 fail-closed
                    status_code = getattr(
                        getattr(exc, "response", None), "status_code", None
                    )
                    logger.warning(
                        "agent_turn provider=glm model=%s status=failed retry=1 "
                        "error_type=%s http_status=%s latency_ms=%d",
                        model,
                        type(exc).__name__,
                        status_code if status_code is not None else "none",
                        round((time.monotonic() - started) * 1000),
                    )
                    return AgentTurnResult(None, "failed", tuple(used_tool_names))
                # 对重试回复重新跑完整校验（含非空 / 长度 / 全部锚点）
                retry_content = retry_message.get("content")
                (
                    retry_passed,
                    retry_missing_count,
                    _retry_missing_anchors,
                ) = _validate_final_reply(retry_content, anchor_sink)
                if retry_passed:
                    logger.info(
                        "agent_turn status=success provider=glm model=%s retry=1 "
                        "tool_calls=%d tools=%s latency_ms=%d",
                        model,
                        tool_calls_used,
                        ",".join(used_tool_names) if used_tool_names else "none",
                        round((time.monotonic() - started) * 1000),
                    )
                    return AgentTurnResult(
                        retry_content.strip(), "success", tuple(used_tool_names)
                    )
                # 重试仍失败（仍缺锚点 / 超长 / 空文本）→ 拒绝，不再重试
                logger.warning(
                    "agent_turn status=rejected_by_gate provider=glm model=%s "
                    "retry=1 missing_anchor_count=%d reply_chars=%d "
                    "tool_calls=%d latency_ms=%d",
                    model,
                    retry_missing_count,
                    len(retry_content) if isinstance(retry_content, str) else 0,
                    tool_calls_used,
                    round((time.monotonic() - started) * 1000),
                )
                return AgentTurnResult(
                    None, "rejected_by_gate", tuple(used_tool_names)
                )
            # 预算不足 / 已重试过 / 非锚点失败（纯超长）→ 直接拒绝（现状不变）
            logger.warning(
                "agent_turn status=rejected_by_gate provider=glm model=%s "
                "missing_anchor_count=%d reply_chars=%d tool_calls=%d "
                "latency_ms=%d",
                model,
                missing_count,
                len(content),
                tool_calls_used,
                round((time.monotonic() - started) * 1000),
            )
            return AgentTurnResult(None, "rejected_by_gate", tuple(used_tool_names))

        # —— 成功：日志只含状态/模型/工具名与计数/延迟，无 key 无原文 ——
        logger.info(
            "agent_turn status=success provider=glm model=%s tool_calls=%d "
            "tools=%s latency_ms=%d",
            model,
            tool_calls_used,
            ",".join(used_tool_names) if used_tool_names else "none",
            round((time.monotonic() - started) * 1000),
        )
        return AgentTurnResult(content.strip(), "success", tuple(used_tool_names))
