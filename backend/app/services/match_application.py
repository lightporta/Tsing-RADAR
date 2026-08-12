"""Web 与清小搭共用的 A4 匹配应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

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
        return MatchApplicationOutcome(
            status="no_match",
            items=[],
            meta=meta,
            message=(
                "已有发布数据，但当前没有同时通过硬约束和召回阈值的候选。"
            ),
            questions=[
                "是否要检查已确认的硬约束或调整召回阈值？"
            ],
        )
    return MatchApplicationOutcome(
        status="matched",
        items=result.items,
        meta=meta,
        message=f"基于已确认画像找到 {len(result.items)} 个证据化候选。",
        questions=[],
    )


def format_match_outcome(outcome: MatchApplicationOutcome) -> str:
    """把共用结果格式化为清小搭可读文本，不重算分数或结论。"""
    lines = [outcome.message]
    if outcome.status == "matched":
        for index, item in enumerate(outcome.items, start=1):
            lines.append(
                (
                    f"\n{index}. {item['name']}：保守排序分 {item['score']:.1f}，"
                    f"适配分 {item['fit_score']:.1f}，证据覆盖 "
                    f"{item['evidence_coverage']:.0%}，证据置信度 "
                    f"{item['evidence_confidence']:.0%}。"
                )
            )
            explanation = item["explanation"]
            for claim in explanation["supporting_evidence"][:2]:
                citation = claim["citations"][0]
                lines.append(
                    f"- 支持：{claim['statement']} 来源：{citation['citation']}"
                )
            for claim in explanation["counter_evidence"][:1]:
                lines.append(f"- 反证/不利信号：{claim['statement']}")
            for uncertainty in explanation["uncertainties"][:2]:
                lines.append(f"- 不确定性：{uncertainty}")
            for question in explanation["questions_to_verify"][:2]:
                lines.append(f"- 待核实：{question}")
    for question in outcome.questions:
        lines.append(f"- {question}")
    return "\n".join(lines)
