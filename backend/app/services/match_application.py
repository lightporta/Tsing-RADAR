"""Web 与清小搭共用的 A4 匹配应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.schemas.interview import StudentPortrait
from app.schemas.matching import RankingConfig
from app.services.data_loader import (
    load_match_candidates,
    mentor_data_summary,
)
from app.services.interview import confirmed_portrait
from app.services.matching import match_mentors


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
) -> MatchApplicationOutcome:
    """读取已确认服务端画像并执行唯一一套匹配流水线。"""
    portrait = confirmed_portrait(
        db,
        session_id=session_id,
        student_id=student_id,
    )
    candidates = load_match_candidates()
    result = match_mentors(
        mentors=candidates,
        portrait=portrait.model_dump(mode="json"),
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


def format_match_outcome(
    outcome: MatchApplicationOutcome,
    *,
    profile: StudentPortrait | None = None,
) -> str:
    """把共用结果格式化为清小搭可读文本，不重算分数或结论。

    呈现分组：为什么适合你 / 👍 亮点（好处）/ ⚠️ 需要注意（坏处与不确定）/ 建议；
    语气档位由已确认画像推导，三档之间的数字与证据内容逐字一致。
    """
    tone = derive_reply_tone(profile)
    lines: list[str] = []
    if outcome.status == "matched":
        lines.append(_TONE_OPENINGS[tone])
        for index, item in enumerate(outcome.items, start=1):
            dept = item.get("dept")
            header = f"{item['name']}" + (f" · {dept}" if dept else "")
            lines.append(
                (
                    f"\n{index}. {header} —— 保守排序分 {item['score']:.1f}，"
                    f"适配分 {item['fit_score']:.1f}，证据覆盖 "
                    f"{item['evidence_coverage']:.0%}，证据置信度 "
                    f"{item['evidence_confidence']:.0%}。"
                )
            )
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
            verify = explanation.get("questions_to_verify") or []
            if verify:
                lines.append(f"建议：{verify[0]}")
        lines.append("")
        lines.append(_TONE_CLOSINGS[tone])
        lines.append(_SITE_DEEP_LINK)
    else:
        lines.append(outcome.message)
    for question in outcome.questions:
        lines.append(f"- {question}")
    return "\n".join(lines)
