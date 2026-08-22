"""v4.0.0 任务1 阶段B：确定性工具注册表（OpenAI function-calling 对齐）。

注册 3 个只读工具：query_mentor_knowledge / get_recruitments / recall_memory。

本期为**服务端确定性路由**：由对话状态机（chat.py 意图分发）决定调用哪个
工具、传入什么参数，LLM 不自主调用。注册表提供两样东西：
- TOOL_SCHEMAS：与 OpenAI function-calling 对齐的 JSON Schema 声明，作为
  协议契约（供文档/未来 LLM 自主调用复用），并由 `dispatch_tool_call` 做
  参数校验；
- build_tool_runtime / dispatch_tool_call：参数校验（fail-closed）后调用
  既有服务函数确定性执行，输出纯文本，不经 LLM。

红线：
- 只读：知识库 / 公开招募 / 本人白名单记忆，不写库、不触碰访谈状态机；
- fail-closed：未知工具、参数非法、执行异常 → 返回确定性错误文本，
  不抛异常、不吞消息、不降级为编造；
- 与对话管线同源：执行体即 chat 各 handler 复用的既有函数，行为一致。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services import mentor_knowledge, recruitment_public
from app.services.memory_service import format_memory_summary

logger = logging.getLogger(__name__)

TOOL_QUERY_MENTOR_KNOWLEDGE = "query_mentor_knowledge"
TOOL_GET_RECRUITMENTS = "get_recruitments"
TOOL_RECALL_MEMORY = "recall_memory"

_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    TOOL_QUERY_MENTOR_KNOWLEDGE: {
        "description": (
            "查询导师公开评价综述级知识库（匿名主观评价聚合，无原始引文，"
            "仅作参考）。未收录时诚实拒答，绝不编造联系方式/名额/项目细节。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "导师姓名，如「李琦」"}
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    TOOL_GET_RECRUITMENTS: {
        "description": (
            "查询当前通过审核且在招的公开招募（静态目录 + 数据库投稿双源"
            "实时；已过审、已发布、未下架、未过期）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "urgent_only": {
                    "type": "boolean",
                    "description": "仅急招（默认 false）",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "最多展示条数（默认 3）",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    TOOL_RECALL_MEMORY: {
        "description": (
            "召回该用户已确认画像的长期记忆（user_memories 白名单事实），"
            "供跨会话续聊引用。无记忆返回诚实空态。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}

# OpenAI function-calling 对齐声明（type=function / function.name+parameters）
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {"name": name, **definition},
    }
    for name, definition in _TOOL_DEFINITIONS.items()
]


def _schema_by_name(name: str) -> dict[str, Any] | None:
    definition = _TOOL_DEFINITIONS.get(name)
    return definition.get("parameters") if definition is not None else None


def _coerce_arguments(
    parameters: dict[str, Any], arguments: dict[str, Any] | None
) -> dict[str, Any]:
    """按 Schema 校验/整形参数；非法即抛 ValueError（fail-closed）。

    只允许声明内的键（additionalProperties=False），并按声明类型检查：
    string / boolean / integer（不含 bool）/ array（全 string）。
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("参数必须是对象")
    properties = parameters.get("properties") or {}
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        if key not in properties:
            raise ValueError(f"未知参数「{key}」")
        spec = properties[key]
        declared = spec.get("type")
        if declared == "string":
            if not isinstance(value, str):
                raise ValueError(f"参数「{key}」需要字符串")
        elif declared == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"参数「{key}」需要布尔值")
        elif declared == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"参数「{key}」需要整数")
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and value < minimum:
                raise ValueError(f"参数「{key}」不能小于 {minimum}")
            if maximum is not None and value > maximum:
                raise ValueError(f"参数「{key}」不能大于 {maximum}")
        elif declared == "array":
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f"参数「{key}」需要字符串数组")
        else:
            raise ValueError(f"参数「{key}」类型未声明")
        cleaned[key] = value
    for required in parameters.get("required") or []:
        if required not in cleaned:
            raise ValueError(f"缺少必填参数「{required}」")
    return cleaned


def build_tool_runtime(
    *,
    db: Session,
    student_id: str,
    portrait: Any = None,
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """按会话上下文构建确定性工具执行体（只读，不经 LLM）。

    portrait 为已确认画像（可空），供招募相关度排序复用；student_id 供
    本人记忆召回。
    """

    def _query_mentor_knowledge(arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        record = mentor_knowledge.query_mentor_knowledge(name)
        if record is None:
            return mentor_knowledge.render_mentor_not_found(name)
        return mentor_knowledge.render_mentor_knowledge(record)

    def _get_recruitments(arguments: dict[str, Any]) -> str:
        records, _withheld = recruitment_public.list_public_recruitments(
            db,
            urgent_only=bool(arguments.get("urgent_only", False)),
        )
        return recruitment_public.format_recruitment_digest(
            records,
            profile=portrait,
            limit=int(arguments.get("limit", 3)),
        )

    def _recall_memory(arguments: dict[str, Any]) -> str:
        summary = format_memory_summary(db, student_id)
        if not summary:
            return "暂无已确认的长期记忆；完成访谈并确认画像后会自动保存。"
        return f"已确认画像记忆：{summary}"

    return {
        TOOL_QUERY_MENTOR_KNOWLEDGE: _query_mentor_knowledge,
        TOOL_GET_RECRUITMENTS: _get_recruitments,
        TOOL_RECALL_MEMORY: _recall_memory,
    }


def dispatch_tool_call(
    runtime: dict[str, Callable[[dict[str, Any]], str]],
    *,
    name: str,
    arguments: dict[str, Any] | None,
) -> str:
    """校验并执行一次工具调用，返回确定性文本；任何失败返回错误文本。"""
    parameters = _schema_by_name(name)
    if parameters is None:
        available = "、".join(_TOOL_DEFINITIONS)
        return f"未知工具「{name}」；可用工具：{available}。"
    try:
        cleaned = _coerce_arguments(parameters, arguments)
    except ValueError as exc:
        return f"工具参数无效：{exc}"
    executor = runtime.get(name)
    if executor is None:
        return f"工具「{name}」未在当前会话注册。"
    try:
        return executor(cleaned)
    except Exception as exc:  # 执行失败 → 诚实降级，不抛异常不编造
        logger.warning("tool dispatch failed: %s (%s)", name, exc)
        return f"工具「{name}」执行失败，请稍后重试。"
