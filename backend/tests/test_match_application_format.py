"""匹配应用格式化服务测试：语气分层与事实一致性。"""

from __future__ import annotations

import re

import pytest

from app.schemas.interview import StudentPortrait
from app.services.match_application import (
    MatchApplicationOutcome,
    derive_reply_tone,
    format_match_outcome,
)


def _sample_outcome() -> MatchApplicationOutcome:
    """构造一个固定的匹配 outcome，覆盖所有呈现分支。"""
    return MatchApplicationOutcome(
        status="matched",
        items=[
            {
                "advisor_id": "T00001",
                "name": "测试导师",
                "dept": "自动化系",
                "score": 85.5,
                "fit_score": 90.0,
                "evidence_coverage": 0.85,
                "evidence_confidence": 0.92,
                "explanation": {
                    "supporting_evidence": [
                        {
                            "statement": "在 NLP 方向有深厚积累",
                            "citations": [
                                {"citation": "顶会论文 2023", "source": "public"}
                            ],
                        },
                        {
                            "statement": "指导过多个相关项目",
                            "citations": [
                                {"citation": "项目记录", "source": "public"}
                            ],
                        },
                    ],
                    "counter_evidence": [
                        {
                            "statement": "近期经费有限",
                            "citations": [
                                {"citation": "年度报表", "source": "public"}
                            ],
                        },
                    ],
                    "uncertainties": [
                        "是否接受跨院系学生",
                        "下一届招生名额未确定",
                    ],
                    "questions_to_verify": [
                        "建议核实导师近期经费状况",
                        "建议确认是否有跨院系招生先例",
                    ],
                },
            }
        ],
        meta={"match_candidate_records": 1, "interview_status": "confirmed"},
        message="找到 1 个证据化候选。",
        questions=[],
    )


def test_derive_reply_tone_mapping():
    assert derive_reply_tone(None) == "balanced"
    assert derive_reply_tone(StudentPortrait(career_orientation="industry")) == "pragmatic"
    assert derive_reply_tone(StudentPortrait(innovation_risk="mature")) == "pragmatic"
    assert (
        derive_reply_tone(
            StudentPortrait(career_orientation="academic", innovation_risk="pioneering")
        )
        == "exploratory"
    )
    assert (
        derive_reply_tone(
            StudentPortrait(career_orientation="mixed", innovation_risk="balanced")
        )
        == "balanced"
    )
    assert (
        derive_reply_tone(
            StudentPortrait(career_orientation="academic", innovation_risk="balanced")
        )
        == "balanced"
    )


def test_format_match_outcome_preserves_facts_across_three_tones():
    outcome = _sample_outcome()

    pragmatic_profile = StudentPortrait(career_orientation="industry")
    exploratory_profile = StudentPortrait(
        career_orientation="academic", innovation_risk="pioneering"
    )
    balanced_profile = StudentPortrait(
        career_orientation="national_mission", innovation_risk="balanced"
    )

    pragmatic = format_match_outcome(outcome, profile=pragmatic_profile)
    exploratory = format_match_outcome(outcome, profile=exploratory_profile)
    balanced = format_match_outcome(outcome, profile=balanced_profile)
    default_ = format_match_outcome(outcome, profile=None)

    # 三档文案不全等
    assert pragmatic != exploratory
    assert exploratory != balanced
    assert pragmatic != balanced

    # 关键数字集合相等
    def extract_numbers(text: str) -> set[str]:
        return set(re.findall(r"\d+\.?\d*", text))

    nums_p = extract_numbers(pragmatic)
    nums_e = extract_numbers(exploratory)
    nums_b = extract_numbers(balanced)
    nums_d = extract_numbers(default_)
    assert nums_p == nums_e == nums_b == nums_d

    # 候选人名、证据文本片段一致
    for text in (pragmatic, exploratory, balanced, default_):
        assert "测试导师" in text
        assert "自动化系" in text
        assert "在 NLP 方向有深厚积累" in text
        assert "近期经费有限" in text

    # 分组结构存在
    for text in (pragmatic, exploratory, balanced, default_):
        assert "👍 亮点" in text
        assert "⚠️ 需要注意" in text
        assert any(marker in text for marker in ("建议：", "建议下一步"))

    # profile=None 时不报错且走默认档（balanced）
    assert default_ == balanced


def test_format_match_outcome_different_openings_and_closings():
    outcome = _sample_outcome()
    p = format_match_outcome(outcome, profile=StudentPortrait(career_orientation="industry"))
    e = format_match_outcome(
        outcome, profile=StudentPortrait(career_orientation="academic", innovation_risk="pioneering")
    )
    b = format_match_outcome(outcome, profile=StudentPortrait())

    assert "按你确认的画像筛了一轮，先看关键数字：" in p
    assert "结合你确认的研究方向与探索偏好，这几位候选与你的重合度最高：" in e
    assert "基于你确认的画像，找到以下证据化候选：" in b

    assert "匹配点" in p
    assert "契合点" in e
    assert "为什么适合你" in b

    assert "优先核实产出节奏与毕业安排" in p
    assert "带着你的研究设想与导师聊聊方向重合度" in e
    assert "先核实各候选「需要注意」中的不确定项，再约谈" in b


def test_format_match_outcome_non_matched_statuses():
    no_data = MatchApplicationOutcome(
        status="no_published_data",
        items=[],
        meta={},
        message="暂无通过审核的数据可作为正式推荐导师画像。",
        questions=["是否要检查已确认的硬约束？"],
    )
    text = format_match_outcome(no_data, profile=None)
    assert "暂无通过审核的数据可作为正式推荐导师画像" in text
    assert "是否要检查已确认的硬约束？" in text
    assert "👍 亮点" not in text
    assert "⚠️ 需要注意" not in text
