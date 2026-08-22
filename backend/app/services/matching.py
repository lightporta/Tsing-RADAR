"""A4 证据化导师匹配流水线。

顺序固定为：硬约束（失败关闭）→ 透明语义召回 → 显式多目标排序 →
证据/反证/不确定性解释。服务不会为缺失的导师事实、主观评分或机会信号
补默认值，也不会读取尚未达到训练条件的反馈模型。
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from app.schemas.governance import (
    ProvenanceEntry,
    SourceType,
    VerificationStatus,
    public_citation,
)
from app.schemas.interview import (
    HardConstraint,
    HardConstraintField,
    HardConstraintOperator,
)
from app.schemas.matching import (
    EvidenceClaim,
    MatchExplanation,
    MatchPipelineMeta,
    MatchedMentor,
    ObjectiveBreakdown,
    OpportunitySignal,
    PublicOpportunitySignal,
    RankingConfig,
    RankingObjective,
    SourcedEvidenceClaim,
)
from app.services.off_topic import CONSTRAINT_JUNK_SIGNALS

logger = logging.getLogger("tsing_radar.matching")

MATCH_METHOD_VERSION = "evidence-matching-v1"
LEXICAL_FALLBACK_METHOD = "deterministic-concept-ngram-lexical-v1"

_CJK_SEQUENCE = re.compile(r"[\u3400-\u9fff]+")
_ASCII_TERM = re.compile(r"[a-z0-9][a-z0-9.+#_-]*")
_GENERIC_TERMS = {
    "研究",
    "方向",
    "相关",
    "希望",
    "想做",
    "课题",
    "项目",
    "系统",
    "the",
    "and",
    "research",
}

# 这是版本化的检索词典，不是对导师或领域的评价数据。它只把常见同义表达
# 映射到同一召回概念，最终命中的导师文本仍必须带 A2 字段级来源。
_CONCEPT_LEXICON: dict[str, tuple[str, ...]] = {
    "natural_language_processing": (
        "自然语言处理",
        "nlp",
        "语言模型",
        "大语言模型",
        "llm",
        "文本挖掘",
        "对话系统",
    ),
    "computer_vision": (
        "计算机视觉",
        "computer vision",
        "cv",
        "图像识别",
        "视觉感知",
    ),
    "machine_learning": (
        "机器学习",
        "machine learning",
        "ml",
        "深度学习",
        "deep learning",
    ),
    "robotics": (
        "机器人",
        "robotics",
        "具身智能",
        "运动控制",
        "自主系统",
    ),
    "biomedical_engineering": (
        "生物医学工程",
        "医学工程",
        "医疗器械",
        "生物制造",
        "再生医学",
    ),
    "advanced_manufacturing": (
        "先进制造",
        "智能制造",
        "增材制造",
        "制造自动化",
    ),
    "control_and_automation": (
        "控制科学",
        "自动化",
        "控制理论",
        "系统控制",
    ),
    "integrated_circuits": (
        "集成电路",
        "芯片",
        "半导体",
        "ic design",
        "eda",
    ),
}

_CATEGORICAL_FIELDS: tuple[
    tuple[RankingObjective, str, str, str],
    ...,
] = (
    (
        RankingObjective.RESEARCH_MODE_FIT,
        "research_mode",
        "research_modes",
        "研究方式",
    ),
    (
        RankingObjective.MENTORSHIP_FIT,
        "mentorship_style",
        "mentorship_styles",
        "指导方式",
    ),
    (
        RankingObjective.CAREER_FIT,
        "career_orientation",
        "career_orientations",
        "生涯去向",
    ),
    (
        RankingObjective.INNOVATION_FIT,
        "innovation_risk",
        "innovation_profiles",
        "创新风险",
    ),
)

_CONSTRAINT_LABELS: dict[HardConstraintField, str] = {
    HardConstraintField.LOCATION: "地点",
    HardConstraintField.WEEKLY_COMMITMENT_DAYS: "每周投入天数",
    HardConstraintField.DEGREE_STAGE: "学历阶段",
    HardConstraintField.LANGUAGE: "语言",
    HardConstraintField.CONFIDENTIALITY: "保密要求",
    HardConstraintField.GRADUATION_ARRANGEMENT: "毕业安排",
    HardConstraintField.DEPARTMENT: "院系",
    HardConstraintField.RESEARCH_TOPIC: "研究主题",
    HardConstraintField.ADVISOR_ID: "导师 ID",
}

_CONSTRAINT_OPERATORS: dict[
    HardConstraintField, tuple[HardConstraintOperator, ...]
] = {
    HardConstraintField.WEEKLY_COMMITMENT_DAYS: (
        HardConstraintOperator.EQUALS,
        HardConstraintOperator.MINIMUM,
        HardConstraintOperator.MAXIMUM,
    ),
    HardConstraintField.RESEARCH_TOPIC: (
        HardConstraintOperator.CONTAINS,
        HardConstraintOperator.EXCLUDES,
    ),
    HardConstraintField.ADVISOR_ID: (
        HardConstraintOperator.EQUALS,
        HardConstraintOperator.ONE_OF,
        HardConstraintOperator.EXCLUDES,
    ),
}
_DEFAULT_CONSTRAINT_OPERATORS = (
    HardConstraintOperator.EQUALS,
    HardConstraintOperator.ONE_OF,
    HardConstraintOperator.EXCLUDES,
    HardConstraintOperator.CONTAINS,
)


@dataclass
class ParsedHardConstraints:
    constraints: list[HardConstraint] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


@dataclass
class MatchPipelineResult:
    items: list[dict[str, Any]]
    meta: dict[str, Any]


@dataclass
class RecallHit:
    candidate: dict[str, Any]
    score: float
    matched_features: list[str]
    topic_fields: list[str]


class RecallProvider(Protocol):
    """可插拔召回接口；可靠 embedding provider 可与词法回退做混合。"""

    name: str
    mode: str

    def score(self, query: str, document: str) -> tuple[float, list[str]]:
        ...


class DeterministicLexicalRecall:
    name = LEXICAL_FALLBACK_METHOD
    mode = "deterministic_lexical_fallback"

    def score(self, query: str, document: str) -> tuple[float, list[str]]:
        return lexical_concept_similarity(query, document)


class HybridRecallProvider:
    """词法回退 + 可选可靠语义 provider 的显式混合器。"""

    mode = "hybrid"

    def __init__(
        self,
        semantic_provider: RecallProvider,
        *,
        semantic_weight: float = 0.7,
    ) -> None:
        if not 0 < semantic_weight <= 1:
            raise ValueError("semantic_weight 必须在 (0, 1] 内")
        self.semantic_provider = semantic_provider
        self.lexical_provider = DeterministicLexicalRecall()
        self.semantic_weight = semantic_weight
        self.name = (
            f"hybrid:{semantic_provider.name}+{self.lexical_provider.name}"
        )

    def score(self, query: str, document: str) -> tuple[float, list[str]]:
        semantic_score, semantic_features = self.semantic_provider.score(
            query, document
        )
        lexical_score, lexical_features = self.lexical_provider.score(
            query, document
        )
        combined = (
            semantic_score * self.semantic_weight
            + lexical_score * (1 - self.semantic_weight)
        )
        return round(combined, 6), list(
            dict.fromkeys([*semantic_features, *lexical_features])
        )[:5]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """普通余弦相似度；只用于可解释的共享特征向量。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    numerator = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return numerator / (norm_a * norm_b) if norm_a and norm_b else 0.0


def hash_embedding(text: str, dim: int = 128) -> list[float]:
    """兼容旧向量接口的“词项特征哈希”，不是整段文本伪随机向量。

    相同词项会落入相同维度，因此相似度来自可检查的词项/概念重合。A4
    匹配主链直接使用下方的稀疏特征，不依赖此兼容表示。
    """
    if dim <= 0:
        return []
    vector = [0.0] * dim
    for feature_name, weight in _retrieval_features(text).items():
        digest = hashlib.sha256(feature_name.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _retrieval_features(text: str) -> Counter[str]:
    normalized = _normalize_text(text)
    features: Counter[str] = Counter()
    if not normalized:
        return features

    for term in _ASCII_TERM.findall(normalized):
        if len(term) >= 2 and term not in _GENERIC_TERMS:
            features[f"term:{term}"] += 2.0

    for sequence in _CJK_SEQUENCE.findall(normalized):
        if len(sequence) >= 2 and sequence not in _GENERIC_TERMS:
            features[f"phrase:{sequence}"] += 2.0
        for width in (2, 3):
            for index in range(max(0, len(sequence) - width + 1)):
                gram = sequence[index : index + width]
                if gram not in _GENERIC_TERMS:
                    features[f"ngram:{gram}"] += 1.0

    compact = normalized.replace(" ", "")
    for concept, aliases in _CONCEPT_LEXICON.items():
        if any(alias.lower().replace(" ", "") in compact for alias in aliases):
            features[f"concept:{concept}"] += 3.0
    return features


def keyword_overlap_baseline(query: str, document: str) -> float:
    """仅计算完整 ASCII/CJK 片段重合的朴素关键词基线。"""
    query_terms = {
        *_ASCII_TERM.findall(_normalize_text(query)),
        *_CJK_SEQUENCE.findall(_normalize_text(query)),
    }
    document_terms = {
        *_ASCII_TERM.findall(_normalize_text(document)),
        *_CJK_SEQUENCE.findall(_normalize_text(document)),
    }
    if not query_terms:
        return 0.0
    return len(query_terms & document_terms) / len(query_terms)


def lexical_concept_similarity(
    query: str, document: str
) -> tuple[float, list[str]]:
    """确定性词法/概念回退分，不宣称为 embedding 语义相似度。"""
    query_features = _retrieval_features(query)
    document_features = _retrieval_features(document)
    if not query_features or not document_features:
        return 0.0, []
    shared = set(query_features) & set(document_features)
    numerator = sum(query_features[key] * document_features[key] for key in shared)
    query_norm = math.sqrt(sum(value * value for value in query_features.values()))
    document_norm = math.sqrt(
        sum(value * value for value in document_features.values())
    )
    score = numerator / (query_norm * document_norm)
    ranked_features = sorted(
        shared,
        key=lambda key: (
            query_features[key] * document_features[key],
            key,
        ),
        reverse=True,
    )
    readable = [
        feature.split(":", 1)[1]
        for feature in ranked_features
        if feature.startswith(("concept:", "term:", "phrase:"))
    ]
    if not readable:
        readable = [
            feature.split(":", 1)[1] for feature in ranked_features[:5]
        ]
    return round(max(0.0, min(1.0, score)), 6), readable[:5]


def _parse_sources(candidate: dict[str, Any], field_name: str) -> list[ProvenanceEntry]:
    parsed: list[ProvenanceEntry] = []
    for raw in (candidate.get("provenance", {}) or {}).get(field_name, []):
        try:
            source = (
                raw
                if isinstance(raw, ProvenanceEntry)
                else ProvenanceEntry.model_validate(raw)
            )
        except (TypeError, ValueError):
            continue
        if (
            source.verification_status == VerificationStatus.VERIFIED
            and source.source_type != SourceType.UNKNOWN
        ):
            parsed.append(source)
    return parsed


def _source_backed_value(
    candidate: dict[str, Any], field_name: str
) -> tuple[Any | None, list[ProvenanceEntry]]:
    sources = _parse_sources(candidate, field_name)
    if not sources or field_name not in candidate:
        return None, []
    return candidate[field_name], sources


def _unique_sources(sources: Iterable[ProvenanceEntry]) -> list[ProvenanceEntry]:
    unique: dict[tuple[str, str, str], ProvenanceEntry] = {}
    for source in sources:
        key = (
            source.source_type.value,
            source.source_ref,
            source.captured_at.isoformat(),
        )
        unique[key] = source
    return list(unique.values())


def _claim(
    statement: str,
    candidate: dict[str, Any],
    fields: Iterable[str],
) -> SourcedEvidenceClaim | None:
    sources = _unique_sources(
        source
        for field_name in fields
        for source in _parse_sources(candidate, field_name)
    )
    if not sources:
        return None
    return SourcedEvidenceClaim(statement=statement, sources=sources)


def _public_claim(
    claim: SourcedEvidenceClaim,
    *,
    context: str,
) -> EvidenceClaim:
    return EvidenceClaim(
        statement=claim.statement,
        citations=[
            public_citation(source, context=f"{context}:{index}")
            for index, source in enumerate(claim.sources)
        ],
    )


def parse_hard_constraints(portrait: dict[str, Any]) -> ParsedHardConstraints:
    """读取用户已确认的结构化约束；旧自然语言只保留为 unresolved。"""
    parsed = ParsedHardConstraints(
        unresolved=list(
            dict.fromkeys(
                [
                    *[
                        str(item).strip()
                        for item in portrait.get(
                            "unresolved_hard_constraints"
                        )
                        or []
                        if str(item).strip()
                    ],
                    *[
                        str(item.get("source_text", "")).strip()
                        for item in portrait.get(
                            "draft_hard_constraints"
                        )
                        or []
                        if isinstance(item, dict)
                        and str(item.get("source_text", "")).strip()
                    ],
                ]
            )
        )
    )
    for raw in portrait.get("hard_constraints") or []:
        try:
            constraint = (
                raw
                if isinstance(raw, HardConstraint)
                else HardConstraint.model_validate(raw)
            )
        except (TypeError, ValueError):
            parsed.unresolved.append(str(raw))
            continue
        parsed.constraints.append(constraint)
        parsed.applied.append(
            (
                f"{constraint.field.value}|{constraint.operator.value}|"
                f"{'/'.join(constraint.value)}"
            )
        )
    # v4.2.x 修复1 第三层消毒：幽灵值（确认指令/态度词/开场白残留）直接丢弃，
    # 绝不参与硬过滤。访谈层（修复1 前两层）已拦截大部分，这里是匹配前的
    # 最后一道防线（防旧数据/防旁路写入）。
    kept: list[tuple[HardConstraint, str]] = []
    for constraint, applied in zip(parsed.constraints, parsed.applied):
        joined = "".join(constraint.value)
        if any(junk in joined for junk in CONSTRAINT_JUNK_SIGNALS):
            logger.warning(
                "hard_constraint_junk_value_dropped: %s", joined
            )
            continue
        kept.append((constraint, applied))
    parsed.constraints = [constraint for constraint, _ in kept]
    parsed.applied = [applied for _, applied in kept]
    return parsed


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _topic_document(
    candidate: dict[str, Any],
) -> tuple[str, list[str]]:
    values: list[str] = []
    fields: list[str] = []
    for field_name in ("field", "tags", "research_keywords", "research_summary"):
        value, sources = _source_backed_value(candidate, field_name)
        if value is None or not sources:
            continue
        text_values = _as_text_list(value)
        if text_values:
            values.extend(text_values)
            fields.append(field_name)
    return " ".join(values), fields


def _constraint_candidate_value(
    candidate: dict[str, Any],
    field_name: HardConstraintField,
) -> tuple[Any | None, bool]:
    if field_name == HardConstraintField.ADVISOR_ID:
        return candidate.get("advisor_id"), bool(candidate.get("advisor_id"))
    if field_name == HardConstraintField.RESEARCH_TOPIC:
        document, topic_fields = _topic_document(candidate)
        return document, bool(topic_fields)
    candidate_fields: dict[HardConstraintField, tuple[str, ...]] = {
        HardConstraintField.LOCATION: ("locations", "office_loc"),
        HardConstraintField.WEEKLY_COMMITMENT_DAYS: (
            "weekly_commitment_days",
        ),
        HardConstraintField.DEGREE_STAGE: ("degree_stages",),
        HardConstraintField.LANGUAGE: ("languages",),
        HardConstraintField.CONFIDENTIALITY: ("confidentiality",),
        HardConstraintField.GRADUATION_ARRANGEMENT: (
            "graduation_arrangements",
        ),
        HardConstraintField.DEPARTMENT: ("dept",),
    }
    values: list[Any] = []
    for candidate_field in candidate_fields.get(field_name, ()):
        value, sources = _source_backed_value(candidate, candidate_field)
        if value is not None and sources:
            values.extend(value if isinstance(value, list) else [value])
    if not values:
        return None, False
    return values, True


def hard_constraint_capabilities(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive the editor contract from evidence actually present today."""
    total = len(candidates)
    fields: list[dict[str, Any]] = []
    for field_name in HardConstraintField:
        values: list[str] = []
        evidence_records = 0
        for candidate in candidates:
            value, has_evidence = _constraint_candidate_value(candidate, field_name)
            if not has_evidence:
                continue
            evidence_records += 1
            if field_name not in {
                HardConstraintField.RESEARCH_TOPIC,
                HardConstraintField.ADVISOR_ID,
            }:
                values.extend(
                    str(item).strip()
                    for item in (value if isinstance(value, list) else [value])
                    if str(item).strip()
                )
        available = evidence_records > 0
        fields.append(
            {
                "field": field_name.value,
                "label": _CONSTRAINT_LABELS[field_name],
                "available": available,
                "evidence_record_count": evidence_records,
                "candidate_count": total,
                "evidence_coverage": round(evidence_records / total, 6)
                if total
                else 0.0,
                "operators": [
                    item.value
                    for item in _CONSTRAINT_OPERATORS.get(
                        field_name, _DEFAULT_CONSTRAINT_OPERATORS
                    )
                ],
                "values": sorted(set(values))[:200],
                "accepts_free_text": field_name
                in {
                    HardConstraintField.RESEARCH_TOPIC,
                    HardConstraintField.ADVISOR_ID,
                },
                "unavailable_reason": None
                if available
                else "当前已发布导师数据没有该字段的可核验证据",
            }
        )
    return {
        "version": "hard-constraints-v1",
        "candidate_count": total,
        "fields": fields,
        "basis": "published_verified_candidate_fields",
    }


def _constraint_satisfied(
    candidate: dict[str, Any],
    constraint: HardConstraint,
) -> bool:
    raw_candidate_value, has_evidence = _constraint_candidate_value(
        candidate, constraint.field
    )
    if not has_evidence:
        return False
    if constraint.field == HardConstraintField.RESEARCH_TOPIC:
        document = str(raw_candidate_value)
        matches = [
            lexical_concept_similarity(value, document)[0] > 0
            for value in constraint.value
        ]
        return (
            not any(matches)
            if constraint.operator == HardConstraintOperator.EXCLUDES
            else any(matches)
        )
    if constraint.operator in {
        HardConstraintOperator.MINIMUM,
        HardConstraintOperator.MAXIMUM,
    }:
        try:
            candidate_number = float(
                raw_candidate_value[0]
                if isinstance(raw_candidate_value, list)
                else raw_candidate_value
            )
            required_number = float(constraint.value[0])
        except (TypeError, ValueError):
            return False
        if constraint.operator == HardConstraintOperator.MINIMUM:
            return candidate_number >= required_number
        return candidate_number <= required_number

    candidate_values = {
        _normalize_text(value)
        for value in (
            raw_candidate_value
            if isinstance(raw_candidate_value, list)
            else [raw_candidate_value]
        )
    }
    expected_values = {_normalize_text(value) for value in constraint.value}
    if constraint.operator == HardConstraintOperator.EXCLUDES:
        return not bool(candidate_values & expected_values)
    if constraint.operator in {
        HardConstraintOperator.EQUALS,
        HardConstraintOperator.ONE_OF,
    }:
        return bool(candidate_values & expected_values)
    if constraint.operator == HardConstraintOperator.CONTAINS:
        return any(
            expected in candidate_value
            for candidate_value in candidate_values
            for expected in expected_values
        )
    return False


def _passes_hard_constraints(
    candidate: dict[str, Any],
    constraints: ParsedHardConstraints,
) -> bool:
    return all(
        _constraint_satisfied(candidate, constraint)
        for constraint in constraints.constraints
    )


def _profile_query(portrait: dict[str, Any]) -> str:
    parts = _as_text_list(portrait.get("research_interests"))
    statement = portrait.get("interest_statement")
    if statement:
        parts.append(str(statement))
    return " ".join(parts)


def _compatibility_score(
    objective: RankingObjective,
    student_value: str,
    candidate_values: set[str],
) -> tuple[float, str]:
    if student_value in candidate_values:
        return 1.0, "exact-category-v1"

    if objective == RankingObjective.RESEARCH_MODE_FIT:
        if student_value == "mixed" or "mixed" in candidate_values:
            return 0.7, "mixed-bridge-v1"
    elif objective == RankingObjective.MENTORSHIP_FIT:
        if student_value == "balanced" or "balanced" in candidate_values:
            return 0.6, "balanced-bridge-v1"
    elif objective == RankingObjective.CAREER_FIT:
        if student_value == "mixed" or "mixed" in candidate_values:
            return 0.7, "mixed-bridge-v1"
    elif objective == RankingObjective.INNOVATION_FIT:
        if student_value == "balanced" or "balanced" in candidate_values:
            return 0.6, "balanced-bridge-v1"
    return 0.0, "category-mismatch-v1"


def _active_opportunity_signals(
    candidate: dict[str, Any],
    as_of: datetime,
) -> tuple[list[OpportunitySignal], list[str]]:
    raw_signals, field_sources = _source_backed_value(
        candidate, "opportunity_signals"
    )
    if raw_signals is None or not field_sources:
        return [], ["缺少带字段级来源的机会信号，机会维度未参与排序。"]

    active: list[OpportunitySignal] = []
    uncertainties: list[str] = []
    for raw in raw_signals if isinstance(raw_signals, list) else []:
        try:
            signal = (
                raw
                if isinstance(raw, OpportunitySignal)
                else OpportunitySignal.model_validate(raw)
            )
        except (TypeError, ValueError):
            uncertainties.append("存在未通过来源或时间窗校验的机会信号，已忽略。")
            continue
        if signal.observed_from > as_of:
            uncertainties.append(f"机会信号 {signal.signal_id} 尚未进入观测窗口。")
            continue
        if signal.valid_until < as_of:
            uncertainties.append(f"机会信号 {signal.signal_id} 已过期，未参与排序。")
            continue
        active.append(signal)
    if not active:
        uncertainties.append("当前没有处于有效时间窗内的机会信号。")
    return active, uncertainties


def _opportunity_score(
    signals: list[OpportunitySignal],
) -> tuple[float | None, float]:
    confidence_total = sum(signal.confidence for signal in signals)
    if confidence_total <= 0:
        return None, 0.0
    weighted = sum(
        ((signal.effect + 1.0) / 2.0) * signal.confidence
        for signal in signals
    )
    return (
        round(weighted / confidence_total, 6),
        round(confidence_total / len(signals), 6),
    )


def _weight_map(config: RankingConfig) -> dict[RankingObjective, float]:
    values = config.weights.model_dump()
    return {
        objective: float(values[objective.value])
        for objective in RankingObjective
    }


def _rank_candidate(
    recalled: RecallHit,
    portrait: dict[str, Any],
    config: RankingConfig,
    as_of: datetime,
) -> dict[str, Any]:
    candidate = recalled.candidate
    objective_scores: dict[RankingObjective, float | None] = {
        objective: None for objective in RankingObjective
    }
    objective_scores[RankingObjective.TOPIC_FIT] = recalled.score
    objective_methods: dict[RankingObjective, str] = {
        RankingObjective.TOPIC_FIT: LEXICAL_FALLBACK_METHOD
    }
    objective_fields: dict[RankingObjective, list[str]] = {
        RankingObjective.TOPIC_FIT: recalled.topic_fields
    }
    objective_confidence: dict[RankingObjective, float] = {
        objective: 0.0 for objective in RankingObjective
    }
    topic_sources = _unique_sources(
        source
        for field_name in recalled.topic_fields
        for source in _parse_sources(candidate, field_name)
    )
    if topic_sources:
        objective_confidence[RankingObjective.TOPIC_FIT] = sum(
            source.confidence for source in topic_sources
        ) / len(topic_sources)
    supporting_internal: list[SourcedEvidenceClaim] = []
    counter_internal: list[SourcedEvidenceClaim] = []
    uncertainties: list[str] = []
    questions: list[str] = []

    topic_claim = _claim(
        (
            f"研究主题召回得分为 {recalled.score:.3f}"
            + (
                f"，共享概念/词项：{', '.join(recalled.matched_features)}。"
                if recalled.matched_features
                else "。"
            )
        ),
        candidate,
        recalled.topic_fields,
    )
    if topic_claim is not None:
        if recalled.score >= 0.35:
            supporting_internal.append(topic_claim)
        else:
            counter_internal.append(topic_claim)

    for objective, profile_field, candidate_field, label in _CATEGORICAL_FIELDS:
        student_value = portrait.get(profile_field)
        if not student_value or student_value == "undecided":
            uncertainties.append(f"学生画像中的{label}尚未确定，该维度未参与排序。")
            questions.append(f"请确认你偏好的{label}。")
            continue
        raw_values, sources = _source_backed_value(candidate, candidate_field)
        candidate_values = {
            _normalize_text(value) for value in _as_text_list(raw_values)
        }
        if not sources or not candidate_values:
            uncertainties.append(
                f"导师候选缺少有来源的{label}信息，该维度未参与排序。"
            )
            questions.append(f"请向导师或课题组核实{label}。")
            continue
        score, method = _compatibility_score(
            objective, _normalize_text(student_value), candidate_values
        )
        objective_scores[objective] = score
        objective_confidence[objective] = sum(
            source.confidence for source in sources
        ) / len(sources)
        objective_methods[objective] = method
        objective_fields[objective] = [candidate_field]
        claim = _claim(
            (
                f"{label}：学生偏好为 {student_value}，"
                f"候选公开信息为 {', '.join(sorted(candidate_values))}，"
                f"规则得分 {score:.2f}。"
            ),
            candidate,
            [candidate_field],
        )
        if claim is not None:
            (
                supporting_internal
                if score >= 0.6
                else counter_internal
            ).append(claim)

    active_signals, signal_uncertainties = _active_opportunity_signals(
        candidate, as_of
    )
    uncertainties.extend(signal_uncertainties)
    opportunity_score, opportunity_confidence = _opportunity_score(active_signals)
    objective_scores[RankingObjective.OPPORTUNITY_FIT] = opportunity_score
    objective_confidence[RankingObjective.OPPORTUNITY_FIT] = (
        opportunity_confidence
    )
    objective_methods[RankingObjective.OPPORTUNITY_FIT] = (
        "confidence-weighted-signed-signals-v1"
    )
    objective_fields[RankingObjective.OPPORTUNITY_FIT] = (
        ["opportunity_signals"] if active_signals else []
    )
    if opportunity_score is None:
        questions.append("请核实该方向近期机会信号及其时间窗。")
    for signal in active_signals:
        target = (
            supporting_internal
            if signal.effect >= 0
            else counter_internal
        )
        target.extend(signal.supporting_evidence)
        counter_internal.extend(signal.counter_evidence)

    requested_weights = _weight_map(config)
    configured_weight_total = sum(requested_weights.values())
    available_weight_total = sum(
        requested_weights[objective]
        for objective, score in objective_scores.items()
        if score is not None
    )
    breakdown: list[ObjectiveBreakdown] = []
    fit_numerator = 0.0
    confidence_numerator = 0.0
    for objective in RankingObjective:
        score = objective_scores[objective]
        requested_weight = requested_weights[objective]
        effective_weight = (
            requested_weight / configured_weight_total
            if configured_weight_total > 0
            else 0
        )
        if score is not None:
            fit_numerator += score * requested_weight
            confidence_numerator += (
                objective_confidence[objective] * requested_weight
            )
        contribution = (
            score * effective_weight * objective_confidence[objective]
            if score is not None
            else 0.0
        )
        breakdown.append(
            ObjectiveBreakdown(
                objective=objective,
                score=score,
                requested_weight=requested_weight,
                effective_weight=round(effective_weight, 6),
                method=objective_methods.get(objective, "not-scored"),
                evidence_fields=objective_fields.get(objective, []),
                evidence_coverage=1.0 if score is not None else 0.0,
                evidence_confidence=round(
                    objective_confidence[objective], 6
                ),
                conservative_contribution=round(contribution, 6),
            )
        )
    evidence_coverage = (
        available_weight_total / configured_weight_total
        if configured_weight_total > 0
        else 0.0
    )
    fit_score = (
        fit_numerator / available_weight_total
        if available_weight_total > 0
        else 0.0
    )
    evidence_confidence = (
        confidence_numerator / available_weight_total
        if available_weight_total > 0
        else 0.0
    )
    conservative_score = fit_score * evidence_coverage * evidence_confidence
    if available_weight_total <= 0:
        uncertainties.append("配置的非零权重维度均无可用证据，综合分保持为 0。")
    elif evidence_coverage < 1:
        uncertainties.append(
            f"加权证据覆盖率为 {evidence_coverage:.1%}，排序分已保守折减。"
        )
    if evidence_confidence < 1:
        uncertainties.append(
            f"可用证据加权置信度为 {evidence_confidence:.1%}，排序分已保守折减。"
        )

    supporting = [
        _public_claim(claim, context=f"{candidate['advisor_id']}:support:{index}")
        for index, claim in enumerate(supporting_internal)
    ]
    counter = [
        _public_claim(claim, context=f"{candidate['advisor_id']}:counter:{index}")
        for index, claim in enumerate(counter_internal)
    ]
    public_signals = [
        PublicOpportunitySignal(
            signal_id=signal.signal_id,
            signal_type=signal.signal_type,
            label=signal.label,
            effect=signal.effect,
            confidence=signal.confidence,
            observed_from=signal.observed_from,
            observed_to=signal.observed_to,
            valid_until=signal.valid_until,
            method=signal.method,
            method_version=signal.method_version,
            supporting_evidence=[
                _public_claim(
                    claim,
                    context=(
                        f"{candidate['advisor_id']}:{signal.signal_id}:"
                        f"support:{index}"
                    ),
                )
                for index, claim in enumerate(signal.supporting_evidence)
            ],
            counter_evidence=[
                _public_claim(
                    claim,
                    context=(
                        f"{candidate['advisor_id']}:{signal.signal_id}:"
                        f"counter:{index}"
                    ),
                )
                for index, claim in enumerate(signal.counter_evidence)
            ],
        )
        for signal in active_signals
    ]

    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"provenance", "opportunity_signals"}
    }
    payload.update(
        {
            "score": round(conservative_score * 100.0, 2),
            "fit_score": round(fit_score * 100.0, 2),
            "evidence_coverage": round(evidence_coverage, 6),
            "evidence_confidence": round(evidence_confidence, 6),
            "recall_score": recalled.score,
            "score_breakdown": [
                item.model_dump(mode="json") for item in breakdown
            ],
            "explanation": MatchExplanation(
                supporting_evidence=supporting,
                counter_evidence=counter,
                uncertainties=list(dict.fromkeys(uncertainties)),
                questions_to_verify=list(dict.fromkeys(questions)),
            ).model_dump(mode="json"),
            "opportunity_signals": [
                signal.model_dump(mode="json") for signal in public_signals
            ],
        }
    )
    return MatchedMentor.model_validate(payload).model_dump(
        mode="json", exclude_none=True
    )


def match_mentors(
    mentors: list[dict[str, Any]],
    portrait: dict[str, Any],
    config: RankingConfig | None = None,
    *,
    as_of: datetime | None = None,
    recall_provider: RecallProvider | None = None,
) -> MatchPipelineResult:
    """执行 A4 流水线并返回结果与可审计元数据。"""
    config = config or RankingConfig()
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of 必须包含时区")
    recall_provider = recall_provider or DeterministicLexicalRecall()

    constraints = parse_hard_constraints(portrait)
    input_count = len(mentors)

    # 无法无损解析的硬约束必须失败关闭，不能假装该约束已经满足。
    if constraints.unresolved:
        meta = MatchPipelineMeta(
            status="needs_clarification",
            method_version=MATCH_METHOD_VERSION,
            retrieval_method=recall_provider.name,
            retrieval_mode=recall_provider.mode,
            input_candidates=input_count,
            after_hard_constraints=0,
            recalled_candidates=0,
            ranked=0,
            applied_hard_constraints=constraints.applied,
            unresolved_hard_constraints=constraints.unresolved,
            clarification_questions=[
                (
                    f"请继续确认“{item}”对应的具体、不可妥协条件。"
                )
                for item in constraints.unresolved
            ],
            excluded_by_hard_constraints=input_count,
            ranking_config=config,
        )
        return MatchPipelineResult(
            items=[], meta=meta.model_dump(mode="json")
        )

    # Apply one condition at a time so a zero result can name the exact
    # condition that exhausted the candidate set.  Missing evidence remains a
    # failure (never an implicit pass) and is counted separately from mismatch.
    filtered = list(mentors)
    constraint_trace: list[dict[str, Any]] = []
    zero_result_reason: str | None = None
    for constraint in constraints.constraints:
        before = filtered
        after: list[dict[str, Any]] = []
        missing_evidence = 0
        mismatched = 0
        for candidate in before:
            _, has_evidence = _constraint_candidate_value(
                candidate, constraint.field
            )
            if not has_evidence:
                missing_evidence += 1
                continue
            if _constraint_satisfied(candidate, constraint):
                after.append(candidate)
            else:
                mismatched += 1
        key = (
            f"{constraint.field.value}|{constraint.operator.value}|"
            f"{'/'.join(constraint.value)}"
        )
        trace = {
            "constraint": key,
            "field": constraint.field.value,
            "operator": constraint.operator.value,
            "values": constraint.value,
            "candidates_before": len(before),
            "candidates_after": len(after),
            "excluded": len(before) - len(after),
            "missing_evidence": missing_evidence,
            "mismatched": mismatched,
        }
        if before and not after:
            if missing_evidence == len(before):
                zero_result_reason = (
                    f"约束“{_CONSTRAINT_LABELS[constraint.field]} "
                    f"{constraint.operator.value} {'/'.join(constraint.value)}”"
                    "归零：当前候选均缺少该字段的已核验证据。"
                )
            else:
                zero_result_reason = (
                    f"约束“{_CONSTRAINT_LABELS[constraint.field]} "
                    f"{constraint.operator.value} {'/'.join(constraint.value)}”"
                    f"归零：{mismatched} 位不符合，{missing_evidence} 位缺少已核验证据。"
                )
            trace["zero_result_reason"] = zero_result_reason
        constraint_trace.append(trace)
        filtered = after
        if not filtered:
            break

    query = _profile_query(portrait)
    recalled: list[RecallHit] = []
    for candidate in filtered:
        document, topic_fields = _topic_document(candidate)
        if not topic_fields:
            continue
        score, matched_features = recall_provider.score(query, document)
        if score < config.minimum_recall_score:
            continue
        recalled.append(
            RecallHit(
                candidate=candidate,
                score=score,
                matched_features=matched_features,
                topic_fields=topic_fields,
            )
        )
    recalled.sort(
        key=lambda item: (
            item.score,
            _normalize_text(item.candidate.get("advisor_id")),
        ),
        reverse=True,
    )
    recalled = recalled[: config.recall_pool_size]

    ranked = [
        _rank_candidate(item, portrait, config, as_of) for item in recalled
    ]
    ranked.sort(
        key=lambda item: (
            float(item["score"]),
            float(item["recall_score"]),
            str(item["advisor_id"]),
        ),
        reverse=True,
    )
    ranked = ranked[: config.result_limit]

    meta = MatchPipelineMeta(
        status="ready",
        method_version=MATCH_METHOD_VERSION,
        retrieval_method=recall_provider.name,
        retrieval_mode=recall_provider.mode,
        input_candidates=input_count,
        after_hard_constraints=len(filtered),
        recalled_candidates=len(recalled),
        ranked=len(ranked),
        applied_hard_constraints=constraints.applied,
        unresolved_hard_constraints=[],
        clarification_questions=[],
        excluded_by_hard_constraints=input_count - len(filtered),
        constraint_trace=constraint_trace,
        zero_result_reason=zero_result_reason,
        ranking_config=config,
    )
    return MatchPipelineResult(
        items=ranked, meta=meta.model_dump(mode="json")
    )
