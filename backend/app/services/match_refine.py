"""匹配结果二次筛选：换一批 / 缩小范围 / 恢复完整结果（v3.1.7）。

设计动机：学习竞品"清研向导"匹配后的结构化二次筛选（换一批、缩小范围
结构化追问→重筛），用确定性硬约束实现，不依赖 LLM：
- 换一批：把已展示候选并入排除集，重跑同一画像匹配；
- 缩小范围：两问（聚焦方向 / 排除方向）→ RESEARCH_TOPIC 硬约束过滤；
- 恢复完整结果：清空二次筛选状态，重跑全量。

诚实性红线：
- 过滤完全确定性，归零时输出 match 层 zero_result_reason 原文并提示恢复，
  绝不编造候选；
- 过滤态与最近展示批次存 dialogue_sessions.state，保证「换一批」后
  「第 N 个 / 雷达图 / 套磁」追问与二次筛选结果一致；
- 首次匹配（无已展示批次）时「换一批」诚实说明无法排除。
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.services.dialogue_state_store import (
    clear_dialogue_state,
    get_dialogue_mode,
    get_dialogue_state,
    upsert_dialogue_state,
)
from app.services.match_application import run_confirmed_match

MODE_MATCH_REFINE = "match_refine"

# 触发词（子串匹配；均在 recommend_ready 上下文生效，不影响访谈）
_REFINE_TRIGGERS = (
    "换一批",
    "换些",
    "换几个",
    "再换",
    "还有别的",
    "别的导师",
    "再筛",
    "缩小范围",
    "缩小下范围",
    "收窄",
)

# 其中"缩小范围"类（进入两问状态机；其余为"换一批"类，立即重跑）
_REFINE_NARROW_TRIGGERS = (
    "缩小范围",
    "缩小下范围",
    "收窄",
    "再筛",
)

# 恢复全量（清空排除集与方向过滤）
_REFINE_RESET = (
    "恢复完整结果",
    "恢复全部",
    "重置筛选",
    "取消筛选",
    "看全部",
    "全部结果",
)

# 取消（仅取消未答完的筛选问题，保留已生效的筛选条件）
_REFINE_CANCEL = ("取消", "退出", "不筛了", "算了")

# 答题步骤
_STEP_INCLUDE = "include"  # 待回答：聚焦方向
_STEP_EXCLUDE = "exclude"  # 待回答：排除方向

# 聚焦/排除答案的"无"表达（跳过该过滤）
_NONE_TERMS = ("无", "没有", "不需要", "都可以", "随便", "跳过")


def parse_topic_answer(text: str) -> list[str]:
    """把筛选答案拆成方向/技术词（去空、去"无"、去重；确定性）。

    例："大模型、多模态" → ["大模型", "多模态"]；"无" → []（跳过）。
    """
    tokens: list[str] = []
    for part in re.split(r"[、，,;；/\s]+", (text or "").strip()):
        token = (part or "").strip()
        if not token or token in _NONE_TERMS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def build_refine_constraints(
    excluded_advisor_ids: Sequence[str],
    topic_include: Sequence[str],
    topic_exclude: Sequence[str],
) -> list[dict[str, Any]]:
    """二次筛选 → 附加硬约束（matching 层原生支持，零改动复用）。

    ADVISOR_ID EXCLUDES（换一批排除已展示）；RESEARCH_TOPIC
    CONTAINS/EXCLUDES（缩小范围聚焦/排除方向）。无对应条件不出约束。
    """
    constraints: list[dict[str, Any]] = []
    excluded: list[str] = []
    for raw in excluded_advisor_ids or ():
        value = str(raw).strip()
        if value and value not in excluded:
            excluded.append(value)
    if excluded:
        constraints.append(
            {
                "field": "advisor_id",
                "operator": "excludes",
                "value": excluded,
                "source_text": "二次筛选：换一批（排除已展示候选）",
            }
        )
    include = list(dict.fromkeys(topic_include or []))
    if include:
        constraints.append(
            {
                "field": "research_topic",
                "operator": "contains",
                "value": include,
                "source_text": "二次筛选：缩小范围（聚焦方向）",
            }
        )
    exclude_topics = list(dict.fromkeys(topic_exclude or []))
    if exclude_topics:
        constraints.append(
            {
                "field": "research_topic",
                "operator": "excludes",
                "value": exclude_topics,
                "source_text": "二次筛选：缩小范围（排除方向）",
            }
        )
    return constraints


def _read_state(db: Session, *, session_id: str, student_id: str) -> dict[str, Any]:
    return dict(get_dialogue_state(db, session_id=session_id, student_id=student_id) or {})


def persisted_refine_constraints(
    db: Session,
    *,
    session_id: str,
    student_id: str,
) -> list[dict[str, Any]]:
    """读取已持久化的二次筛选条件 → 附加硬约束（供 chat.py 基础重跑）。

    基础重跑（「第 N 个」/「雷达图」等）必须与二次筛选批次一致：
    换一批后的排除集与缩小范围的方向过滤在此统一生效。
    """
    state = _read_state(db, session_id=session_id, student_id=student_id)
    return build_refine_constraints(
        state.get("excluded_advisor_ids") or [],
        state.get("topic_include") or [],
        state.get("topic_exclude") or [],
    )


def persist_shown_batch(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    items: Sequence[dict[str, Any]],
) -> None:
    """记录最近一次渲染的候选批（供「换一批」排除）。

    有已匹配项才写入；保留既有排除集/方向过滤/答题态，只更新
    last_shown_advisor_ids。无状态行时创建（首次基础匹配即记录批次）；
    其它对话模式进行中不抢占（避免覆盖科研风格等跨轮状态）。
    """
    shown = [
        str(item.get("advisor_id")).strip()
        for item in items or ()
        if item.get("advisor_id")
    ]
    if not shown:
        return
    existing_mode = get_dialogue_mode(db, session_id=session_id, student_id=student_id)
    if existing_mode not in (None, MODE_MATCH_REFINE):
        return
    state = _read_state(db, session_id=session_id, student_id=student_id)
    state["last_shown_advisor_ids"] = list(dict.fromkeys(shown))
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_MATCH_REFINE,
        state=state,
    )


def _refine_questions() -> tuple[str, str]:
    """Q1（聚焦方向）与 Q2（排除方向）题干文本。"""
    q1 = (
        "好的，来缩小范围。先告诉我：你希望候选集中在哪些方向或技术上？\n"
        "可以列 1~3 个（如「大模型、多模态」）；没有就回复「无」。"
    )
    q2 = (
        "收到。还有想排除的方向或技术吗？\n"
        "列出来会从结果中过滤掉；没有就回复「无」。"
    )
    return q1, q2


def render_refined_outcome(
    db: Session,
    outcome,
    *,
    session_id: str,
    student_id: str,
) -> str:
    """与 chat.py 基础重跑同口径渲染（画像/评分/隐式维度一致）。"""
    from app.services.advisor_rating import get_gated_summary
    from app.services.dialogue_intent import detect_implicit_dimension_attention
    from app.services.interview import (
        InterviewAccessError,
        InterviewConflictError,
        InterviewNotFoundError,
    )
    from app.services.match_application import (
        derive_user_dimension_scores,
        format_match_outcome,
    )

    portrait = None
    try:
        from app.services.interview import confirmed_portrait

        portrait = confirmed_portrait(
            db, session_id=session_id, student_id=student_id
        )
    except (InterviewNotFoundError, InterviewAccessError, InterviewConflictError):
        portrait = None
    ratings: dict[str, dict] = {}
    for item in outcome.items or []:
        advisor_id = str(item.get("advisor_id") or "")
        if not advisor_id:
            continue
        gated = get_gated_summary(db, advisor_id)
        if gated is not None:
            ratings[advisor_id] = gated
    user_scores = derive_user_dimension_scores(
        portrait,
        implicit_dimensions=detect_implicit_dimension_attention([]),
    )
    return format_match_outcome(
        outcome,
        profile=portrait,
        advisor_ratings=ratings,
        user_dimension_scores=user_scores,
    )


def _run_refined(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    excluded: Sequence[str],
    topic_include: Sequence[str],
    topic_exclude: Sequence[str],
    preamble: str,
) -> str:
    """以当前二次筛选条件重跑匹配并渲染（确定性；归零走 zero_result_reason）。"""
    outcome = run_confirmed_match(
        db,
        session_id=session_id,
        student_id=student_id,
        extra_constraints=build_refine_constraints(
            excluded, topic_include, topic_exclude
        ),
    )
    # 记录本批（后续「换一批」继续排除；「第 N 个」基础重跑批次一致）
    persist_shown_batch(
        db, session_id=session_id, student_id=student_id, items=outcome.items
    )
    if outcome.status != "matched":
        return (
            f"{preamble}\n\n{outcome.message}\n\n"
            "可以回复「恢复完整结果」回到全量结果，"
            "或「缩小范围」重新设置筛选条件。"
        )
    text = render_refined_outcome(
        db, outcome, session_id=session_id, student_id=student_id
    )
    return (
        f"{preamble}\n\n{text}\n\n"
        "可以继续：\n"
        "- 「第 N 个」查看候选详情\n"
        "- 「换一批」再换一组候选\n"
        "- 「缩小范围」按方向进一步筛选\n"
        "- 「恢复完整结果」回到全量结果"
    )


def _start_refine(
    db: Session,
    *,
    text: str,
    session_id: str,
    student_id: str,
    state: dict[str, Any] | None = None,
) -> str:
    """冷启动或重触发：按指令进入换一批 / 缩小范围。"""
    state = dict(state or _read_state(db, session_id=session_id, student_id=student_id))
    last_shown = [
        str(item)
        for item in (state.get("last_shown_advisor_ids") or [])
        if str(item)
    ]
    excluded: list[str] = []
    for raw in [*(state.get("excluded_advisor_ids") or []), *last_shown]:
        value = str(raw).strip()
        if value and value not in excluded:
            excluded.append(value)

    if any(term in text for term in _REFINE_NARROW_TRIGGERS):
        # 缩小范围：保存排除集，进入两问状态机
        state["excluded_advisor_ids"] = excluded
        state["step"] = _STEP_INCLUDE
        upsert_dialogue_state(
            db,
            session_id=session_id,
            student_id=student_id,
            mode=MODE_MATCH_REFINE,
            state=state,
        )
        return _refine_questions()[0]

    # 换一批：立即排除已展示候选并重跑
    state["excluded_advisor_ids"] = excluded
    state["step"] = None
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_MATCH_REFINE,
        state=state,
    )
    if not last_shown and not excluded:
        return (
            "本轮还没有已展示的候选可排除；可以先回复「缩小范围」设置"
            "方向筛选，或「第 N 个」查看当前候选详情。"
        )
    return _run_refined(
        db,
        session_id=session_id,
        student_id=student_id,
        excluded=excluded,
        topic_include=state.get("topic_include") or [],
        topic_exclude=state.get("topic_exclude") or [],
        preamble=f"已排除已展示的 {len(last_shown)} 位候选后重新匹配：",
    )


def handle_match_refine(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
    structural_match: bool = False,
) -> str | None:
    """二次筛选多轮入口（状态存 dialogue_sessions）。

    返回 None 表示本消息不属于二次筛选（释放回 recommend_ready 主流程，
    由 chat.py 走基础重跑 + 序号/雷达等追问）；返回文本表示已消费。
    仅在 chat.py 的 recommend_ready 上下文调用，不注册全局对话模式。
    """
    text = (latest_user or "").strip()
    mode = get_dialogue_mode(db, session_id=session_id, student_id=student_id)
    if mode != MODE_MATCH_REFINE:
        # 冷启动：仅触发词进入；否则释放
        if not any(term in text for term in _REFINE_TRIGGERS):
            return None
        return _start_refine(
            db, text=text, session_id=session_id, student_id=student_id
        )

    state = _read_state(db, session_id=session_id, student_id=student_id)
    step = state.get("step")

    # 恢复全量（先于"取消"判定，避免"取消筛选"被当成取消答题）
    if any(term in text for term in _REFINE_RESET):
        clear_dialogue_state(db, session_id=session_id, student_id=student_id)
        return _run_refined(
            db,
            session_id=session_id,
            student_id=student_id,
            excluded=[],
            topic_include=[],
            topic_exclude=[],
            preamble="已恢复完整结果（清空二次筛选条件后重新匹配）：",
        )

    # 答题进行中：取消 / 重触发 / 结构指令 / 作答
    if step in (_STEP_INCLUDE, _STEP_EXCLUDE):
        if any(term in text for term in _REFINE_CANCEL):
            state["step"] = None
            upsert_dialogue_state(
                db,
                session_id=session_id,
                student_id=student_id,
                mode=MODE_MATCH_REFINE,
                state=state,
            )
            return (
                "已退出二次筛选设置；当前已生效的筛选条件保持不变。\n"
                "可以回复「第 N 个」查看详情、「换一批」继续排除，"
                "或「恢复完整结果」回到全量。"
            )
        if any(term in text for term in _REFINE_TRIGGERS):
            # 答题中改主意：按新指令重新开始
            return _start_refine(
                db,
                text=text,
                session_id=session_id,
                student_id=student_id,
                state=state,
            )
        if structural_match:
            # 序号/雷达/招募/报告等结构指令 → 放弃未答完的问题，释放
            state["step"] = None
            upsert_dialogue_state(
                db,
                session_id=session_id,
                student_id=student_id,
                mode=MODE_MATCH_REFINE,
                state=state,
            )
            return None
        answer = parse_topic_answer(text)
        if step == _STEP_INCLUDE:
            state["topic_include"] = answer
            state["step"] = _STEP_EXCLUDE
            upsert_dialogue_state(
                db,
                session_id=session_id,
                student_id=student_id,
                mode=MODE_MATCH_REFINE,
                state=state,
            )
            return _refine_questions()[1]
        # step == exclude：完成 → 按两问答案重跑
        state["topic_exclude"] = answer
        state["step"] = None
        upsert_dialogue_state(
            db,
            session_id=session_id,
            student_id=student_id,
            mode=MODE_MATCH_REFINE,
            state=state,
        )
        return _run_refined(
            db,
            session_id=session_id,
            student_id=student_id,
            excluded=state.get("excluded_advisor_ids") or [],
            topic_include=state.get("topic_include") or [],
            topic_exclude=answer,
            preamble="已按你的筛选条件重新匹配：",
        )

    # 非答题态：换一批 / 缩小范围 触发 → 排除已展示后重跑 / 进入问答
    if any(term in text for term in _REFINE_TRIGGERS):
        return _start_refine(
            db,
            text=text,
            session_id=session_id,
            student_id=student_id,
            state=state,
        )
    return None
