"""Fail-closed publication gate for optional mentor score visualisations."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.mentor_scores import (
    ClaimReviewStatus,
    MentorScoreDataset,
    REQUIRED_SCORE_DIMENSIONS,
    ScoreDimension,
    ScoreReleaseStatus,
)
from app.services.data_loader import load_match_candidates


def _now(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("now 必须包含时区")
    return result


@lru_cache(maxsize=1)
def load_score_dataset() -> MentorScoreDataset | None:
    """Load one immutable score release file; absence means an honest zero state."""
    configured = settings.MENTOR_SCORE_DATA_FILE
    if not configured:
        return None
    path = Path(configured)
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    expected = (settings.MENTOR_SCORE_DATA_EXPECTED_SHA256 or "").strip().lower()
    if expected and hashlib.sha256(payload).hexdigest() != expected:
        raise RuntimeError("mentor_score_dataset_sha256_mismatch")
    return MentorScoreDataset.model_validate_json(payload)


def _active_release(
    dataset: MentorScoreDataset | None,
) -> Any | None:
    if dataset is None:
        return None
    releases = [
        release
        for release in dataset.releases
        if release.status == ScoreReleaseStatus.PUBLISHED
    ]
    return max(releases, key=lambda item: item.version, default=None)


def score_coverage_status(
    candidates: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return only aggregate gate state; never expose unpublished claim values."""
    current = _now(now)
    candidate_rows = candidates if candidates is not None else load_match_candidates()
    advisor_ids = {
        str(item.get("advisor_id"))
        for item in candidate_rows
        if item.get("advisor_id")
    }
    dataset = load_score_dataset()
    release = _active_release(dataset)
    current_dimensions: dict[str, set[ScoreDimension]] = {
        advisor_id: set() for advisor_id in advisor_ids
    }
    expired_claims = 0
    approved_claims = 0
    if release is not None:
        for claim in release.claims:
            if claim.advisor_id not in advisor_ids:
                continue
            if claim.review_status != ClaimReviewStatus.APPROVED:
                continue
            approved_claims += 1
            if claim.valid_until <= current:
                expired_claims += 1
                continue
            current_dimensions[claim.advisor_id].add(claim.dimension)
    complete_advisors = sum(
        dimensions >= REQUIRED_SCORE_DIMENSIONS
        for dimensions in current_dimensions.values()
    )
    candidate_count = len(advisor_ids)
    coverage = complete_advisors / candidate_count if candidate_count else 0.0
    threshold = float(settings.MENTOR_SCORE_COVERAGE_THRESHOLD)
    gate_open = bool(
        release is not None
        and candidate_count
        and coverage >= threshold
    )
    dimension_coverage = {
        dimension.value: round(
            sum(
                dimension in dimensions
                for dimensions in current_dimensions.values()
            )
            / candidate_count,
            6,
        )
        if candidate_count
        else 0.0
        for dimension in ScoreDimension
    }
    reason = "coverage_threshold_met"
    if dataset is None:
        reason = "score_evidence_file_not_configured_or_unavailable"
    elif release is None:
        reason = "no_published_score_release"
    elif not candidate_count:
        reason = "no_verified_match_candidates"
    elif coverage < threshold:
        reason = "trusted_coverage_below_threshold"
    return {
        "gate_open": gate_open,
        "reason": reason,
        "coverage": round(coverage, 6),
        "coverage_threshold": threshold,
        "eligible_advisors": candidate_count,
        "complete_advisors": complete_advisors,
        "approved_claims": approved_claims,
        "expired_claims": expired_claims,
        "required_dimensions": sorted(
            dimension.value for dimension in REQUIRED_SCORE_DIMENSIONS
        ),
        "dimension_coverage": dimension_coverage,
        "release_version": release.version if release is not None else None,
        "release_id": str(release.release_id) if release is not None else None,
        "as_of": current.isoformat(),
        "policy": "all_dimensions_independently_approved_and_current",
    }


def public_score_bundles(
    candidates: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return current approved claims only after the aggregate gate opens."""
    current = _now(now)
    candidate_rows = candidates if candidates is not None else load_match_candidates()
    status = score_coverage_status(candidate_rows, now=current)
    if not status["gate_open"]:
        return {}, status
    dataset = load_score_dataset()
    release = _active_release(dataset)
    assert release is not None
    grouped: dict[str, dict[ScoreDimension, Any]] = {}
    allowed_ids = {
        str(item.get("advisor_id"))
        for item in candidate_rows
        if item.get("advisor_id")
    }
    for claim in release.claims:
        if claim.advisor_id not in allowed_ids or not claim.is_current_approved(current):
            continue
        grouped.setdefault(claim.advisor_id, {})[claim.dimension] = claim

    bundles: dict[str, dict[str, Any]] = {}
    for advisor_id, claims in grouped.items():
        if set(claims) < REQUIRED_SCORE_DIMENSIONS:
            continue
        values = {dimension.value: claim.value for dimension, claim in claims.items()}
        citations = {
            dimension.value: {
                "claim_id": f"score_{claim.claim_id.hex}",
                "source_url": claim.source_url,
                "extracted_at": claim.extracted_at.isoformat(),
                "valid_until": claim.valid_until.isoformat(),
                "method": claim.method,
                "method_version": claim.method_version,
                "release_version": release.version,
            }
            for dimension, claim in claims.items()
        }
        bundles[advisor_id] = {"values": values, "citations": citations}
    return bundles, status


def score_enriched_resources(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Strip legacy score fields and overlay only gate-released evidence."""
    bundles, status = public_score_bundles()
    enriched: list[dict[str, Any]] = []
    for source in records:
        item = copy.deepcopy(source)
        for field in ("radar_traits", "popularity", "sector", "synergy"):
            item.pop(field, None)
        bundle = bundles.get(str(item.get("advisor_id")))
        if bundle:
            values = bundle["values"]
            item["radar_traits"] = {
                key: values[f"trait_{key}"]
                for key in (
                    "acumen",
                    "network",
                    "mentorship",
                    "tolerance",
                    "funding",
                    "efficiency",
                )
            }
            item["popularity"] = values["popularity_index"]
            item["sector"] = (
                "国" if values["sector_attribute"] == "state" else "私"
            )
            item["compatibility_evidence"] = {
                "research_mode": values["compatibility_research_mode"],
                "mentorship_style": values["compatibility_mentorship_style"],
                "career_orientation": values[
                    "compatibility_career_orientation"
                ],
                "innovation_risk": values["compatibility_innovation_risk"],
            }
            item["score_evidence"] = bundle["citations"]
        enriched.append(item)
    return enriched, status


def clear_score_cache() -> None:
    load_score_dataset.cache_clear()
