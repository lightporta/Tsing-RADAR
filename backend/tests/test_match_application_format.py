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


def test_format_match_outcome_v25_adds_fit_basic_and_dimension_table():
    outcome = _sample_outcome()
    ratings = {
        "T00001": {
            "dimensions": {
                "acumen": {"value": 4.5, "n": 9},
                "network": {"value": None, "n": 1},
                "mentorship": {"value": 3.2, "n": 12},
                "tolerance": {"value": None, "n": 0},
                "funding": {"value": 4.0, "n": 8},
                "efficiency": {"value": None, "n": 2},
            }
        }
    }
    user_scores = {
        "acumen": 80.0,
        "mentorship": 85.0,
        "funding": 75.0,
        "efficiency": 80.0,
        "tolerance": 60.0,
        "network": 70.0,
    }
    text = format_match_outcome(
        outcome,
        profile=StudentPortrait(
            career_orientation="academic", innovation_risk="pioneering"
        ),
        advisor_ratings=ratings,
        user_dimension_scores=user_scores,
    )
    # v2.5 要素
    assert "契合度 90 分" in text
    assert "基本信息：测试导师 | 自动化系" in text
    assert "六维度对比" in text
    assert "你的需求 80（需求映射）" in text
    assert "导师 90（9 份评价）" in text          # 4.5 * 20 = 90
    assert "导师 64（12 份评价）" in text          # 3.2 * 20 = 64
    # 样本不足维度诚实空态
    assert "导师 暂无足够样本" in text
    # 既有结构不回归
    assert "👍 亮点" in text
    assert "测试导师" in text


def test_format_match_outcome_v25_research_direction_when_present():
    outcome = _sample_outcome()
    outcome.items[0]["research_summary"] = "围绕自然语言处理与大模型开展研究"
    text = format_match_outcome(outcome, profile=None)
    assert "核心研究方向：围绕自然语言处理与大模型开展研究" in text


def test_derive_user_dimension_scores_mapping():
    from app.services.match_application import derive_user_dimension_scores

    profile = StudentPortrait(
        mentorship_style="high_guidance",
        innovation_risk="pioneering",
        research_mode="engineering",
    )
    scores = derive_user_dimension_scores(profile)
    assert scores["mentorship"] == 85.0
    assert scores["acumen"] == 80.0
    assert scores["efficiency"] == 70.0

    # 隐式关注维度补充（取较大值）
    scores = derive_user_dimension_scores(
        StudentPortrait(), implicit_dimensions=("funding", "funding")
    )
    assert scores.get("funding") == 75.0

    # 空画像 → 空映射（不产生任何伪造需求分）
    assert derive_user_dimension_scores(None) == {}


def _breakdown_item(**overrides) -> dict:
    """构造带 score_breakdown 的匹配候选（v3.1.5 契合度构成分解）。"""
    item = {
        "fit_score": 60.0,
        "score_breakdown": [
            {
                "objective": "topic_fit",
                "requested_weight": 0.4,
                "score": 0.9,  # 90 分 > 60 → 拉高
                "method": "exact-category-v1",
                "evidence_coverage": 1.0,
                "evidence_confidence": 0.8,
                "conservative_contribution": 0.288,
            },
            {
                "objective": "mentorship_fit",
                "requested_weight": 0.2,
                "score": 0.3,  # 30 分 < 60 → 拉低
                "method": "exact-category-v1",
                "evidence_coverage": 1.0,
                "evidence_confidence": 0.9,
                "conservative_contribution": 0.054,
            },
            {
                "objective": "career_fit",
                "requested_weight": 0.2,
                "score": 0.58,  # 58 分 ≈ 60 → 中位
                "method": "exact-category-v1",
                "evidence_coverage": 1.0,
                "evidence_confidence": 0.7,
                "conservative_contribution": 0.081,
            },
            {
                "objective": "innovation_fit",
                "requested_weight": 0.1,
                "score": None,  # 无画像证据 → 未计入
                "method": "not-scored",
                "evidence_coverage": 0.0,
                "evidence_confidence": 0.0,
                "conservative_contribution": 0.0,
            },
        ],
    }
    item.update(overrides)
    return item


def test_format_fit_breakdown_mixed_signs_and_labels():
    from app.services.match_application import format_fit_breakdown

    text = format_fit_breakdown(_breakdown_item())
    assert text is not None
    assert "契合度构成" in text
    assert "非新增评分" in text  # 诚实声明：只解释不新增评分
    assert "▲ 拉高：方向匹配（权重 40%）—— 90 分" in text
    assert "▼ 拉低：指导方式（权重 20%）—— 30 分" in text
    assert "· 中位：生涯去向（权重 20%）—— 58 分" in text
    assert "创新偏好：未计入（画像无该维度证据，确认后生效）" in text


def test_format_fit_breakdown_deterministic_and_missing_breakdown():
    from app.services.match_application import format_fit_breakdown

    item = _breakdown_item()
    assert format_fit_breakdown(item) == format_fit_breakdown(item)
    # breakdown 缺失/为空 → None（调用方省略该块，向后兼容）
    assert format_fit_breakdown({"fit_score": 60.0}) is None
    assert format_fit_breakdown({"fit_score": 60.0, "score_breakdown": []}) is None


def test_format_fit_breakdown_threshold_boundary():
    from app.services.match_application import format_fit_breakdown

    # diff == +3.0 → 拉高；diff == -3.0 → 拉低（含边界）
    item = _breakdown_item(
        fit_score=60.0,
        score_breakdown=[
            {
                "objective": "topic_fit",
                "requested_weight": 0.5,
                "score": 0.63,  # 63 - 60 = +3 → 拉高
                "method": "exact-category-v1",
                "evidence_coverage": 1.0,
                "evidence_confidence": 1.0,
                "conservative_contribution": 0.3,
            },
            {
                "objective": "opportunity_fit",
                "requested_weight": 0.5,
                "score": 0.57,  # 57 - 60 = -3 → 拉低
                "method": "opportunity-signal-v1",
                "evidence_coverage": 1.0,
                "evidence_confidence": 1.0,
                "conservative_contribution": 0.3,
            },
        ],
    )
    text = format_fit_breakdown(item)
    assert "▲ 拉高：方向匹配（权重 50%）—— 63 分" in text
    assert "▼ 拉低：招募机会（权重 50%）—— 57 分" in text


def test_format_fit_breakdown_unknown_objective_falls_back_to_key():
    from app.services.match_application import format_fit_breakdown

    item = _breakdown_item(
        score_breakdown=[
            {
                "objective": "some_future_fit",
                "requested_weight": 0.5,
                "score": 0.8,
                "method": "v9",
                "evidence_coverage": 1.0,
                "evidence_confidence": 1.0,
                "conservative_contribution": 0.4,
            }
        ]
    )
    text = format_fit_breakdown(item)
    assert "some_future_fit" in text  # 未知名目标回退原始键，不崩溃


def test_format_match_item_inline_consistency_and_single_candidate():
    """v3.1.6：format_match_item 与 format_match_outcome 内联逐字一致。"""
    from app.services.match_application import format_match_item

    outcome = _sample_outcome()
    profile = StudentPortrait(career_orientation="industry")
    full = format_match_outcome(outcome, profile=profile)
    item_block = format_match_item(outcome.items[0], index=1, profile=profile)

    # 详情块是内联输出的一部分且只出现一次（逐字一致）
    assert full.count(item_block) == 1
    head, tail = full.split(item_block, 1)
    assert head.strip() and tail.strip()

    # 单候选追问带序号头与关键事实
    assert item_block.startswith("\n1. 测试导师")
    assert "契合度 90 分" in item_block
    assert "保守排序分 85.5" in item_block
    assert "👍 亮点" in item_block
    # 无 score_breakdown 时不出现构成分解块
    assert "契合度构成" not in item_block
    # 默认档（profile=None）可独立渲染，数字不变
    default_block = format_match_item(outcome.items[0], index=1)
    assert "契合度 90 分" in default_block


# —— v3.1.7 能力差距分析 / 官方主页 / 六维条形 ——


def test_format_gap_analysis_same_direction_shows_learning_list():
    from app.services.match_application import format_gap_analysis

    item = {"research_keywords": ["大模型", "自然语言处理"]}
    profile = StudentPortrait(research_interests=["大模型"])
    block = format_gap_analysis(item, profile)
    assert block is not None
    assert "能力差距" in block
    assert "你的画像兴趣与候选方向一致（大模型 / 大语言模型）" in block
    assert "Transformer 架构与注意力机制" in block
    assert "学习清单" in block


def test_format_gap_analysis_cross_direction_lists_supplement():
    from app.services.match_application import format_gap_analysis

    item = {"research_keywords": ["计算机视觉"]}
    profile = StudentPortrait(research_interests=["大模型"])
    block = format_gap_analysis(item, profile)
    assert block is not None
    assert "你画像关注 大模型 / 大语言模型" in block
    assert "候选方向为 计算机视觉" in block
    assert "卷积网络与特征提取" in block
    assert "建议优先补充" in block


def test_format_gap_analysis_no_portrait_honest_note():
    from app.services.match_application import format_gap_analysis

    item = {"research_keywords": ["大模型"]}
    block = format_gap_analysis(item, None)
    assert block is not None
    assert "暂无画像证据" in block
    assert "Transformer 架构与注意力机制" in block


def test_format_gap_analysis_unmapped_direction_omitted():
    from app.services.match_application import format_gap_analysis

    item = {"research_keywords": ["不存在的研究方向 X"]}
    assert format_gap_analysis(item, None) is None
    assert format_gap_analysis({}, None) is None


def test_format_gap_analysis_substring_fallback_on_summary():
    from app.services.match_application import format_gap_analysis

    # research_keywords 缺失时回退核心研究方向文本，子串命中规范方向名
    item = {"research_summary": "围绕自然语言处理与大模型开展研究"}
    profile = StudentPortrait(research_interests=["NLP"])
    block = format_gap_analysis(item, profile)
    assert block is not None
    assert "自然语言处理" in block
    assert "学习清单" in block  # 同方向分支（NLP → 自然语言处理）


def test_format_match_item_includes_gap_block_when_mapped():
    from app.services.match_application import format_match_item

    outcome = _sample_outcome()
    outcome.items[0]["research_keywords"] = ["大模型"]
    block = format_match_item(
        outcome.items[0],
        index=1,
        profile=StudentPortrait(research_interests=["NLP"]),
    )
    assert "能力差距" in block


def test_format_match_item_renders_official_homepage_when_present():
    from app.services.match_application import format_match_item

    outcome = _sample_outcome()
    outcome.items[0]["official_homepage"] = "https://example.com/prof"
    block = format_match_item(outcome.items[0], index=1)
    assert "官方主页：https://example.com/prof" in block


def test_format_match_item_omits_homepage_when_absent():
    from app.services.match_application import format_match_item

    outcome = _sample_outcome()
    block = format_match_item(outcome.items[0], index=1)
    assert "官方主页" not in block


def test_dimension_compare_block_appends_bars_after_values():
    from app.services.match_application import format_match_outcome

    outcome = _sample_outcome()
    ratings = {
        "T00001": {
            "dimensions": {
                "acumen": {"value": 4.5, "n": 9},
                "network": {"value": None, "n": 1},
                "mentorship": {"value": 3.2, "n": 12},
                "tolerance": {"value": None, "n": 0},
                "funding": {"value": 4.0, "n": 8},
                "efficiency": {"value": None, "n": 2},
            }
        }
    }
    user_scores = {
        "acumen": 80.0,
        "mentorship": 85.0,
        "funding": 75.0,
        "efficiency": 80.0,
        "tolerance": 60.0,
        "network": 70.0,
    }
    text = format_match_outcome(
        outcome,
        profile=StudentPortrait(),
        advisor_ratings=ratings,
        user_dimension_scores=user_scores,
    )
    # 数值与条形并存，且条形在数值之后（保持既有子串断言兼容）
    assert "你的需求 80（需求映射） ████████░░" in text
    assert "导师 90（9 份评价） █████████░" in text
    assert "导师 64（12 份评价） ██████░░░░" in text
    # 无数据侧不画条（诚实空态，不画 0 冒充）
    assert "导师 暂无足够样本" in text
