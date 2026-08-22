"""v4.3.0 阶段五：LLM 自主工具调用编排（仅工具域，fail-closed）。

任务书 §五「阶段B 转正」的边界实现：
- LLM 可自主调用**注册表白名单标记**的工具（LLM_TOOL_SCHEMAS），
  自主调用决定"何时调"；
- 调用结果由 tools_registry 确定性渲染（不经 LLM 改写事实）——
  "结果如何呈现"的确定性不变；
- 敏感工具（send_contact_request）的执行体只登记待确认动作并返回
  确认指令；精确确认词由 `resolve_pending_contact` 二次确认门校验，
  确认后才走既有套磁链路（反骚扰红线）；
- 无 GLM key / 开关关闭 / 超时 / LLM 失败 / 无 tool_calls →
  返回 None，调用方降级为确定性路由（行为与基线一致）。

红线（与 v4.0.0 一致，仅工具域定向放开）：
画像确认 / 匹配触发 / 记忆写入 / 招募发布永不注册为 LLM 可调工具
（tools_registry 白名单制 + tests 架构护栏）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.dialogue_state_store import (
    get_session_value,
    set_session_value,
)
from app.services.llm import LLMMessage, _llm_complete_result
from app.services.tools_registry import (
    PENDING_CONTACT_KEY,
    LLM_TOOL_SCHEMAS,
    build_tool_runtime,
    dispatch_tool_call,
    is_sensitive_tool,
)

logger = logging.getLogger(__name__)

_AUTONOMOUS_SYSTEM_PROMPT = (
    "你是清华导师匹配助手的工具调度层。根据用户最新消息判断是否调用工具。\n"
    "规则：\n"
    "1. 只在用户明确表达工具能覆盖的意图时调用工具；闲聊、致谢、感叹、"
    "对匹配结果本身的追问都不需要调用任何工具；\n"
    "2. 拿不准就不调用，直接返回空文本；\n"
    "3. 不得编造工具名；参数必须符合 Schema；advisor_id 只能使用下方"
    "「当前匹配候选」里给出的值，一个字都不能改；\n"
    "4. 用户表达联系导师的意向时可以调用 send_contact_request（系统会"
    "向用户二次确认，你不需要自行确认）。\n"
)

# 会话内最多执行的自主工具调用条数（防 LLM 滥用返回长列表）
_MAX_AUTONOMOUS_CALLS = 3


def autonomous_tools_ready() -> bool:
    """自主调用链路是否就绪（开关 + LLM 凭据）。"""
    return bool(
        settings.QXD_AUTONOMOUS_TOOLS_ENABLED and settings.llm_credentials
    )


def _render_candidates(match_items: list[dict[str, Any]]) -> str:
    if not match_items:
        return "（当前没有匹配候选）"
    lines = []
    for item in match_items[:10]:
        advisor_id = str(item.get("advisor_id") or "")
        name = str(item.get("name") or "")
        lines.append(f"- {name}：advisor_id={advisor_id}")
    return "\n".join(lines)


async def try_autonomous_tool_call(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
    portrait: Any = None,
    match_items: list[dict[str, Any]] | None = None,
) -> str | None:
    """匹配态兜底位的 LLM 自主工具调用；任何降级路径返回 None。

    返回非 None 时为已确定性渲染的工具结果文本（含敏感工具的确认
    指令文本）；调用方应直接作为回复内容。
    """
    if not autonomous_tools_ready():
        return None
    query = (latest_user or "").strip()
    if not query:
        return None
    runtime = build_tool_runtime(
        db=db,
        student_id=student_id,
        portrait=portrait,
        session_id=session_id,
        match_items=match_items,
    )
    result = await _llm_complete_result(
        [
            LLMMessage(
                role="system", content=_AUTONOMOUS_SYSTEM_PROMPT
            ),
            LLMMessage(
                role="user",
                content=(
                    f"当前匹配候选：\n{_render_candidates(match_items or [])}\n\n"
                    f"用户最新消息：{query[:800]}\n\n"
                    "请判断是否需要调用工具。不需要则只输出空文本。"
                ),
            ),
        ],
        tools=LLM_TOOL_SCHEMAS,
        timeout_seconds=settings.LLM_INTERVIEW_ENHANCEMENT_TIMEOUT_SECONDS,
    )
    if result is None or not result.tool_calls:
        return None
    replies: list[str] = []
    for call in result.tool_calls[:_MAX_AUTONOMOUS_CALLS]:
        # 幻觉工具名 / 参数注入 / 越界 → dispatch fail-closed 返回
        # 确定性错误文本（不抛异常、不编造）
        replies.append(
            dispatch_tool_call(
                runtime, name=call.name, arguments=call.arguments
            )
        )
    logger.info(
        "autonomous_tool_call session=%s calls=%d names=%s",
        session_id,
        len(result.tool_calls),
        [c.name for c in result.tool_calls[:_MAX_AUTONOMOUS_CALLS]],
    )
    return "\n\n".join(part for part in replies if part)


def load_pending_contact(
    db: Session, *, session_id: str, student_id: str
) -> dict[str, str] | None:
    """读取待确认联系意向；无/损坏 → None。"""
    raw = get_session_value(
        db,
        session_id=session_id,
        student_id=student_id,
        key=PENDING_CONTACT_KEY,
    )
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not payload.get("advisor_id"):
        return None
    return {
        "advisor_id": str(payload.get("advisor_id") or ""),
        "advisor_name": str(payload.get("advisor_name") or ""),
        "message": str(payload.get("message") or ""),
    }


def clear_pending_contact(
    db: Session, *, session_id: str, student_id: str
) -> None:
    """清除待确认联系意向（确认执行后 / 取消 / 防骚扰失效）。"""
    set_session_value(
        db,
        session_id=session_id,
        student_id=student_id,
        key=PENDING_CONTACT_KEY,
        value="",
    )


def is_contact_confirmation(message: str, advisor_name: str) -> bool:
    """精确确认词判定（逐字，防歧义确认）。"""
    return (message or "").strip() == f"确认联系{advisor_name}"


_CONTACT_CANCEL_WORDS = ("取消", "算了", "不用了", "不联系了")


def is_contact_cancellation(message: str) -> bool:
    return (message or "").strip() in _CONTACT_CANCEL_WORDS
