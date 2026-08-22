"""确定性工具注册表（OpenAI function-calling 对齐；v4.3.0 阶段五扩展）。

v4.0.0 阶段B 起为服务端确定性路由；v4.3.0 阶段五「工具域转正」：
LLM 可自主调用注册表内**白名单标记**的工具（3 只读 + save_favorite
+ send_contact_request），自主调用决定"何时调"，结果仍由注册表确定性
渲染（不经 LLM 改写事实）。

红线（注册表白名单制）：
- 新增 LLM 可调工具必须在 _TOOL_DEFINITIONS 显式标记
  llm_callable=True 并过评审；画像确认/匹配触发/记忆写入/招募发布
  等能力**永不注册**（见 tests 架构护栏断言）；
- 敏感工具（sensitive=True，如 send_contact_request）执行体只登记
  待确认动作并返回确认指令——无精确确认词绝不执行（反骚扰）；
- fail-closed：未知工具、参数非法、执行异常 → 确定性错误文本，
  不抛异常、不吞消息、不编造；
- save_favorite 只能收藏当前匹配上下文中的 advisor_id（防幻觉 ID）。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.mentor_favorite import MentorFavorite
from app.services import mentor_knowledge, recruitment_public
from app.services.memory_service import format_memory_summary

logger = logging.getLogger(__name__)

TOOL_QUERY_MENTOR_KNOWLEDGE = "query_mentor_knowledge"
TOOL_GET_RECRUITMENTS = "get_recruitments"
TOOL_RECALL_MEMORY = "recall_memory"
TOOL_SAVE_FAVORITE = "save_favorite"
TOOL_SEND_CONTACT_REQUEST = "send_contact_request"

# 待确认联系意向的会话 KV 键（chat.py 二次确认门读取/清除）
PENDING_CONTACT_KEY = "pending_contact_request"

_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    TOOL_QUERY_MENTOR_KNOWLEDGE: {
        "llm_callable": True,
        "sensitive": False,
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
        "llm_callable": True,
        "sensitive": False,
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
        "llm_callable": True,
        "sensitive": False,
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
    TOOL_SAVE_FAVORITE: {
        # v4.3.0 阶段五：白名单写操作（幂等收藏；只接受当前匹配上下文
        # 内的 advisor_id，防 LLM 幻觉 ID）
        "llm_callable": True,
        "sensitive": False,
        "description": (
            "收藏一位导师（幂等：已收藏则提示，不重复入库）。advisor_id "
            "只能来自当前对话上下文中的匹配候选列表，不得凭记忆填写。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "advisor_id": {
                    "type": "string",
                    "description": "当前匹配候选列表中的导师标识",
                }
            },
            "required": ["advisor_id"],
            "additionalProperties": False,
        },
    },
    TOOL_SEND_CONTACT_REQUEST: {
        # v4.3.0 阶段五：敏感写操作——执行体只登记待确认动作并返回
        # 确认指令；用户回复精确确认词后才由 chat.py 走既有套磁链路
        "llm_callable": True,
        "sensitive": True,
        "description": (
            "发起联系某位导师的请求（生成套磁邮件初稿）。这是敏感操作："
            "必须先向用户复述目标导师并获得精确确认后才能执行。"
            "advisor_id 只能来自当前匹配候选列表。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "advisor_id": {
                    "type": "string",
                    "description": "当前匹配候选列表中的导师标识",
                },
                "message": {
                    "type": "string",
                    "description": "用户想向导师表达的联系意图（可选）",
                },
            },
            "required": ["advisor_id"],
            "additionalProperties": False,
        },
    },
}

# OpenAI function-calling 对齐声明（type=function / function.name+parameters）
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": definition["description"],
            "parameters": definition["parameters"],
        },
    }
    for name, definition in _TOOL_DEFINITIONS.items()
]

# LLM 自主调用白名单面（llm_callable=True 且过评审；发送给 GLM 请求体）
LLM_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": definition["description"],
            "parameters": definition["parameters"],
        },
    }
    for name, definition in _TOOL_DEFINITIONS.items()
    if definition.get("llm_callable")
]


def is_sensitive_tool(name: str) -> bool:
    """敏感工具判定（chat.py 自主调用层据此走二次确认门）。"""
    definition = _TOOL_DEFINITIONS.get(name)
    return bool(definition and definition.get("sensitive"))


def format_favorite_listing(db: Session, student_id: str) -> str:
    """收藏列表的确定性渲染（chat.py「我的收藏」意图词路由）。"""
    records = (
        db.query(MentorFavorite)
        .filter(MentorFavorite.student_id == student_id)
        .order_by(MentorFavorite.created_at)
        .all()
    )
    if not records:
        return (
            "收藏列表为空。在匹配结果里回复「收藏第 N 个」即可收藏"
            "感兴趣的导师。"
        )
    lines = [f"当前收藏了 {len(records)} 位导师："]
    for index, record in enumerate(records, start=1):
        name = record.advisor_name or record.advisor_id
        lines.append(f"{index}. {name}")
    lines.append("回复「取消收藏第 N 个」可移除（N 为上表序号）。")
    return "\n".join(lines)


def remove_favorite(
    db: Session,
    *,
    student_id: str,
    ordinal: int,
) -> str:
    """按收藏列表序号移除（确定性，越界诚实提示）。"""
    records = (
        db.query(MentorFavorite)
        .filter(MentorFavorite.student_id == student_id)
        .order_by(MentorFavorite.created_at)
        .all()
    )
    if not records:
        return "收藏列表为空，没有可移除的导师。"
    if not 1 <= ordinal <= len(records):
        return (
            f"收藏列表共有 {len(records)} 位导师（第 1 到第 "
            f"{len(records)}），回复「我的收藏」可查看列表。"
        )
    record = records[ordinal - 1]
    name = record.advisor_name or record.advisor_id
    db.delete(record)
    db.commit()
    return f"已取消收藏 {name}。"


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
    session_id: str | None = None,
    match_items: list[dict[str, Any]] | None = None,
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """按会话上下文构建确定性工具执行体（校验后执行，不经 LLM）。

    portrait 为已确认画像（可空），供招募相关度排序复用；student_id 供
    本人记忆召回与收藏归属。v4.3.0 阶段五新增：session_id 供敏感工具
    登记待确认动作（dialogue_sessions KV）；match_items 为当前匹配候选
    上下文（advisor_id/name），收藏与联系请求据此校验目标导师（防幻觉）。
    """
    items = list(match_items or [])

    def _match_item_by_advisor(advisor_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in items
                if str(item.get("advisor_id") or "") == advisor_id
            ),
            None,
        )

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

    def _save_favorite(arguments: dict[str, Any]) -> str:
        advisor_id = str(arguments.get("advisor_id") or "").strip()
        if not advisor_id:
            return "收藏失败：缺少导师标识。"
        item = _match_item_by_advisor(advisor_id)
        if item is None:
            return (
                "收藏失败：该导师不在当前匹配候选中，只能收藏本轮结果里的"
                "导师（防止误收藏不存在的导师）。"
            )
        name = str(item.get("name") or advisor_id)
        existing = (
            db.query(MentorFavorite)
            .filter(
                MentorFavorite.student_id == student_id,
                MentorFavorite.advisor_id == advisor_id,
            )
            .one_or_none()
        )
        if existing is not None:
            return f"{name} 已在收藏列表，无需重复收藏。"
        db.add(
            MentorFavorite(
                favorite_id=str(uuid.uuid4()),
                student_id=student_id,
                advisor_id=advisor_id,
                advisor_name=name,
            )
        )
        db.commit()
        return f"已收藏导师 {name}。回复「我的收藏」可随时查看。"

    def _send_contact_request(arguments: dict[str, Any]) -> str:
        # 敏感工具：本执行体绝不直接联系导师——只登记待确认动作并
        # 返回确认指令；精确确认词由 chat.py 二次确认门校验后走既有
        # 套磁链路（反骚扰红线）。
        advisor_id = str(arguments.get("advisor_id") or "").strip()
        message = str(arguments.get("message") or "").strip()
        if not advisor_id:
            return "联系请求失败：缺少导师标识。"
        item = _match_item_by_advisor(advisor_id)
        if item is None:
            return (
                "联系请求失败：该导师不在当前匹配候选中，只能联系本轮结果"
                "里的导师。"
            )
        name = str(item.get("name") or advisor_id)
        if not session_id:
            return (
                f"已收到联系 {name} 的意向，但当前会话不支持确认流程，"
                "未执行任何联系操作。"
            )
        from app.services.dialogue_state_store import set_session_value

        set_session_value(
            db,
            session_id=session_id,
            student_id=student_id,
            key=PENDING_CONTACT_KEY,
            value=json.dumps(
                {
                    "advisor_id": advisor_id,
                    "advisor_name": name,
                    "message": message,
                },
                ensure_ascii=False,
            ),
        )
        return (
            f"即将为导师 {name} 生成套磁邮件初稿并记录联系意向。\n\n"
            f"确认请回复「确认联系{name}」，取消请回复「取消」。"
            "未确认前不会执行任何联系操作。"
        )

    return {
        TOOL_QUERY_MENTOR_KNOWLEDGE: _query_mentor_knowledge,
        TOOL_GET_RECRUITMENTS: _get_recruitments,
        TOOL_RECALL_MEMORY: _recall_memory,
        TOOL_SAVE_FAVORITE: _save_favorite,
        TOOL_SEND_CONTACT_REQUEST: _send_contact_request,
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
