"""A4 证据化匹配流水线单元测试。

本文件中的导师均为合成夹具，不写入 ``backend/data``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import json
from pydantic import ValidationError

from app.schemas.matching import (
    OpportunitySignal,
    RankingConfig,
    RankingWeights,
)
from app.services.matching import (
    hard_constraint_capabilities,
    hash_embedding,
    keyword_overlap_baseline,
    lexical_concept_similarity,
    match_mentors,
)

AS_OF = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _source(ref: str, confidence: float = 0.9) -> dict:
    return {
        "evidence_id": str(uuid4()),
        "source_type": "public_fact",
        "source_ref": f"https://example.edu/{ref}",
        "captured_at": "2026-07-20T08:00:00+00:00",
        "verification_status": "verified",
        "confidence": confidence,
    }


def _claim(statement: str, ref: str) -> dict:
    return {"statement": statement, "sources": [_source(ref)]}


def _signal(
    signal_id: str,
    *,
    effect: float,
    valid_until: str = "2026-12-31T00:00:00+00:00",
) -> dict:
    return {
        "signal_id": signal_id,
        "signal_type": "publication_or_hiring_growth",
        "label": "近一年公开岗位与论文增长",
        "effect": effect,
        "confidence": 0.8,
        "observed_from": "2025-07-01T00:00:00+00:00",
        "observed_to": "2026-06-30T00:00:00+00:00",
        "valid_until": valid_until,
        "method": "公开页面计数同比",
        "method_version": "fixture-v1",
        "supporting_evidence": [_claim("公开计数支持该变化方向。", signal_id)],
        "counter_evidence": [_claim("样本窗口仍然较短。", f"{signal_id}-counter")],
    }


def _candidate(
    advisor_id: str,
    *,
    name: str,
    dept: str,
    field: str,
    tags: list[str],
    research_modes: list[str],
    mentorship_styles: list[str],
    career_orientations: list[str],
    innovation_profiles: list[str],
    opportunity_signals: list[dict] | None = None,
) -> dict:
    values = {
        "advisor_id": advisor_id,
        "name": name,
        "dept": dept,
        "field": field,
        "tags": tags,
        "research_modes": research_modes,
        "mentorship_styles": mentorship_styles,
        "career_orientations": career_orientations,
        "innovation_profiles": innovation_profiles,
        "locations": ["北京"],
        "weekly_commitment_days": 4,
        "degree_stages": ["硕士"],
        "languages": ["中文", "英语"],
        "confidentiality": ["可接受保密项目"],
        "graduation_arrangements": ["支持正常毕业安排"],
    }
    if opportunity_signals is not None:
        values["opportunity_signals"] = opportunity_signals
    values["provenance"] = {
        key: [_source(f"{advisor_id}/{key}")]
        for key in values
        if key not in {"advisor_id", "provenance"}
    }
    return values


def _portrait(
    hard_constraints: list[dict] | None = None,
    unresolved_hard_constraints: list[str] | None = None,
) -> dict:
    return {
        "research_interests": ["自然语言处理", "对话系统"],
        "interest_statement": "希望做面向真实场景的 NLP 系统",
        "research_mode": "engineering",
        "mentorship_style": "high_guidance",
        "career_orientation": "industry",
        "innovation_risk": "pioneering",
        "hard_constraints": hard_constraints,
        "unresolved_hard_constraints": unresolved_hard_constraints,
    }


def _candidates() -> list[dict]:
    return [
        _candidate(
            "SYN-001",
            name="合成甲",
            dept="计算机系",
            field="自然语言处理与对话系统",
            tags=["NLP", "大语言模型"],
            research_modes=["theory"],
            mentorship_styles=["autonomous"],
            career_orientations=["academic"],
            innovation_profiles=["mature"],
            opportunity_signals=[_signal("signal-a", effect=-0.5)],
        ),
        _candidate(
            "SYN-002",
            name="合成乙",
            dept="自动化系",
            field="机器学习与文本挖掘",
            tags=["NLP"],
            research_modes=["engineering"],
            mentorship_styles=["high_guidance"],
            career_orientations=["industry"],
            innovation_profiles=["pioneering"],
            opportunity_signals=[_signal("signal-b", effect=0.8)],
        ),
    ]


def test_lexical_fallback_has_baseline_paraphrase_and_false_overlap_controls():
    assert keyword_overlap_baseline("NLP", "自然语言处理与对话系统") == 0
    related, features = lexical_concept_similarity(
        "NLP", "自然语言处理与对话系统"
    )
    unrelated, _ = lexical_concept_similarity("NLP", "热力学材料制备")
    assert related > unrelated
    assert "natural_language_processing" in features

    paraphrase, _ = lexical_concept_similarity("机器学习", "深度学习方法")
    false_surface_overlap, _ = lexical_concept_similarity(
        "机器学习", "学习机器的维护规程"
    )
    assert paraphrase > false_surface_overlap

    # 兼容向量也来自共享词项：相关文本应比无关文本更相近。
    query = hash_embedding("NLP 自然语言处理", 256)
    related_vec = hash_embedding("自然语言处理与对话系统", 256)
    unrelated_vec = hash_embedding("热力学材料制备", 256)
    dot = lambda left, right: sum(a * b for a, b in zip(left, right))
    assert dot(query, related_vec) > dot(query, unrelated_vec)


def test_hard_constraints_run_before_recall_and_fail_closed():
    result = match_mentors(
        _candidates(),
        _portrait(
            [
                {
                    "field": "department",
                    "operator": "equals",
                    "value": ["自动化系"],
                },
                {
                    "field": "location",
                    "operator": "one_of",
                    "value": ["北京"],
                },
            ]
        ),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    assert [item["advisor_id"] for item in result.items] == ["SYN-002"]
    assert result.meta["input_candidates"] == 2
    assert result.meta["after_hard_constraints"] == 1
    assert result.meta["excluded_by_hard_constraints"] == 1
    assert result.meta["applied_hard_constraints"] == [
        "department|equals|自动化系",
        "location|one_of|北京",
    ]

    unresolved = match_mentors(
        _candidates(),
        _portrait(unresolved_hard_constraints=["最好离宿舍近一点"]),
        as_of=AS_OF,
    )
    assert unresolved.items == []
    assert unresolved.meta["after_hard_constraints"] == 0
    assert unresolved.meta["status"] == "needs_clarification"
    assert unresolved.meta["unresolved_hard_constraints"] == [
        "最好离宿舍近一点"
    ]
    assert "具体、不可妥协条件" in unresolved.meta["clarification_questions"][0]


def test_capabilities_follow_current_evidence_and_zero_trace_names_constraint():
    candidates = _candidates()
    del candidates[0]["locations"]
    del candidates[0]["provenance"]["locations"]
    capabilities = hard_constraint_capabilities(candidates)
    by_field = {item["field"]: item for item in capabilities["fields"]}
    assert by_field["location"]["available"] is True
    assert by_field["location"]["evidence_record_count"] == 1
    assert by_field["location"]["evidence_coverage"] == pytest.approx(0.5)
    assert by_field["research_topic"]["operators"] == ["contains", "excludes"]

    result = match_mentors(
        candidates,
        _portrait(
            [
                {
                    "field": "department",
                    "operator": "equals",
                    "value": ["不存在的院系"],
                }
            ]
        ),
        as_of=AS_OF,
    )
    assert result.items == []
    assert result.meta["constraint_trace"][0]["candidates_before"] == 2
    assert result.meta["constraint_trace"][0]["candidates_after"] == 0
    assert "院系" in result.meta["zero_result_reason"]
    assert "不存在的院系" in result.meta["zero_result_reason"]


def test_source_less_or_legacy_subjective_fields_cannot_enter_recall():
    unsafe = {
        "advisor_id": "SYN-UNSAFE",
        "name": "合成无证据",
        "field": "自然语言处理",
        "tags": ["NLP"],
        "score": 99,
        "popularity": 100,
        "provenance": {"name": [_source("unsafe/name")]},
    }
    result = match_mentors(
        [unsafe],
        _portrait(),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    assert result.items == []
    assert result.meta["recalled_candidates"] == 0


def test_structured_constraints_cover_time_degree_language_and_arrangements():
    constraints = [
        {
            "field": "weekly_commitment_days",
            "operator": "minimum",
            "value": ["3"],
        },
        {
            "field": "degree_stage",
            "operator": "one_of",
            "value": ["硕士"],
        },
        {
            "field": "language",
            "operator": "one_of",
            "value": ["英语"],
        },
        {
            "field": "confidentiality",
            "operator": "equals",
            "value": ["可接受保密项目"],
        },
        {
            "field": "graduation_arrangement",
            "operator": "contains",
            "value": ["正常毕业"],
        },
    ]
    passed = match_mentors(
        [_candidates()[0]],
        _portrait(constraints),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    assert [item["advisor_id"] for item in passed.items] == ["SYN-001"]

    constraints[0] = {
        "field": "weekly_commitment_days",
        "operator": "minimum",
        "value": ["5"],
    }
    failed = match_mentors(
        [_candidates()[0]],
        _portrait(constraints),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    assert failed.items == []
    assert failed.meta["excluded_by_hard_constraints"] == 1


def test_configurable_multi_objective_ranking_changes_order_transparently():
    topic_only = RankingConfig(
        weights=RankingWeights(
            topic_fit=1,
            research_mode_fit=0,
            mentorship_fit=0,
            career_fit=0,
            innovation_fit=0,
            opportunity_fit=0,
        ),
        minimum_recall_score=0,
    )
    preference_only = RankingConfig(
        weights=RankingWeights(
            topic_fit=0,
            research_mode_fit=0.25,
            mentorship_fit=0.25,
            career_fit=0.2,
            innovation_fit=0.2,
            opportunity_fit=0.1,
        ),
        minimum_recall_score=0,
    )

    topic_result = match_mentors(
        _candidates(), _portrait(), topic_only, as_of=AS_OF
    )
    preference_result = match_mentors(
        _candidates(), _portrait(), preference_only, as_of=AS_OF
    )

    assert topic_result.items[0]["advisor_id"] == "SYN-001"
    assert preference_result.items[0]["advisor_id"] == "SYN-002"
    breakdown = {
        row["objective"]: row
        for row in preference_result.items[0]["score_breakdown"]
    }
    assert breakdown["topic_fit"]["requested_weight"] == 0
    assert breakdown["research_mode_fit"]["method"] == "exact-category-v1"
    assert sum(row["effective_weight"] for row in breakdown.values()) == pytest.approx(
        1.0, abs=1e-5
    )


def test_explanation_contains_sources_counterevidence_and_uncertainty():
    candidates = _candidates()
    # 删除一个有来源的画像维度，验证它不会被默认补值。
    candidates[1].pop("mentorship_styles")
    candidates[1]["provenance"].pop("mentorship_styles")

    result = match_mentors(
        candidates,
        _portrait(
            [
                {
                    "field": "department",
                    "operator": "equals",
                    "value": ["自动化系"],
                }
            ]
        ),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    item = result.items[0]
    explanation = item["explanation"]
    assert explanation["supporting_evidence"]
    assert explanation["counter_evidence"]
    assert any(
        claim["citations"][0]["source_url"].startswith("https://example.edu/")
        for claim in explanation["supporting_evidence"]
    )
    assert any("指导方式" in text for text in explanation["uncertainties"])
    assert any("核实指导方式" in text for text in explanation["questions_to_verify"])


def test_sparse_evidence_is_penalized_instead_of_renormalized_to_full_score():
    rich = _candidates()[1]
    sparse = _candidate(
        "SYN-SPARSE",
        name="合成稀疏",
        dept="自动化系",
        field=rich["field"],
        tags=rich["tags"],
        research_modes=[],
        mentorship_styles=[],
        career_orientations=[],
        innovation_profiles=[],
        opportunity_signals=None,
    )
    for field_name in (
        "research_modes",
        "mentorship_styles",
        "career_orientations",
        "innovation_profiles",
    ):
        sparse.pop(field_name)
        sparse["provenance"].pop(field_name)

    result = match_mentors(
        [sparse, rich],
        _portrait(),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    by_id = {item["advisor_id"]: item for item in result.items}
    assert by_id["SYN-SPARSE"]["fit_score"] > 0
    assert by_id["SYN-SPARSE"]["evidence_coverage"] < by_id["SYN-002"][
        "evidence_coverage"
    ]
    assert by_id["SYN-SPARSE"]["score"] < by_id["SYN-002"]["score"]


def test_low_confidence_opportunity_signal_cannot_receive_full_objective_credit():
    candidate = _candidates()[1]
    candidate["opportunity_signals"][0]["confidence"] = 0.1
    opportunity_only = RankingConfig(
        weights=RankingWeights(
            topic_fit=0,
            research_mode_fit=0,
            mentorship_fit=0,
            career_fit=0,
            innovation_fit=0,
            opportunity_fit=1,
        ),
        minimum_recall_score=0,
    )
    item = match_mentors(
        [candidate],
        _portrait(),
        opportunity_only,
        as_of=AS_OF,
    ).items[0]
    assert item["fit_score"] == pytest.approx(90)
    assert item["evidence_confidence"] == pytest.approx(0.1)
    assert item["score"] == pytest.approx(9)


def test_matching_response_redacts_private_provenance_fields():
    candidate = _candidates()[1]
    private_evidence_id = uuid4()
    candidate["provenance"]["field"] = [
        {
            "evidence_id": str(private_evidence_id),
            "source_type": "authorized_message",
            "source_ref": "message:123",
            "captured_at": "2026-07-20T08:00:00+00:00",
            "verification_status": "verified",
            "consent_id": "consent-secret",
            "confidence": 0.8,
            "method": "private-method-detail",
        }
    ]
    item = match_mentors(
        [candidate],
        _portrait(),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    ).items[0]
    serialized = json.dumps(item, ensure_ascii=False)
    assert "message:123" not in serialized
    assert "consent-secret" not in serialized
    assert "private-method-detail" not in serialized
    assert f"ev_{private_evidence_id.hex}" in serialized


def test_only_active_sourced_opportunity_signals_are_ranked_and_returned():
    candidate = _candidates()[1]
    candidate["opportunity_signals"].append(
        _signal(
            "expired-signal",
            effect=1,
            valid_until="2026-06-30T00:00:00+00:00",
        )
    )
    result = match_mentors(
        [candidate],
        _portrait(),
        RankingConfig(minimum_recall_score=0),
        as_of=AS_OF,
    )
    item = result.items[0]
    assert [signal["signal_id"] for signal in item["opportunity_signals"]] == [
        "signal-b"
    ]
    assert any(
        "expired-signal 已过期" in text
        for text in item["explanation"]["uncertainties"]
    )
    opportunity = next(
        row
        for row in item["score_breakdown"]
        if row["objective"] == "opportunity_fit"
    )
    assert opportunity["score"] == pytest.approx(0.9)


def test_opportunity_signal_rejects_missing_source_or_naive_time():
    invalid = _signal("invalid", effect=0.5)
    invalid["supporting_evidence"][0]["sources"] = []
    with pytest.raises(ValidationError):
        OpportunitySignal.model_validate(invalid)

    invalid = _signal("invalid-time", effect=0.5)
    invalid["observed_from"] = "2025-07-01T00:00:00"
    with pytest.raises(ValidationError):
        OpportunitySignal.model_validate(invalid)


def test_zero_candidates_is_an_honest_empty_pipeline():
    result = match_mentors([], _portrait(), as_of=AS_OF)
    assert result.items == []
    assert result.meta["input_candidates"] == 0
    assert result.meta["after_hard_constraints"] == 0
    assert result.meta["recalled_candidates"] == 0
    assert result.meta["ranked"] == 0
    assert result.meta["method_version"] == "evidence-matching-v1"


def test_ranking_weights_must_have_a_non_zero_total():
    with pytest.raises(ValidationError):
        RankingWeights(
            topic_fit=0,
            research_mode_fit=0,
            mentorship_fit=0,
            career_fit=0,
            innovation_fit=0,
            opportunity_fit=0,
        )
