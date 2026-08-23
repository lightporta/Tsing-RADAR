"""v2.5 招募对话模块：自然语言语义筛选 + 个性化推荐 + 投递辅助。

设计约定：
- 语义筛选完全确定性：院系别名 / 招募类型 / 急招 / 方向关键词，从一句
  自然语言解析为结构化过滤条件，复用 list_public_recruitments 的公开口径
  （静态 + DB、verified + published + 未下架 + 未过期）；方向别名归一化
  （NLP ↔ 自然语言处理、LLM ↔ 大模型 等）双向映射后再匹配；
- 个性化推荐：画像 research_interests + hard_constraints 与招募字段做
  相关度排序，输出推荐理由与推荐指数（★），全部基于已有公开数据，
  不编造名额、薪资或联系方式；
- 宽泛问题：无筛选条件时，有画像按研究兴趣推荐并给出进一步筛选引导，
  无画像给引导后展示最新在招概览；同一会话中用户明确说过的筛选条件会
  被记住（dialogue_sessions），之后宽泛查询自动沿用；
- 岗位联动：回复序号（"第 1 个"）查看完整详情（含距截止天数），
  "针对第 1 个优化简历"由简历模块解析为岗位并附加公开核心要求；
- 投递辅助：推荐后主动提议联动简历定向优化（指向 recruit_dialogue）；
- 诚实性：无过审在招记录、无画像、或筛选后无结果时，均给出诚实说明，
  不伪造"热门推荐"。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.interview import StudentPortrait
from app.services.dialogue_state_store import (
    get_dialogue_mode,
    get_dialogue_state,
    upsert_dialogue_state,
)
from app.services.recruitment_public import (
    RECRUITMENT_SITE_URL,
    list_public_recruitments,
)

# 与 DialogueMode.RECRUITMENT 一致的 mode 值；用于记忆用户筛选偏好
MODE_RECRUITMENT = "recruitment_query"

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

# 院系别名 → 规范院系名（子串匹配，命中即视为筛选条件）
DEPT_ALIASES: tuple[tuple[str, str], ...] = (
    ("计算机", "计算机科学与技术系"),
    ("自动化", "自动化系"),
    ("电子工程", "电子工程系"),
    ("电子系", "电子工程系"),
    ("电子", "电子工程系"),
    ("机械工程", "机械工程系"),
    ("机械", "机械工程系"),
    ("材料学院", "材料学院"),
    ("材料", "材料学院"),
    ("精密仪器", "精密仪器系"),
    ("精仪", "精密仪器系"),
)

# 招募类型关键词（子串匹配；"科研助理"优先于泛化的"助理"）
TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("科研助理", "科研助理"),
    ("研究助理", "科研助理"),
    ("科研岗", "科研助理"),
    ("实习", "实习"),
    ("博士后", "博士后"),
    ("博士", "博士"),
    ("硕士", "硕士"),
    ("本科生", "本科生"),
)

# 方向关键词：出现在 标题/专业要求/需求 中即视为相关（词面匹配，不做语义推断）
DIRECTION_KEYWORDS: tuple[str, ...] = (
    "大模型",
    "机器学习",
    "深度学习",
    "强化学习",
    "计算机视觉",
    "自然语言处理",
    "NLP",
    "语音",
    "机器人",
    "自动驾驶",
    "无人系统",
    "无人机",
    "芯片",
    "集成电路",
    "通信",
    "网络安全",
    "人工智能",
    "数据挖掘",
    "优化",
    "控制",
    "仿真",
    "嵌入式",
    "操作系统",
    "数据库",
    "材料",
    "生物",
    "化学",
    "物理",
    "新能源",
    "储能",
)

# 方向别名 → 规范方向（词面同义/缩写归一化，不做语义推断）。
# 用户输入与岗位文本双向映射到规范词后再匹配，让 "NLP" 与
# "自然语言处理"、"LLM" 与 "大模型" 等写法互相命中。
DIRECTION_ALIASES: tuple[tuple[str, str], ...] = (
    ("NLP", "自然语言处理"),
    ("nlp", "自然语言处理"),
    ("大语言模型", "大模型"),
    ("LLM", "大模型"),
    ("llm", "大模型"),
    ("ML", "机器学习"),
    ("RL", "强化学习"),
    ("神经网络", "深度学习"),
    ("深度神经网络", "深度学习"),
    ("视觉", "计算机视觉"),
    ("无人驾驶", "自动驾驶"),
    ("语音识别", "语音"),
    ("语音合成", "语音"),
    ("AI", "人工智能"),
)

URGENT_TERMS = ("急招", "急聘", "紧急", "尽快", "最近")
_APPLY_METHOD_EMPTY_HINTS = ("暂无", "未收录", "尚未提供")


def _normalize_direction(term: str) -> str:
    """把方向表述归一化为规范词（精确匹配别名表，不做语义推断）。"""
    stripped = (term or "").strip()
    for alias, canonical in DIRECTION_ALIASES:
        if stripped == alias:
            return canonical
    return stripped


def _substring_boundary(term: str, text: str) -> bool:
    """子串命中：纯英文缩写按词边界匹配（避免 "AI" 误命中 training）。"""
    if not term:
        return False
    if term.isascii() and term.isalpha():
        pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        return re.search(pattern, text) is not None
    return term in text


def _matches_direction(direction: str, haystack: str) -> bool:
    """方向是否命中岗位文本：方向归一到规范词后，同义词组内任一写法
    命中即可（"自然语言处理" 命中含 "NLP" 的岗位，反之亦然）。"""
    canonical = _normalize_direction(direction)
    aliases = {canonical}
    for alias, canon in DIRECTION_ALIASES:
        if canon == canonical:
            aliases.add(alias)
    for alias in sorted(aliases, key=len, reverse=True):
        if _substring_boundary(alias, haystack):
            return True
    return False


def parse_recruitment_filters(text: str) -> dict[str, Any]:
    """从一句自然语言解析招募筛选条件。

    例："计算机系最近的急招科研助理" →
    {"dept": "计算机科学与技术系", "type": "科研助理", "urgent": True,
     "direction": []}
    """
    filters: dict[str, Any] = {
        "dept": None,
        "type": None,
        "urgent": None,
        "direction": [],
    }
    if not text:
        return filters
    for alias, canonical in DEPT_ALIASES:
        if alias in text:
            filters["dept"] = canonical
            break
    for keyword, type_label in TYPE_KEYWORDS:
        if keyword in text:
            filters["type"] = type_label
            break
    if any(term in text for term in URGENT_TERMS):
        filters["urgent"] = True
    # 方向关键词提取（规范词 + 别名表写法都可触发），归一到规范词并去重
    extracted: list[str] = [kw for kw in DIRECTION_KEYWORDS if kw in text]
    for alias, _canonical in DIRECTION_ALIASES:
        if alias in text and alias not in extracted:
            extracted.append(alias)
    filters["direction"] = list(
        dict.fromkeys(_normalize_direction(kw) for kw in extracted)
    )
    return filters


def _record_haystack(record: dict[str, Any]) -> str:
    """招募记录的可检索文本：标题 + 专业要求 + 需求 + 标签。"""
    return (
        f"{record.get('title') or ''} {record.get('major') or ''} "
        f"{record.get('req') or ''} "
        f"{' '.join(record.get('tags') or [])}"
    )


def apply_recruitment_filters(
    records: list[dict[str, Any]],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """确定性过滤：全部命中条件才保留；无条件时原样返回。"""
    dept = filters.get("dept")
    type_label = filters.get("type")
    urgent = filters.get("urgent")
    directions = filters.get("direction") or []
    result: list[dict[str, Any]] = []
    for record in records:
        if dept and dept not in (record.get("dept") or ""):
            continue
        if type_label and type_label not in (record.get("type") or ""):
            continue
        if urgent is True and not record.get("is_urgent"):
            continue
        haystack = _record_haystack(record)
        if directions and not any(
            _matches_direction(direction, haystack) for direction in directions
        ):
            continue
        result.append(record)
    return result


def _deadline_text(record: dict[str, Any]) -> str:
    from datetime import date, datetime

    deadline = record.get("deadline")
    if isinstance(deadline, datetime):
        return deadline.date().isoformat()
    if isinstance(deadline, date):
        return deadline.isoformat()
    if deadline:
        return str(deadline)
    return "长期有效"


def _interest_matches(record: dict[str, Any], interests: list[str]) -> list[str]:
    """画像兴趣与岗位文本的命中方向（归一化为规范词，去重）。

    双向同义归一化：兴趣写 "NLP" 可命中含 "自然语言处理" 的岗位，反之亦然。
    """
    haystack = _record_haystack(record)
    matched: list[str] = []
    for tag in interests:
        if not tag:
            continue
        canonical = _normalize_direction(tag)
        if _matches_direction(canonical, haystack) and canonical not in matched:
            matched.append(canonical)
    return matched


def _recommendation_stars(matches: list[str]) -> str:
    """推荐指数：按画像兴趣命中数定级（1-5★），无命中不输出星级。"""
    if not matches:
        return ""
    stars = min(5, len(matches) + 1)
    return "★" * stars


def _sort_records(
    records: list[dict[str, Any]],
    *,
    interests: list[str],
    hard_constraints: list[str],
) -> list[dict[str, Any]]:
    """相关度排序：兴趣命中数 > 硬约束命中数 > 截止日期临近。"""

    def score(record: dict[str, Any]) -> tuple[int, int, str]:
        haystack = _record_haystack(record)
        interest_hits = sum(
            1 for tag in interests if tag and _matches_direction(tag, haystack)
        )
        constraint_hits = sum(
            1 for constraint in hard_constraints if constraint and constraint in haystack
        )
        return (interest_hits + constraint_hits, interest_hits, _deadline_text(record))

    return sorted(records, key=score, reverse=True)


def format_recruitment_digest_v25(
    records: list[dict[str, Any]],
    *,
    profile: StudentPortrait | None,
    filters: dict[str, Any],
    limit: int = 3,
) -> str:
    """v2.5 招募输出格式：标题 / 发布方|类型|截止|急招 / 核心要求 /
    投递说明 / 推荐理由与推荐指数。

    无记录、无画像、筛选后为空三种诚实空态与普通结果分开表达。
    """
    if not records:
        return (
            "暂无通过审核且仍在招期内的招募信息。投稿在审核通过后会出现在"
            f"这里；你也可以在网站查看与投递 👉 {RECRUITMENT_SITE_URL}"
        )
    interests = list(getattr(profile, "research_interests", None) or [])
    constraints = [
        item.get("constraint") or str(item)
        for item in (getattr(profile, "hard_constraints", None) or [])
    ]
    ranked = _sort_records(records, interests=interests, hard_constraints=constraints)
    selected = ranked[: max(1, limit)]
    active = {key: value for key, value in filters.items() if value}
    active_lines = []
    if active.get("dept"):
        active_lines.append(f"院系：{active['dept']}")
    if active.get("type"):
        active_lines.append(f"类型：{active['type']}")
    if active.get("urgent"):
        active_lines.append("急招")
    if active.get("direction"):
        active_lines.append(f"方向：{'、'.join(active['direction'])}")
    scope_text = f"，当前筛选条件：{'、'.join(active_lines)}" if active_lines else ""

    header = (
        f"📢 共 {len(records)} 条通过审核且在招的招募信息{scope_text}，"
        f"取相关度前 {len(selected)} 条："
    )
    lines: list[str] = [header]
    personalized = False
    for index, record in enumerate(selected, start=1):
        urgent = "[急招] " if record.get("is_urgent") else ""
        publisher = record.get("publisher_name") or "经审核发布者"
        type_label = record.get("type") or "招募"
        dept = record.get("dept") or ""
        dept_suffix = f" · {dept}" if dept else ""
        lines.append(
            f"\n{index}. {urgent}{record.get('title') or '未命名招募'}"
            f"（{publisher}{dept_suffix}）"
        )
        lines.append(
            f"   {type_label} | 截止 {_deadline_text(record)}"
        )
        req = (record.get("req") or "").strip()
        if req:
            summary = _shorten_requirement(req)
            lines.append(f"   核心要求：{summary}")
        apply_method = (record.get("apply_method") or "").strip()
        if apply_method and not any(
            hint in apply_method for hint in _APPLY_METHOD_EMPTY_HINTS
        ):
            lines.append(f"   投递说明：{apply_method}")
        else:
            lines.append(
                "   投递说明：该信息暂未收录，建议通过导师官网或官方邮箱"
                "核实具体投递方式"
            )
        matches = _interest_matches(record, interests)
        stars = _recommendation_stars(matches)
        if matches:
            personalized = True
            lines.append(
                f"   推荐理由：与你的研究方向「{'、'.join(matches)}」重合"
                f"（推荐指数 {stars}）"
            )
    if not personalized and interests:
        lines.append("")
        lines.append(
            "当前无与你的研究兴趣直接重合的在招岗位，以上为按截止时间排序的"
            "公开信息，供参考。"
        )
    lines.append("")
    lines.append(f"浏览全部、查看详情与站内投递 👉 {RECRUITMENT_SITE_URL}")
    lines.append(
        "需要的话，我可以帮你把简历调整成适配其中某条岗位——告诉我岗位序号"
        "或直接说「针对 XX 优化简历」。"
    )
    return "\n".join(lines)


def _shorten_requirement(req: str, *, limit: int = 90) -> str:
    """核心要求摘要：压到单行，不截断中文语义（按标点分段取前段）。"""
    cleaned = re.sub(r"\s+", " ", req).strip()
    if len(cleaned) <= limit:
        return cleaned
    head = cleaned[: limit + 1]
    cut = max(head.rfind("，"), head.rfind("；"), head.rfind("。"), head.rfind(","))
    if cut > limit // 2:
        return head[:cut] + "…"
    return cleaned[:limit] + "…"


def _is_vague_query(filters: dict[str, Any]) -> bool:
    """宽泛问题判定：没有任何可用的筛选条件（院系/类型/急招/方向）。"""
    return not any(filters.get(key) for key in ("dept", "type", "urgent", "direction"))


def _parse_ordinal(text: str) -> int | None:
    """解析「第 N 个」序号（阿拉伯数字 / 中文数字 / 第一…第十）；未命中 None。"""
    match = re.search(r"第\s*([一二两三四五六七八九十\d]+)\s*个", text or "")
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if "十" in raw:
        head, _, tail = raw.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0)
        return tens * 10 + ones
    return _CN_DIGITS.get(raw)


# 详情追问语气词：与序号组合判定"想看岗位详情"；优化/投递意图不在此列
_DETAIL_INTENT_WORDS = (
    "详情",
    "怎么样",
    "怎样",
    "展开",
    "细说",
    "介绍",
    "是什么",
    "看看",
    "有啥",
    "有什么",
)


def _is_detail_query(text: str) -> bool:
    """详情追问判定：「第 N 个」且不含优化/投递语义，或序号 + 语气词。

    防御性排除优化意图（正常会被 RESUME_TARGETED 拦截，双保险）。
    """
    text = text or ""
    if any(term in text for term in ("优化", "润色", "打磨", "改简历", "投递", "针对")):
        return False
    if _parse_ordinal(text) is not None:
        return True
    return False


def _deadline_remaining(record: dict[str, Any]) -> str | None:
    """距截止剩余描述；无明确截止返回 None（不编造日期）。"""
    from datetime import date, datetime

    now = date.today()
    deadline = record.get("deadline")
    if isinstance(deadline, datetime):
        target = deadline.date()
    elif isinstance(deadline, date):
        target = deadline
    else:
        return None
    delta = (target - now).days
    if delta < 0:
        return "已截止"
    if delta == 0:
        return "今天截止"
    if delta <= 7:
        return f"距截止还有 {delta} 天（临近）"
    return f"距截止还有 {delta} 天"


def format_recruitment_detail_v25(
    record: dict[str, Any],
    *,
    ordinal: int | None,
    profile: StudentPortrait | None,
) -> str:
    """单条岗位完整详情：标题/发布方·院系/类型/截止倒计时/急招/核心要求/
    投递说明/推荐理由；末尾引导定向优化简历。"""
    urgent = "[急招] " if record.get("is_urgent") else ""
    publisher = record.get("publisher_name") or "经审核发布者"
    dept = record.get("dept") or ""
    dept_suffix = f" · {dept}" if dept else ""
    title = record.get("title") or "未命名招募"
    lines = [
        f"{ordinal}. {urgent}{title}（{publisher}{dept_suffix}）",
        f"   {record.get('type') or '招募'} | 截止 {_deadline_text(record)}",
    ]
    remaining = _deadline_remaining(record)
    if remaining:
        lines.append(f"   ⏳ {remaining}")
    req = (record.get("req") or "").strip()
    if req:
        lines.append(f"   核心要求：{req}")
    major = (record.get("major") or "").strip()
    if major:
        lines.append(f"   专业方向：{major}")
    apply_method = (record.get("apply_method") or "").strip()
    if apply_method and not any(
        hint in apply_method for hint in _APPLY_METHOD_EMPTY_HINTS
    ):
        lines.append(f"   投递说明：{apply_method}")
    else:
        lines.append(
            "   投递说明：该信息暂未收录，建议通过导师官网或官方邮箱"
            "核实具体投递方式"
        )
    interests = list(getattr(profile, "research_interests", None) or [])
    matches = _interest_matches(record, interests)
    if matches:
        stars = _recommendation_stars(matches)
        lines.append(
            f"   推荐理由：与你的研究方向「{'、'.join(matches)}」重合"
            f"（推荐指数 {stars}）"
        )
    lines.append("")
    lines.append(f"浏览全部、查看详情与站内投递 👉 {RECRUITMENT_SITE_URL}")
    lines.append(
        "想针对这个岗位优化简历？回复「针对第 1 个优化简历」"
        "（或直接说出岗位名）。"
    )
    return "\n".join(lines)


def resolve_recruitment_target(
    db: Session,
    target: str,
    *,
    interests: list[str] | None = None,
) -> dict[str, Any] | None:
    """把用户目标解析为一条公开招募记录（供简历定向优化联动）。

    解析顺序：序号（第 N 个，按 digest 同口径排序取第 N 条）→ recruit_id
    前缀 → 标题子串。无命中返回 None（调用方按普通目标名处理，不报错）。
    """
    if not (target or "").strip():
        return None
    records, _withheld = list_public_recruitments(db)
    if not records:
        return None
    ordinal = _parse_ordinal(target)
    if ordinal is not None:
        ranked = _sort_records(
            records,
            interests=interests or [],
            hard_constraints=[],
        )
        if 1 <= ordinal <= len(ranked):
            return ranked[ordinal - 1]
    text = target.strip()
    for record in records:
        if (record.get("recruit_id") or "").lower() == text.lower():
            return record
    for record in records:
        if text in (record.get("title") or "") or text in _record_haystack(record):
            return record
    return None


def _vague_guidance(profile: StudentPortrait | None) -> str:
    """宽泛查询时的引导：有画像按兴趣排序说明，无画像给出筛选引导。"""
    interests = list(getattr(profile, "research_interests", None) or [])
    if interests:
        return (
            "你还没有指定院系、类型或方向，我按你的研究兴趣（"
            f"{'、'.join(interests[:5])}）为你做了相关度排序。"
            "也可以告诉我院系（如计算机系）、类型（如科研助理 / 实习 / "
            "博士后）或方向（如大模型、计算机视觉）进一步缩小范围。\n\n"
        )
    return (
        "你还没有指定筛选条件，以下是当前最新在招岗位概览。"
        "告诉我你的研究兴趣或想要的方向（如大模型、计算机视觉）、院系、"
        "类型，我可以帮你精准筛选。\n\n"
    )


def _save_filter_memo(
    db: Session,
    *,
    session_id: str | None,
    student_id: str | None,
    filters: dict[str, Any],
) -> None:
    """记住用户明确说过的筛选条件（dialogue_sessions 持久化）。"""
    if not session_id or not student_id:
        return
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_RECRUITMENT,
        state={"filters": filters},
    )


def _load_filter_memo(
    db: Session,
    *,
    session_id: str | None,
    student_id: str | None,
) -> dict[str, Any] | None:
    """读取本会话记住的筛选条件；无记忆返回 None。"""
    if not session_id or not student_id:
        return None
    if (
        get_dialogue_mode(db, session_id=session_id, student_id=student_id)
        != MODE_RECRUITMENT
    ):
        return None
    state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
    if state is None:
        return None
    remembered = state.get("filters") or {}
    if not isinstance(remembered, dict) or _is_vague_query(remembered):
        return None
    return remembered


def _memo_scope_text(filters: dict[str, Any]) -> str:
    """把记住的条件转成展示文本（"计算机系 · 科研助理"）。"""
    parts = []
    if filters.get("dept"):
        parts.append(f"院系 {filters['dept']}")
    if filters.get("type"):
        parts.append(f"类型 {filters['type']}")
    if filters.get("urgent"):
        parts.append("急招")
    if filters.get("direction"):
        parts.append(f"方向 {'、'.join(filters['direction'])}")
    return "、".join(parts)


async def handle_recruitment_query(
    db: Session,
    *,
    latest_user: str,
    portrait: StudentPortrait | None,
    session_id: str | None = None,
    student_id: str | None = None,
) -> tuple[str, Any]:
    """招募查询入口：详情追问 / 语义筛选 / 宽泛问题与偏好记忆。

    - 详情追问（"第 1 个"）→ 单条完整详情（含距截止天数）；
    - 有明确筛选条件 → 正常筛选并记住该条件（同会话复用）；
    - 宽泛问题 → 优先沿用记住的条件，其次按画像兴趣推荐 + 引导；
    - 无在招记录保持诚实空态。
    """
    # 详情追问：优先级最高（"第 1 个"是对话上下文里的岗位指代）
    if _is_detail_query(latest_user):
        records, _withheld = list_public_recruitments(db)
        ordinal = _parse_ordinal(latest_user)
        if ordinal is not None:
            interests = list(getattr(portrait, "research_interests", None) or [])
            ranked = _sort_records(records, interests=interests, hard_constraints=[])
            if 1 <= ordinal <= len(ranked):
                return format_recruitment_detail_v25(
                    ranked[ordinal - 1],
                    ordinal=ordinal,
                    profile=portrait,
                ), None
        return (
            "没找到对应的在招岗位。可以回复序号（如「第 1 个」）查看详情，"
            "或描述岗位名 / 筛选条件。"
        ), None

    filters = parse_recruitment_filters(latest_user)
    records, _withheld = list_public_recruitments(db)
    has_explicit = not _is_vague_query(filters)
    if has_explicit:
        _save_filter_memo(db, session_id=session_id, student_id=student_id, filters=filters)
    else:
        remembered = _load_filter_memo(
            db, session_id=session_id, student_id=student_id
        )
        if remembered is not None:
            filters = dict(remembered)
            memo_note = (
                "我沿用你之前提到的筛选条件（"
                f"{_memo_scope_text(remembered)}）为你筛选；"
                "想看全部可告诉我新的条件。\n\n"
            )
            filtered = apply_recruitment_filters(records, filters)
            digest = format_recruitment_digest_v25(
                filtered, profile=portrait, filters=filters
            )
            return memo_note + digest, None
    filtered = apply_recruitment_filters(records, filters)
    digest = format_recruitment_digest_v25(
        filtered,
        profile=portrait,
        filters=filters,
    )
    if _is_vague_query(filters) and filtered:
        return _vague_guidance(portrait) + digest, None
    return digest, None
