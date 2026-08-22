"""Web 与清小搭共用的 A4 匹配应用服务。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from sqlalchemy.orm import Session

from app.schemas.interview import HardConstraint, StudentPortrait
from app.schemas.matching import RankingConfig
from app.services.data_loader import (
    load_match_candidates,
    mentor_data_summary,
)
from app.services.interview import confirmed_portrait
from app.services.matching import match_mentors

logger = logging.getLogger("tsing_radar.match_application")


@dataclass(frozen=True)
class MatchApplicationOutcome:
    status: Literal[
        "matched",
        "no_published_data",
        "no_match",
        "needs_clarification",
    ]
    items: list[dict[str, Any]]
    meta: dict[str, Any]
    message: str
    questions: list[str]


def run_confirmed_match(
    db: Session,
    *,
    session_id: str,
    student_id: str | None,
    ranking: RankingConfig | None = None,
    extra_constraints: Sequence[dict[str, Any] | HardConstraint] | None = None,
    relax_hard_constraints: bool = False,
    extra_topic_tags: Sequence[str] | None = None,
) -> MatchApplicationOutcome:
    """读取已确认服务端画像并执行唯一一套匹配流水线。

    v3.1.7：extra_constraints 为二次筛选附加硬约束（换一批排除已展示 /
    缩小范围按方向过滤），合并进画像 hard_constraints 后走同一套
    match_mentors 硬过滤；约束合法性由 matching 层校验，非法 fail-closed。
    v4.2.x 修复8：relax_hard_constraints=「放宽」指令，本次重跑忽略已确认
    硬性条件（画像本身不改写）；extra_topic_tags=「换方向：XXX」单次主题
    覆盖（合并进召回词，不改写画像）。
    """
    portrait = confirmed_portrait(
        db,
        session_id=session_id,
        student_id=student_id,
    )
    payload = portrait.model_dump(mode="json")
    if relax_hard_constraints:
        logger.info("relax_hard_constraints_rerun session=%s", session_id)
        payload["hard_constraints"] = []
        payload["draft_hard_constraints"] = []
        payload["unresolved_hard_constraints"] = []
    elif len(payload.get("hard_constraints") or []) > 3:
        # v4.2.x 修复1 第二层：已确认硬约束超过 3 条视为画像污染/过载，
        # 整批忽略并降级为软条件（访谈层已挡 90%+，这里是旧数据兜底；
        # 若因此扩大召回，空态兜底卡会引导用户检查/放宽）。
        logger.warning(
            "hard_constraint_overload_dropped session=%s count=%d",
            session_id,
            len(payload.get("hard_constraints") or []),
        )
        payload["hard_constraints"] = []
    if extra_topic_tags:
        merged_topics = list(payload.get("research_interests") or [])
        for tag in extra_topic_tags:
            tag = str(tag).strip()
            if tag and tag not in merged_topics:
                merged_topics.append(tag)
        payload["research_interests"] = merged_topics[:8]
    if extra_constraints:
        merged = list(payload.get("hard_constraints") or [])
        for constraint in extra_constraints:
            merged.append(
                constraint.model_dump(mode="json")
                if isinstance(constraint, HardConstraint)
                else constraint
            )
        payload["hard_constraints"] = merged
    candidates = load_match_candidates()
    result = match_mentors(
        mentors=candidates,
        portrait=payload,
        config=ranking,
    )
    meta = {
        **mentor_data_summary(),
        "interview_status": "confirmed",
        "matching": result.meta,
    }
    if result.meta["status"] == "needs_clarification":
        questions = result.meta["clarification_questions"]
        return MatchApplicationOutcome(
            status="needs_clarification",
            items=[],
            meta=meta,
            message="硬约束仍需由你确认成结构化条件，暂不执行匹配。",
            questions=questions,
        )
    if meta["match_candidate_records"] == 0:
        return MatchApplicationOutcome(
            status="no_published_data",
            items=[],
            meta=meta,
            message=(
                "暂无通过审核的数据可作为正式推荐导师画像，因此现在不能"
                "诚实地产生导师推荐。目录资源可检索，但不会冒充导师画像。"
            ),
            questions=[],
        )
    if not result.items:
        zero_reason = result.meta.get("zero_result_reason")
        return MatchApplicationOutcome(
            status="no_match",
            items=[],
            meta=meta,
            message=zero_reason or (
                "已有发布数据，但当前没有同时通过硬约束和召回阈值的候选。"
            ),
            questions=[
                "请检查导致归零的硬约束；如该条件可以放宽，可编辑画像后重新确认。"
                if zero_reason
                else "是否要检查已确认的硬约束或调整召回阈值？"
            ],
        )
    return MatchApplicationOutcome(
        status="matched",
        items=result.items,
        meta=meta,
        message=f"基于已确认画像找到 {len(result.items)} 个证据化候选。",
        questions=[],
    )


def derive_reply_tone(profile: StudentPortrait | None) -> str:
    """从已确认画像推导推荐文案语气档位（纯映射，确定性）。

    语气只改"怎么说"，不改"说什么"——三档输出的分数与事实必须逐字一致。
    """
    if profile is None:
        return "balanced"
    career = getattr(profile, "career_orientation", None)
    risk = getattr(profile, "innovation_risk", None)
    if career == "industry" or risk == "mature":
        return "pragmatic"
    if career == "academic" and risk == "pioneering":
        return "exploratory"
    return "balanced"


_TONE_OPENINGS = {
    "pragmatic": "按你确认的画像筛了一轮，先看关键数字：",
    "exploratory": "结合你确认的研究方向与探索偏好，这几位候选与你的重合度最高：",
    "balanced": "基于你确认的画像，找到以下证据化候选：",
}

_TONE_FIT_LABELS = {
    "pragmatic": "匹配点",
    "exploratory": "契合点",
    "balanced": "为什么适合你",
}

_TONE_CLOSINGS = {
    "pragmatic": (
        "建议下一步：优先核实产出节奏与毕业安排，再决定是否约谈。"
    ),
    "exploratory": (
        "建议下一步：带着你的研究设想与导师聊聊方向重合度，"
        "同时核实下方「需要注意」里标注的未覆盖维度。"
    ),
    "balanced": "建议下一步：先核实各候选「需要注意」中的不确定项，再约谈。",
}

_SITE_DEEP_LINK = "完整对比、交互雷达图与证据面板 👉 https://www.tsingradar.com.cn"


def derive_user_dimension_scores(
    profile: StudentPortrait | None,
    *,
    implicit_dimensions: Sequence[str] = (),
) -> dict[str, float]:
    """从画像推导用户六维需求分（0-100），输出标注「需求映射」。

    这是对访谈画像的确定性、保守映射，只对语义明确的画像字段生效，
    不参与排序计算，仅用于匹配输出的解释层；隐式关注维度（口语映射）
    以较低默认分补充，且全部在输出中标注来源。
    """
    from app.services.constants import TRAIT_KEYS
    from app.services.dialogue_intent import (
        DIMENSION_ACUMEN,
        DIMENSION_EFFICIENCY,
        DIMENSION_MENTORSHIP,
    )

    scores: dict[str, float] = {}
    if profile is None:
        return scores
    style = getattr(profile, "mentorship_style", None)
    if style == "high_guidance":
        scores[DIMENSION_MENTORSHIP] = max(scores.get(DIMENSION_MENTORSHIP, 0.0), 85.0)
    elif style == "balanced":
        scores[DIMENSION_MENTORSHIP] = max(scores.get(DIMENSION_MENTORSHIP, 0.0), 60.0)
    elif style == "autonomous":
        scores[DIMENSION_MENTORSHIP] = max(scores.get(DIMENSION_MENTORSHIP, 0.0), 35.0)
    risk = getattr(profile, "innovation_risk", None)
    if risk == "pioneering":
        scores[DIMENSION_ACUMEN] = max(scores.get(DIMENSION_ACUMEN, 0.0), 80.0)
    elif risk == "mature":
        scores[DIMENSION_EFFICIENCY] = max(scores.get(DIMENSION_EFFICIENCY, 0.0), 80.0)
    mode = getattr(profile, "research_mode", None)
    if mode == "theory":
        scores[DIMENSION_ACUMEN] = max(scores.get(DIMENSION_ACUMEN, 0.0), 70.0)
    elif mode == "engineering":
        scores[DIMENSION_EFFICIENCY] = max(scores.get(DIMENSION_EFFICIENCY, 0.0), 70.0)
    for dimension in implicit_dimensions or ():
        if dimension in TRAIT_KEYS:
            scores[dimension] = max(scores.get(dimension, 0.0), 75.0)
    return scores


def _research_direction(item: dict) -> str | None:
    """从匹配候选中提取已审核的核心研究方向文本（无数据返回 None，诚实省略）。"""
    for key in ("research_summary", "research_keywords", "field", "tags"):
        value = item.get(key)
        if isinstance(value, list):
            value = "、".join(str(part) for part in value if str(part).strip())
        if value and str(value).strip():
            text = str(value).strip()
            return text[:120] + ("…" if len(text) > 120 else "")
    return None


def format_gap_analysis(
    item: dict[str, Any],
    profile: StudentPortrait | None,
) -> str | None:
    """能力差距分析（对标清研向导「需要补充的知识或技能」，v3.1.7）。

    候选方向（research_keywords 优先，其次核心研究方向文本）→ 公开学科
    入门知识点；与学生画像兴趣做词面归一化比对（复用方向别名解析），
    输出「已具备/需要补充」。诚实性：
    - 只列学科常识，绝不出现教师名；
    - 画像无证据 → 明确标注「暂无画像证据」；
    - 方向无知识映射 → 返回 None（调用方省略该块，不编造内容）。
    """
    from app.services.direction_map import knowledge_for_terms

    keywords = item.get("research_keywords")
    if isinstance(keywords, list) and keywords:
        terms = [str(part) for part in keywords if str(part).strip()]
    else:
        direction = _research_direction(item)
        terms = [direction] if direction else []
    canonical, points = knowledge_for_terms(terms)
    if canonical is None or not points:
        return None
    points_text = "、".join(points)
    if profile is None or not (profile.research_interests or []):
        return (
            f"能力差距：暂无画像证据支撑技能比对，候选方向入门知识可作参考："
            f"{points_text}（公开学科常识，非个人评价）"
        )
    student_dirs: list[str] = []
    for interest in profile.research_interests:
        resolved, _points = knowledge_for_terms([interest])
        if resolved:
            student_dirs.append(resolved)
    if canonical in student_dirs:
        return (
            f"能力差距：你的画像兴趣与候选方向一致（{canonical}）。"
            f"建议把以下入门知识作为学习清单：{points_text}"
            "（仅作学习参考，不评价你现有水平）"
        )
    if student_dirs:
        others = "、".join(dict.fromkeys(student_dirs))
        return (
            f"能力差距：你画像关注 {others}，候选方向为 {canonical}。"
            f"候选方向的入门知识建议优先补充：{points_text}"
            "（公开学科常识，非个人评价）"
        )
    return (
        f"能力差距：候选方向 {canonical} 的入门知识建议参考：{points_text}"
        "（画像暂无可比对证据）"
    )


def _bar(value: float | None, width: int = 10) -> str:
    """0-100 数值 → 10 格 █/░ 条形（v3.1.7 雷达显示强化，纯字符无依赖）。

    与 v3.1.5 文本版雷达同风格；无数据（None）返回空串，绝不画 0 冒充。
    """
    if value is None:
        return ""
    filled = min(width, max(0, round(value / 100.0 * width)))
    return "█" * filled + "░" * (width - filled)


def _dimension_compare_block(
    item: dict[str, Any],
    *,
    advisor_ratings: dict[str, dict] | None,
    user_dimension_scores: dict[str, float] | None,
) -> list[str]:
    """六维度分项对比表（诚实空态：任一侧无数据即标注「—」/「样本不足」）。

    导师侧：1-5 匿名评价均值换算 0-100（value*20），且必须 ≥
    ADVISOR_RATING_MIN_SAMPLES 样本（调用方已按 get_gated_summary 口径过滤）；
    用户侧：需求映射推导，明确标注，不参与排序。
    v3.1.7：每侧数值后附 10 格条形可视化（无数据不画条）。
    """
    from app.services.constants import TRAIT_KEYS
    from app.services.dialogue_intent import DIMENSION_LABELS

    summary = (advisor_ratings or {}).get(str(item.get("advisor_id")))
    dimensions = (summary or {}).get("dimensions") or {}
    ratings = user_dimension_scores or {}
    lines: list[str] = []
    for key in TRAIT_KEYS:
        label = DIMENSION_LABELS[key]
        user_value = ratings.get(key)
        if user_value is not None:
            user_cell = f"{user_value:.0f}（需求映射） {_bar(user_value)}"
        else:
            user_cell = "—"
        dimension = dimensions.get(key) or {}
        advisor_value = dimension.get("value")
        sample_n = dimension.get("n") or 0
        if advisor_value is None:
            advisor_cell = "暂无足够样本" if summary else "未收录评价"
        else:
            scaled = float(advisor_value) * 20
            advisor_cell = f"{scaled:.0f}（{sample_n} 份评价） {_bar(scaled)}"
        lines.append(f"- {label}：你的需求 {user_cell}｜导师 {advisor_cell}")
    return lines


# 契合度构成分解：排序目标 → 中文标签（与 matching.RankingObjective 值一致）
_FIT_OBJECTIVE_LABELS: dict[str, str] = {
    "topic_fit": "方向匹配",
    "research_mode_fit": "研究方式",
    "mentorship_fit": "指导方式",
    "career_fit": "生涯去向",
    "innovation_fit": "创新偏好",
    "opportunity_fit": "招募机会",
}

# 该维得分与契合度总分差 ≥ 此值判「拉高」，≤ -此值判「拉低」，其余「中位」
_FIT_DIFF_LIFT = 3.0


def format_fit_breakdown(item: dict[str, Any]) -> str | None:
    """把排序分数构成倒推为可读的「契合度构成」块（确定性、fail-safe）。

    v3.1.5 特色：解释"为什么是 XX 分"。数据来源与保守排序分同一口径
    （matching.score_breakdown：score 0-1 × 权重 × 置信度），只做解释层
    呈现，不新增任何评分；score 为 None 的维度（画像无该维度证据）诚实
    标注「未计入」，绝不用基准值冒充。breakdown 缺失/为空 → 返回 None，
    调用方不输出该块（向后兼容）。
    """
    breakdown = item.get("score_breakdown") or []
    if not breakdown:
        return None
    fit_score = float(item.get("fit_score") or 0.0)
    lines = ["**契合度构成（由排序分数倒推，与保守排序分同一口径，非新增评分）**"]
    for row in breakdown:
        objective = row.get("objective") or ""
        label = _FIT_OBJECTIVE_LABELS.get(objective, objective or "未知名")
        weight = float(row.get("requested_weight") or 0.0)
        score = row.get("score")
        if score is None:
            lines.append(f"- {label}：未计入（画像无该维度证据，确认后生效）")
            continue
        dim_score = float(score) * 100.0
        diff = dim_score - fit_score
        if diff >= _FIT_DIFF_LIFT:
            mark = "▲ 拉高"
        elif diff <= -_FIT_DIFF_LIFT:
            mark = "▼ 拉低"
        else:
            mark = "· 中位"
        lines.append(
            f"- {mark}：{label}（权重 {weight:.0%}）—— {dim_score:.0f} 分"
        )
    return "\n".join(lines)


def format_match_item(
    item: dict[str, Any],
    *,
    index: int,
    profile: StudentPortrait | None = None,
    advisor_ratings: dict[str, dict] | None = None,
    user_dimension_scores: dict[str, float] | None = None,
) -> str:
    """渲染单个匹配候选的完整详情块。

    v3.1.6 从 format_match_outcome 抽出：匹配结果内联循环与「第 N 个」
    单候选追问共用同一渲染，输出逐字一致（不重算分数或结论）。
    """
    tone = derive_reply_tone(profile)
    lines: list[str] = []
    dept = item.get("dept")
    header = f"{item['name']}" + (f" · {dept}" if dept else "")
    title = (item.get("title") or "").strip()
    lines.append(
        (
            f"\n{index}. {header} —— 契合度 {item['fit_score']:.0f} 分；"
            f"保守排序分 {item['score']:.1f}，证据覆盖 "
            f"{item['evidence_coverage']:.0%}，证据置信度 "
            f"{item['evidence_confidence']:.0%}。"
        )
    )
    breakdown_block = format_fit_breakdown(item)
    if breakdown_block:
        lines.append(breakdown_block)
    basic_parts = [str(item["name"]), str(dept or "院系未收录")]
    if title:
        basic_parts.append(title)
    lines.append(f"基本信息：{' | '.join(basic_parts)}")
    homepage = (item.get("official_homepage") or "").strip()
    if homepage:
        # v3.1.7 对标清研向导：候选官方主页链接（无该字段诚实省略）
        lines.append(f"官方主页：{homepage}")
    direction = _research_direction(item)
    if direction:
        lines.append(f"核心研究方向：{direction}")
    explanation = item["explanation"]
    supporting = explanation.get("supporting_evidence") or []
    if supporting:
        lines.append(
            f"{_TONE_FIT_LABELS[tone]}：{supporting[0]['statement']}"
        )
    lines.append("👍 亮点")
    for claim in supporting[:2]:
        citation = claim["citations"][0]
        lines.append(
            f"- {claim['statement']} 来源：{citation['citation']}"
        )
    lines.append("⚠️ 需要注意")
    for claim in explanation.get("counter_evidence") or []:
        lines.append(f"- {claim['statement']}")
    for uncertainty in explanation.get("uncertainties")[:2]:
        lines.append(f"- {uncertainty}")
    if item["evidence_coverage"] < 1.0:
        lines.append(
            "- 证据覆盖率不满 100%，排序分已保守折减，请把分数当作"
            "相对排序而非绝对值。"
        )
    if advisor_ratings or user_dimension_scores:
        lines.append(
            "六维度对比（分数 0-100；「你的需求」由画像映射推导、"
            "不参与排序；「导师」为 ≥8 份匿名学生评价换算）"
        )
        lines.extend(
            _dimension_compare_block(
                item,
                advisor_ratings=advisor_ratings,
                user_dimension_scores=user_dimension_scores,
            )
        )
    gap_block = format_gap_analysis(item, profile)
    if gap_block:
        # v3.1.7 能力差距分析（对标清研向导「需要补充的知识或技能」）
        lines.append(gap_block)
    verify = explanation.get("questions_to_verify") or []
    if verify:
        lines.append(f"建议：{verify[0]}")
    return "\n".join(lines)


def format_match_outcome(
    outcome: MatchApplicationOutcome,
    *,
    profile: StudentPortrait | None = None,
    advisor_ratings: dict[str, dict] | None = None,
    user_dimension_scores: dict[str, float] | None = None,
) -> str:
    """把共用结果格式化为清小搭可读文本，不重算分数或结论。

    呈现分组：为什么适合你 / 👍 亮点（好处）/ ⚠️ 需要注意（坏处与不确定）/ 建议；
    语气档位由已确认画像推导，三档之间的数字与证据内容逐字一致。
    v2.5 新增（可选参数，向后兼容）：契合度分数、基本信息（姓名|院系|职称）、
    核心研究方向、六维度对比表——无数据时诚实省略或标注「—」。
    v3.1.5 新增：契合度构成分解（format_fit_breakdown）——有 score_breakdown
    时输出"为什么是 XX 分"的拉高/拉低/中位/未计入四类行，无则省略。
    """
    tone = derive_reply_tone(profile)
    lines: list[str] = []
    if outcome.status == "matched":
        lines.append(_TONE_OPENINGS[tone])
        for index, item in enumerate(outcome.items, start=1):
            lines.append(
                format_match_item(
                    item,
                    index=index,
                    profile=profile,
                    advisor_ratings=advisor_ratings,
                    user_dimension_scores=user_dimension_scores,
                )
            )
        lines.append("")
        lines.append(_TONE_CLOSINGS[tone])
        lines.append(_SITE_DEEP_LINK)
    else:
        lines.append(outcome.message)
    for question in outcome.questions:
        lines.append(f"- {question}")
    return "\n".join(lines)
