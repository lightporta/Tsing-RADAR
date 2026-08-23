"""A7 offline evaluation and learned-ranking data-readiness gate.

Synthetic fixtures validate deterministic contracts and failure behavior only.
They are not evidence of recommendation accuracy on real users.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.feedback import Feedback
from app.models.questionnaire_session import QuestionnaireSession
from app.schemas.matching import RankingConfig
from app.services.matching import (
    keyword_overlap_baseline,
    lexical_concept_similarity,
    match_mentors,
)

EVALUATION_VERSION = "a7-synthetic-contract-v1"
DATA_READINESS_VERSION = "a7-learning-readiness-v1"


def assess_learning_readiness(db: Session) -> dict[str, Any]:
    """Fail closed until consented exposure/outcome labels actually exist."""
    feedback_count = int(db.query(func.count(Feedback.feedback_id)).scalar() or 0)
    feedback_subjects = int(
        db.query(func.count(func.distinct(Feedback.student_id))).scalar() or 0
    )
    positive_count = int(
        db.query(func.count(Feedback.feedback_id))
        .filter(Feedback.rating == 1)
        .scalar()
        or 0
    )
    negative_count = int(
        db.query(func.count(Feedback.feedback_id))
        .filter(Feedback.rating == -1)
        .scalar()
        or 0
    )
    confirmed_interviews = int(
        db.query(func.count(QuestionnaireSession.session_id))
        .filter(QuestionnaireSession.status == "confirmed")
        .scalar()
        or 0
    )

    # The current schema records preference feedback and confirmed interviews,
    # not consented real-world outcomes tied to a recommendation exposure.
    checks = {
        "explicit_training_consent_recorded": False,
        "recommendation_exposure_join_key_present": False,
        "real_outcome_label_present": False,
        "temporal_holdout_possible": False,
        "minimum_consenting_subjects_met": False,
        "minimum_labeled_outcomes_met": False,
        "class_balance_met": False,
        "privacy_and_bias_review_complete": False,
    }
    reason_codes = [
        "no_explicit_training_consent_field",
        "no_recommendation_exposure_outcome_link",
        "no_real_outcome_label",
        "no_temporal_holdout",
        "minimum_consenting_subjects_not_met",
        "minimum_labeled_outcomes_not_met",
        "class_balance_not_established",
        "privacy_bias_review_not_complete",
    ]
    return {
        "schema_version": DATA_READINESS_VERSION,
        "status": "blocked",
        "learned_ranking_enabled": False,
        "activation_effect": "none",
        "checks": checks,
        "reason_codes": reason_codes,
        "observed_non_training_counts": {
            "preference_feedback": feedback_count,
            "feedback_subjects": feedback_subjects,
            "positive_preferences": positive_count,
            "negative_preferences": negative_count,
            "confirmed_interviews": confirmed_interviews,
        },
        "minimum_thresholds_if_schema_is_upgraded": {
            "consenting_subjects": 100,
            "labeled_outcomes": 500,
            "positive_outcomes": 50,
            "negative_outcomes": 50,
            "observation_days": 30,
        },
        "warning": (
            "Preference feedback and interview completion are not real outcome "
            "labels and must not train or activate ranking weights."
        ),
    }


def _source(path: str, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "evidence_id": str(uuid4()),
        "source_type": "public_fact",
        "source_ref": f"https://synthetic.example.edu/{path}",
        "captured_at": "2026-07-31T00:00:00+00:00",
        "verification_status": "verified",
        "confidence": confidence,
    }


def _candidate(
    advisor_id: str,
    *,
    department: str,
    field: str,
    complete: bool,
    location: str = "北京",
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "advisor_id": advisor_id,
        "name": f"Synthetic candidate {advisor_id}",
        "dept": department,
        "field": field,
        "tags": ["NLP"],
        "locations": [location],
        "weekly_commitment_days": 4,
    }
    if complete:
        values.update(
            {
                "research_modes": ["engineering"],
                "mentorship_styles": ["high_guidance"],
                "career_orientations": ["industry"],
                "innovation_profiles": ["pioneering"],
            }
        )
    values["provenance"] = {
        key: [_source(f"{advisor_id}/{key}")]
        for key in values
        if key not in {"advisor_id", "provenance"}
    }
    return values


def _portrait(*, unresolved: bool = False) -> dict[str, Any]:
    return {
        "research_interests": ["自然语言处理", "对话系统"],
        "interest_statement": "面向真实场景的 NLP 系统",
        "research_mode": "engineering",
        "mentorship_style": "high_guidance",
        "career_orientation": "industry",
        "innovation_risk": "pioneering",
        "hard_constraints": [
            {
                "field": "location",
                "operator": "one_of",
                "value": ["北京"],
                "source_text": "只能北京",
            }
        ],
        "unresolved_hard_constraints": ["离宿舍近"] if unresolved else [],
    }


def run_synthetic_contract_evaluation(
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Run deterministic local fixtures without reading or writing user data."""
    as_of = as_of or datetime(2026, 7, 31, tzinfo=timezone.utc)
    candidates = [
        _candidate(
            "SYN-RICH",
            department="计算机系",
            field="自然语言处理、深度学习与对话系统",
            complete=True,
        ),
        _candidate(
            "SYN-SPARSE",
            department="计算机系",
            field="自然语言处理、深度学习与对话系统",
            complete=False,
        ),
        _candidate(
            "SYN-REMOTE-HIGH-RECALL",
            department="计算机系",
            field="自然语言处理、NLP、大语言模型与对话系统",
            complete=True,
            location="上海",
        ),
    ]

    baseline = keyword_overlap_baseline("NLP", "自然语言处理与对话系统")
    synonym_score, _ = lexical_concept_similarity("机器学习", "深度学习方法")
    false_overlap_score, _ = lexical_concept_similarity(
        "机器学习", "学习机器的维修规程"
    )
    concept_score, _ = lexical_concept_similarity(
        "NLP", "自然语言处理与对话系统"
    )

    ranked = match_mentors(
        candidates,
        _portrait(),
        RankingConfig(minimum_recall_score=0),
        as_of=as_of,
    )
    ranked_by_id = {item["advisor_id"]: item for item in ranked.items}
    clarification = match_mentors(
        candidates,
        _portrait(unresolved=True),
        RankingConfig(minimum_recall_score=0),
        as_of=as_of,
    )
    empty = match_mentors(
        [],
        _portrait(),
        RankingConfig(minimum_recall_score=0),
        as_of=as_of,
    )

    assertions = [
        {
            "id": "keyword_baseline_misses_synonym",
            "passed": baseline == 0,
            "observed": {"keyword_baseline_score": baseline},
        },
        {
            "id": "lexical_fallback_maps_versioned_concept",
            "passed": concept_score > baseline,
            "observed": {
                "keyword_baseline_score": baseline,
                "lexical_fallback_score": concept_score,
            },
        },
        {
            "id": "synonym_beats_surface_false_overlap",
            "passed": synonym_score > false_overlap_score,
            "observed": {
                "synonym_score": synonym_score,
                "false_overlap_score": false_overlap_score,
            },
        },
        {
            "id": "hard_constraints_precede_recall",
            "passed": (
                ranked.meta["input_candidates"] == 3
                and ranked.meta["after_hard_constraints"] == 2
                and ranked.meta["excluded_by_hard_constraints"] == 1
                and "SYN-REMOTE-HIGH-RECALL" not in ranked_by_id
            ),
            "observed": {
                "input_candidates": ranked.meta["input_candidates"],
                "after_hard_constraints": ranked.meta[
                    "after_hard_constraints"
                ],
                "excluded_by_hard_constraints": ranked.meta[
                    "excluded_by_hard_constraints"
                ],
                "high_recall_constraint_violation_returned": (
                    "SYN-REMOTE-HIGH-RECALL" in ranked_by_id
                ),
            },
        },
        {
            "id": "sparse_evidence_is_conservatively_penalized",
            "passed": (
                ranked_by_id["SYN-RICH"]["score"]
                > ranked_by_id["SYN-SPARSE"]["score"]
                and ranked_by_id["SYN-RICH"]["evidence_coverage"]
                > ranked_by_id["SYN-SPARSE"]["evidence_coverage"]
            ),
            "observed": {
                "rich_score": ranked_by_id["SYN-RICH"]["score"],
                "sparse_score": ranked_by_id["SYN-SPARSE"]["score"],
                "rich_coverage": ranked_by_id["SYN-RICH"][
                    "evidence_coverage"
                ],
                "sparse_coverage": ranked_by_id["SYN-SPARSE"][
                    "evidence_coverage"
                ],
            },
        },
        {
            "id": "unresolved_constraint_fails_closed",
            "passed": (
                clarification.meta["status"] == "needs_clarification"
                and not clarification.items
            ),
            "observed": {
                "status": clarification.meta["status"],
                "result_count": len(clarification.items),
            },
        },
        {
            "id": "zero_candidates_is_honest_empty",
            "passed": (
                empty.meta["status"] == "ready"
                and empty.meta["input_candidates"] == 0
                and not empty.items
            ),
            "observed": {
                "status": empty.meta["status"],
                "input_candidates": empty.meta["input_candidates"],
                "result_count": len(empty.items),
            },
        },
    ]
    passed = sum(1 for item in assertions if item["passed"])
    return {
        "schema_version": EVALUATION_VERSION,
        "fixture_classification": "synthetic_only",
        "retrieval_mode": "deterministic_lexical_fallback",
        "real_recommendation_accuracy_measured": False,
        "learned_ranking_evaluated": False,
        "assertions": assertions,
        "summary": {
            "total": len(assertions),
            "passed": passed,
            "failed": len(assertions) - passed,
            "status": "passed" if passed == len(assertions) else "failed",
        },
        "claim_limit": (
            "Passing results establish local contract and failure-state "
            "behavior only; they do not establish real recommendation quality."
        ),
    }
