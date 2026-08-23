"""v4.0.0 任务1 阶段B：确定性工具注册表（OpenAI function-calling 对齐）。

v4.3.0 全 Agent 化：从 3 只读工具扩展为 **8 工具**——query_mentor_knowledge /
get_recruitments / recall_memory 只读 + get_directions / search_mentors /
get_mentor_detail 只读 + compute_match（带画像确认闸门）+ update_profile
（唯一受控写）。全部供 Agent 编排层（agent_orchestrator）的 GLM 通过
function-calling 自主调用；事实仍全部由确定性执行体产出，fail-closed 不变。

注册表提供两样东西：
- TOOL_SCHEMAS：与 OpenAI function-calling 对齐的 JSON Schema 声明，作为
  协议契约（agent_orchestrator 直传 GLM；chat.py 亦按名字确定性 dispatch），
  并由 `dispatch_tool_call` 做参数校验；
- build_tool_runtime / dispatch_tool_call：参数校验（fail-closed）后调用
  既有服务函数确定性执行，输出纯文本，不经 LLM。

红线：
- 8 工具分权：query_mentor_knowledge / get_recruitments / recall_memory /
  get_directions / search_mentors / get_mentor_detail 全部只读；compute_match
  带确认闸门（confirm_profile=true 且服务端校验画像已确认才执行匹配）；
  update_profile 为唯一受控写（确认门内写画像，写后需重新确认再匹配），
  其余工具不写库、不触碰访谈状态机；
- fail-closed：未知工具、参数非法、执行异常 → 返回确定性错误文本，
  不抛异常、不吞消息、不降级为编造；
- 与对话管线同源：执行体即 chat 各 handler 复用的既有函数，行为一致。
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services import mentor_knowledge, recruitment_public
from app.services.advisor_rating import get_gated_summary
from app.services.direction_map import (
    DIRECTION_MAP_ALIASES,
    DIRECTION_MAP_DATA,
    resolve_direction,
)
from app.services.interview import (
    InterviewAccessError,
    InterviewConflictError,
    InterviewNotFoundError,
    _constraint_label,
    _draft_constraint,
    _interest_tags,
    confirmed_portrait,
    upsert_portrait_field,
)
from app.services.match_application import (
    derive_user_dimension_scores,
    format_match_outcome,
    run_confirmed_match,
)
from app.services.match_refine import persisted_refine_constraints
from app.services.memory_service import format_memory_summary
from app.services.mentor_catalog import enriched_mentor_resources
from app.services.mentor_score_governance import public_score_bundles
from app.services.radar_chart import (
    OBJECTIVE_DIMENSION_KEYS,
    RADAR_DIMENSION_LABELS,
)

logger = logging.getLogger(__name__)

TOOL_QUERY_MENTOR_KNOWLEDGE = "query_mentor_knowledge"
TOOL_GET_RECRUITMENTS = "get_recruitments"
TOOL_RECALL_MEMORY = "recall_memory"
# —— 全 Agent 化：5 个 Agent 工具（GLM 自主调用的编排原语）——
TOOL_GET_DIRECTIONS = "get_directions"
TOOL_SEARCH_MENTORS = "search_mentors"
TOOL_COMPUTE_MATCH = "compute_match"
TOOL_GET_MENTOR_DETAIL = "get_mentor_detail"
TOOL_UPDATE_PROFILE = "update_profile"

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
    TOOL_GET_DIRECTIONS: {
        "description": "获取指定院系的细分研究方向列表（含各方向导师数）",
        "parameters": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "学生院系全称，如 计算机科学与技术系",
                },
            },
            "required": ["department"],
            "additionalProperties": False,
        },
    },
    TOOL_SEARCH_MENTORS: {
        "description": "按关键词/院系/方向检索导师库（只读，返回公开事实）",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "检索关键词（匹配姓名/院系/职称/专业/研究方向）",
                },
                "department": {
                    "type": "string",
                    "description": "院系过滤（子串匹配）",
                },
                "direction": {
                    "type": "string",
                    "description": "研究方向过滤（规范方向名或别名）",
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 1,
                    "description": "页码（默认 1）",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    TOOL_COMPUTE_MATCH: {
        "description": (
            "用当前会话画像执行导师匹配，返回推荐列表（含适配分/保守排序分/"
            "六维/原因结构体/来源）"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "confirm_profile": {
                    "type": "boolean",
                    "description": "首次调用须为 true 表示画像已获学生确认",
                },
            },
            "required": ["confirm_profile"],
            "additionalProperties": False,
        },
    },
    TOOL_GET_MENTOR_DETAIL: {
        "description": "导师详情：字段级信息+来源徽章+客观指标+证据计数",
        "parameters": {
            "type": "object",
            "properties": {
                "mentor_id": {
                    "type": "string",
                    "description": "导师 ID（advisor_id，可经 search_mentors 获取）",
                },
            },
            "required": ["mentor_id"],
            "additionalProperties": False,
        },
    },
    TOOL_UPDATE_PROFILE: {
        "description": (
            "修改画像字段（研究兴趣/六维权重/硬约束），修改后自动触发重新匹配"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": [
                        "research_interests",
                        "weights",
                        "constraints",
                        "basics",
                    ],
                    "description": "画像字段类别",
                },
                "value": {
                    "type": "string",
                    "description": "修改内容（格式因字段而异，见执行体校验）",
                },
            },
            "required": ["field", "value"],
            "additionalProperties": False,
        },
    },
}

# OpenAI function-calling 对齐声明（type=function / function.name+parameters）。
# 全 Agent 化后包含全部 8 个工具；chat.py 确定性路由只按名字 dispatch，
# schema 列表变长不影响既有调用方。
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {"name": name, **definition},
    }
    for name, definition in _TOOL_DEFINITIONS.items()
]

# 全部 8 工具的 function-calling schema（供 agent_orchestrator 直传 GLM）
AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = TOOL_SCHEMAS


def _schema_by_name(name: str) -> dict[str, Any] | None:
    definition = _TOOL_DEFINITIONS.get(name)
    return definition.get("parameters") if definition is not None else None


def _coerce_arguments(
    parameters: dict[str, Any], arguments: dict[str, Any] | None
) -> dict[str, Any]:
    """按 Schema 校验/整形参数；非法即抛 ValueError（fail-closed）。

    只允许声明内的键（additionalProperties=False），并按声明类型检查：
    string（含 enum 取值集合）/ boolean / integer（不含 bool）/ number /
    array（全 string）。
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
            allowed = spec.get("enum")
            if allowed is not None and value not in allowed:
                raise ValueError(
                    f"参数「{key}」取值必须是：{'、'.join(str(item) for item in allowed)}"
                )
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
        elif declared == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"参数「{key}」需要数字")
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


# —— 检索归一化（与 app/api/v1/advisor.py get_all_mentors 同口径）——


def _normalize_search_text(value: object) -> str:
    """NFKC + casefold 归一化（列表拼接），与公开检索 API 完全一致。"""
    if isinstance(value, list):
        return " ".join(_normalize_search_text(item) for item in value)
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def _mentor_direction_blob(record: dict[str, Any]) -> str:
    """导师记录的方向字段（research_keywords + programs）拼接为匹配文本。"""
    parts: list[str] = []
    for field in ("research_keywords", "programs"):
        value = record.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if str(item).strip())
        elif value:
            parts.append(str(value))
    return " ".join(parts)


def _mentor_direction_display(record: dict[str, Any]) -> str:
    """导师研究方向展示文本（research_keywords 优先，programs 兜底）。"""
    keywords = record.get("research_keywords")
    parts: list[str] = []
    if isinstance(keywords, list):
        parts = [str(item).strip() for item in keywords if str(item).strip()]
    if not parts:
        programs = record.get("programs")
        if isinstance(programs, list):
            parts = [str(item).strip() for item in programs if str(item).strip()]
    return "、".join(parts)


def _direction_terms(canonical: str, keywords: str) -> list[str]:
    """规范方向 → 匹配词表：方向名分词 + 示例关键词 + 方向别名（含英文）。"""
    terms = [part.strip() for part in canonical.split("/") if part.strip()]
    terms += [part.strip() for part in re.split(r"[、，,]", keywords) if part.strip()]
    terms += [
        alias for alias, target in DIRECTION_MAP_ALIASES if target == canonical
    ]
    return [term for term in terms if term]


# 规范方向 → 匹配词表（确定性预计算，与 DIRECTION_MAP_DATA 一一对应）
_DIRECTION_TERMS: dict[str, list[str]] = {
    name: _direction_terms(name, keywords) for name, _desc, keywords in DIRECTION_MAP_DATA
}


def _mentor_matches_direction(record: dict[str, Any], terms: list[str]) -> bool:
    """导师方向字段与方向词表做子串匹配（词面匹配，不做语义推断）。"""
    blob = _mentor_direction_blob(record).casefold()
    return any(term.casefold() in blob for term in terms)


def _direction_filter_terms(direction: str) -> list[str] | None:
    """检索方向参数 → 匹配词表；无法归一（非空但未知）时按原文子串匹配。"""
    text = (direction or "").strip()
    if not text:
        return None
    canonical = resolve_direction(text)
    if canonical is not None:
        return _DIRECTION_TERMS.get(canonical) or [canonical]
    return [text]


# 适配分锚点：从匹配渲染文本中提取「契合度 N 分」里的精确数值字符串
# （与 format_match_item 的 {fit_score:.0f} 渲染逐字一致），供编排层
# 对最终回复做逐字锚点校验，防止 LLM 改写分数。
_FIT_SCORE_ANCHOR_RE = re.compile(r"契合度 (\d+) 分")

# update_profile：合法字段类别（与 schema enum 一致；执行体再次校验，
# fail-closed 文本提示）
_PROFILE_FIELDS = frozenset({"research_interests", "weights", "constraints", "basics"})

_SESSION_UNAVAILABLE = "当前会话上下文不可用，无法执行该操作"
_PORTRAIT_UNCONFIRMED_MATCH = (
    "画像尚未获学生确认，请先完成画像确认后再调用匹配。"
)
_PORTRAIT_UNCONFIRMED_UPDATE = "画像尚未确认，请先完成访谈与画像确认后再修改。"
# weights/basics：画像确认卡专属编辑入口，对话通道不支持（fail-closed）
_FIELD_EDIT_VIA_CARD = "该字段请通过画像确认卡编辑后重新确认，暂不支持对话修改。"


def build_tool_runtime(
    *,
    db: Session,
    student_id: str,
    portrait: Any = None,
    session_id: str | None = None,
    anchor_sink: list[str] | None = None,
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """按会话上下文构建确定性工具执行体（只读/受控写，不经 LLM）。

    portrait 为已确认画像（可空），供招募相关度排序复用；student_id 供
    本人记忆召回；session_id 供 Agent 工具（compute_match /
    update_profile）访问访谈会话，缺省时这两个工具返回确定性提示
    （fail-closed，不抛异常）。
    anchor_sink 为可选锚点收集器（list[str]）：工具执行体把"最终回复
    必须逐字包含的关键事实"（如每个推荐项的适配分数值）append 进去，
    供编排层（agent_orchestrator）对最终回复做逐字锚点校验，防止 LLM
    篡改数字；缺省（None）时行为与旧签名完全一致（向后兼容）。
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

    # —— Agent 工具执行体（全部只读或受控写，异常 → 确定性文本）——

    def _run_confirmed_match_text() -> str:
        """执行已确认画像匹配并渲染文本（与 chat.py 匹配分支同口径）。"""
        confirmed = confirmed_portrait(
            db, session_id=session_id, student_id=student_id
        )
        outcome = run_confirmed_match(
            db,
            session_id=session_id,
            student_id=student_id,
            extra_constraints=persisted_refine_constraints(
                db, session_id=session_id, student_id=student_id
            ),
        )
        ratings: dict[str, dict] = {}
        for item in outcome.items:
            advisor_id = str(item.get("advisor_id") or "")
            if not advisor_id:
                continue
            gated = get_gated_summary(db, advisor_id)
            if gated is not None:
                ratings[advisor_id] = gated
        user_scores = derive_user_dimension_scores(confirmed)
        text = format_match_outcome(
            outcome,
            profile=confirmed,
            advisor_ratings=ratings,
            user_dimension_scores=user_scores,
        )
        # 锚点收集：每个推荐项的适配分数值以渲染文本中出现的精确字符串
        # 形式（如「契合度 87 分」中的「87」）append 进 anchor_sink，
        # 供编排层逐字校验防篡改（needs_clarification / no_match 等状态
        # 无分数项，自然不产生锚点）。
        if anchor_sink is not None:
            for match in _FIT_SCORE_ANCHOR_RE.finditer(text):
                anchor = match.group(1)
                if anchor not in anchor_sink:
                    anchor_sink.append(anchor)
        return text

    def _get_directions(arguments: dict[str, Any]) -> str:
        department = str(arguments.get("department") or "").strip()
        try:
            records, _status = enriched_mentor_resources()
        except Exception as exc:
            logger.warning("agent tool get_directions failed: %s", exc)
            records = []
        dept_key = _normalize_search_text(department).strip() if department else ""
        scoped = records
        fallback_note = ""
        if dept_key and records:
            scoped = [
                record
                for record in records
                if dept_key in _normalize_search_text(record.get("dept"))
            ]
            if not scoped:
                # 院系无目录数据：诚实说明并退回全部方向，不冒充该院系统计
                scoped = records
                fallback_note = (
                    f"未找到该院系（{department}）的导师目录数据，以下为全部方向。"
                )
        lines: list[str] = []
        if not records:
            lines.append("导师目录暂无数据，以下为公开研究方向地图（导师数为 0）：")
        elif fallback_note:
            lines.append(fallback_note)
        else:
            header = f"【{department} 可选研究方向】" if dept_key else "【可选研究方向】"
            lines.append(header)
        for index, (name, desc, _keywords) in enumerate(DIRECTION_MAP_DATA, start=1):
            terms = _DIRECTION_TERMS.get(name) or []
            count = sum(
                1 for record in scoped if _mentor_matches_direction(record, terms)
            )
            lines.append(f"{index}) {name}（{count} 位导师）：{desc}")
        lines.append("")
        lines.append("可回复方向名或数字（如 1,3）选择感兴趣的方向（可多选 1-3 项）")
        return "\n".join(lines)

    def _search_mentors(arguments: dict[str, Any]) -> str:
        keyword = str(arguments.get("keyword") or "").strip()
        department = str(arguments.get("department") or "").strip()
        direction = str(arguments.get("direction") or "").strip()
        page = int(arguments.get("page", 1) or 1)
        try:
            records, _status = enriched_mentor_resources()
        except Exception as exc:
            logger.warning("agent tool search_mentors failed: %s", exc)
            return "导师目录暂时不可用，请稍后重试。"
        query = _normalize_search_text(keyword).strip() if keyword else ""
        dept_key = _normalize_search_text(department).strip() if department else ""
        direction_terms = _direction_filter_terms(direction)

        def selected(record: dict[str, Any]) -> bool:
            # 过滤口径与 GET /mentors（advisor.py get_all_mentors）一致：
            # 院系子串 + 关键词命中（姓名/院系/职称/专业/研究方向关键词）
            if dept_key and dept_key not in _normalize_search_text(record.get("dept")):
                return False
            if direction_terms and not _mentor_matches_direction(
                record, direction_terms
            ):
                return False
            if query:
                haystack = _normalize_search_text(
                    [
                        record.get("name"),
                        record.get("dept"),
                        record.get("title"),
                        record.get("programs", []),
                        record.get("research_keywords", []),
                    ]
                )
                if query not in haystack:
                    return False
            return True

        filtered = sorted(
            (record for record in records if selected(record)),
            key=lambda item: (
                _normalize_search_text(item.get("dept")),
                _normalize_search_text(item.get("name")),
                str(item.get("advisor_id", "")),
            ),
        )
        if not filtered:
            return "未检索到匹配导师，建议更换关键词或调整院系/方向筛选后重试。"
        page_size = 5
        total_pages = math.ceil(len(filtered) / page_size)
        page = max(1, page)
        if page > total_pages:
            # 超出页码范围：诚实提示，不出空页冒充结果
            return (
                f"已超出页码范围：共 {len(filtered)} 位导师、{total_pages} 页"
                f"（每页 {page_size} 条），请调整 page 参数。"
            )
        offset = (page - 1) * page_size
        page_records = filtered[offset : offset + page_size]
        lines: list[str] = []
        for index, record in enumerate(page_records, start=1):
            name = str(record.get("name") or "姓名未收录")
            dept = str(record.get("dept") or "").strip()
            title = str(record.get("title") or "").strip()
            header = f"{name} · {dept}" if dept else name
            if title:
                header = f"{header} {title}"
            direction_text = _mentor_direction_display(record)
            if len(direction_text) > 40:
                direction_text = direction_text[:40] + "…"
            line = f"{index}) {header}"
            if direction_text:
                line = f"{line} · {direction_text}"
            lines.append(line)
            # 第二行：导师 ID + 官方主页（仅公开事实字段；ID 供
            # get_mentor_detail 精确调用）
            detail_parts: list[str] = []
            advisor_id = str(record.get("advisor_id") or "").strip()
            if advisor_id:
                detail_parts.append(f"导师 ID：{advisor_id}")
            homepage = str(record.get("official_homepage") or "").strip()
            if homepage:
                detail_parts.append(f"主页：{homepage}")
            if detail_parts:
                lines.append("   " + "｜".join(detail_parts))
        lines.append("")
        lines.append(
            f"共 {len(filtered)} 位导师 · 第 {page} 页 / 共 {total_pages} 页"
            f"（每页 {page_size} 条），可用导师 ID 调用 get_mentor_detail 查看详情"
        )
        return "\n".join(lines)

    def _compute_match(arguments: dict[str, Any]) -> str:
        if arguments.get("confirm_profile") is not True:
            return _PORTRAIT_UNCONFIRMED_MATCH
        if not session_id:
            return _SESSION_UNAVAILABLE
        try:
            return _run_confirmed_match_text()
        except (
            InterviewNotFoundError,
            InterviewAccessError,
            InterviewConflictError,
        ):
            # 服务端闸门：画像未确认 / 会话不存在 / 无权访问 → 确定性提示
            return _PORTRAIT_UNCONFIRMED_MATCH
        except Exception as exc:
            logger.warning("agent tool compute_match failed: %s", exc)
            return "匹配服务暂时不可用，请稍后重试。"

    def _get_mentor_detail(arguments: dict[str, Any]) -> str:
        mentor_id = str(arguments.get("mentor_id") or "").strip()
        try:
            records, _status = enriched_mentor_resources()
        except Exception as exc:
            logger.warning("agent tool get_mentor_detail failed: %s", exc)
            return "导师目录暂时不可用，请稍后重试。"

        def _matches(record: dict[str, Any]) -> bool:
            # 兼容多种 ID 形式：主 advisor_id，或同一导师聚合记录里的
            # linked_resource_ids（多源目录条目 ID），全部为目录真实字段
            if str(record.get("advisor_id") or "") == mentor_id:
                return True
            linked = record.get("linked_resource_ids") or []
            return isinstance(linked, list) and mentor_id in [
                str(item) for item in linked
            ]

        record = next((item for item in records if _matches(item)), None)
        if record is None:
            return "未找到该导师，请确认导师 ID 或用 search_mentors 检索。"
        lines: list[str] = []
        name = str(record.get("name") or "姓名未收录")
        dept = str(record.get("dept") or "").strip()
        title = str(record.get("title") or "").strip()
        header = f"{name} · {dept}" if dept else name
        if title:
            header = f"{header} {title}"
        lines.append(f"{header} 🏛官方目录")
        direction = _mentor_direction_display(record)
        if direction:
            lines.append(f"研究方向：{direction} 🏛官方目录")
        homepage = str(record.get("official_homepage") or "").strip()
        if homepage:
            lines.append(f"官方主页：{homepage} ✅已核验")
        # 客观指标：以聚合记录的主 advisor_id 查评分发布包（📊客观证据）
        catalog_id = str(record.get("advisor_id") or "")
        try:
            bundles, _gate = public_score_bundles()
        except Exception as exc:
            logger.warning("agent tool get_mentor_detail scores failed: %s", exc)
            bundles = {}
        bundle = bundles.get(catalog_id)
        if bundle:
            values = bundle.get("values") or {}
            citations = bundle.get("citations") or {}
            lines.append("客观指标（📊客观证据，公开证据换算 0-100）：")
            for key in OBJECTIVE_DIMENSION_KEYS:
                label = RADAR_DIMENSION_LABELS.get(key, key)
                raw = values.get(key)
                if raw is None:
                    lines.append(f"- {label}：导师暂无该维公开数据")
                else:
                    lines.append(f"- {label}：{float(raw):.0f}")
            lines.append(f"客观证据共 {len(citations)} 项（逐维可溯源）。")
        else:
            lines.append(
                "客观指标：导师暂无公开客观数据"
                "（📊客观证据未覆盖该导师，相关维度未参与排序）。"
            )
        return "\n".join(lines)

    def _update_profile(arguments: dict[str, Any]) -> str:
        # 唯一受控写工具：先校验 field 合法性（fail-closed 文本提示；
        # _coerce_arguments 已按 enum 拦截，这里是执行体侧双保险）
        field = str(arguments.get("field") or "")
        if field not in _PROFILE_FIELDS:
            return f"画像更新失败：不支持的字段「{field}」。"
        value = str(arguments.get("value") or "").strip()
        if not value:
            return "画像更新失败：value 不能为空。"
        # value 清洗：长度上限 500（超长截断，防画像污染）
        value = value[:500]
        # 闸门：无会话或画像未确认 → 拒绝受控写（fail-closed）
        if not session_id:
            return _PORTRAIT_UNCONFIRMED_UPDATE
        try:
            try:
                confirmed = confirmed_portrait(
                    db, session_id=session_id, student_id=student_id
                )
            except (
                InterviewNotFoundError,
                InterviewAccessError,
                InterviewConflictError,
            ):
                # 服务端闸门：画像未确认不允许受控写
                return _PORTRAIT_UNCONFIRMED_UPDATE
            if field in ("weights", "basics"):
                # 画像确认卡专属编辑入口，对话通道不支持
                return _FIELD_EDIT_VIA_CARD
            if field == "research_interests":
                # 与 direction_map.handle_direction_map 同款用法：
                # _interest_tags 解析标签 → upsert_portrait_field 合并
                # 去重写入（画像变化后回落 awaiting_confirmation）
                tags = _interest_tags(value)
                if not tags:
                    return (
                        "画像更新失败：未能从 value 中解析出有效的研究兴趣标签，"
                        "请用逗号分隔的简短方向词（如：大模型, 强化学习）。"
                    )
                upsert_portrait_field(
                    db,
                    session_id=session_id,
                    student_id=student_id,
                    changes={"research_interests": tags},
                )
                updated = f"已记录研究兴趣：{'、'.join(tags)}"
            else:
                # constraints：复用访谈层同一约束解析器，参考现有
                # 硬约束数据结构结构化追加（fail-closed：低置信文本不给
                # 结构化形态，诚实拒绝而不是猜测入库）
                draft = _draft_constraint(value)
                proposed = draft.proposed_constraint
                if proposed is None:
                    return (
                        "无法把这段文本解析为结构化硬约束，不猜测入库；"
                        "硬约束请通过画像确认卡修改，或说明具体字段与值"
                        "（如「地点必须在北京」「每周至少投入 3 天」）。"
                    )
                confirmed_data = confirmed.model_dump(mode="json")
                proposed_data = proposed.model_dump(mode="json")
                duplicate = any(
                    item.get("field") == proposed_data.get("field")
                    and item.get("operator") == proposed_data.get("operator")
                    and item.get("value") == proposed_data.get("value")
                    for item in confirmed_data.get("hard_constraints") or []
                )
                if duplicate:
                    return (
                        f"该硬约束已存在于画像中（{_constraint_label(proposed)}），"
                        "无需重复添加。"
                    )
                merged = list(confirmed_data.get("hard_constraints") or [])
                merged.append(proposed_data)
                upsert_portrait_field(
                    db,
                    session_id=session_id,
                    student_id=student_id,
                    changes={"hard_constraints": merged},
                )
                updated = f"已新增硬约束：{_constraint_label(proposed)}"
            # direction_map.py 同款语义：画像已更新，需重新确认后再匹配
            return (
                f"画像已更新：{updated}。\n\n"
                "画像有更新，需要重新确认后再匹配：请回复「确认画像」完成确认，"
                "再重新执行匹配。"
            )
        except Exception as exc:
            logger.warning("agent tool update_profile failed: %s", exc)
            return "画像更新失败：服务暂时不可用，请稍后重试。"

    return {
        TOOL_QUERY_MENTOR_KNOWLEDGE: _query_mentor_knowledge,
        TOOL_GET_RECRUITMENTS: _get_recruitments,
        TOOL_RECALL_MEMORY: _recall_memory,
        TOOL_GET_DIRECTIONS: _get_directions,
        TOOL_SEARCH_MENTORS: _search_mentors,
        TOOL_COMPUTE_MATCH: _compute_match,
        TOOL_GET_MENTOR_DETAIL: _get_mentor_detail,
        TOOL_UPDATE_PROFILE: _update_profile,
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
