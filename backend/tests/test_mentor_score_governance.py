from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.mentor_scores import (
    MentorScoreDataset,
    MentorScoreRelease,
    ScoreDimension,
    ScoreEvidenceClaim,
    ScoreReleaseStatus,
)
from app.services import mentor_score_governance as score_service


EXTRACTED = datetime(2026, 8, 1, tzinfo=timezone.utc)
REVIEWED = datetime(2026, 8, 2, tzinfo=timezone.utc)
VALID_UNTIL = datetime(2027, 8, 1, tzinfo=timezone.utc)


def _value(dimension: ScoreDimension):
    if dimension == ScoreDimension.SECTOR_ATTRIBUTE:
        return "state"
    if dimension == ScoreDimension.COMPATIBILITY_RESEARCH_MODE:
        return ["theory", "mixed"]
    if dimension == ScoreDimension.COMPATIBILITY_MENTORSHIP_STYLE:
        return ["balanced"]
    if dimension == ScoreDimension.COMPATIBILITY_CAREER_ORIENTATION:
        return ["academic"]
    if dimension == ScoreDimension.COMPATIBILITY_INNOVATION_RISK:
        return ["mature"]
    return 60.0


def _claim(advisor_id: str, dimension: ScoreDimension) -> ScoreEvidenceClaim:
    return ScoreEvidenceClaim(
        advisor_id=advisor_id,
        dimension=dimension,
        value=_value(dimension),
        source_kind="official_public",
        source_url=f"https://www.tsinghua.edu.cn/evidence/{advisor_id}/{dimension.value}",
        extracted_at=EXTRACTED,
        valid_until=VALID_UNTIL,
        method="逐维公开事实提取并独立审核",
        method_version="fixture-v1",
        review_status="approved",
        reviewer_id="reviewer-fixture",
        reviewed_at=REVIEWED,
    )


def _dataset() -> MentorScoreDataset:
    return MentorScoreDataset(
        generated_at=REVIEWED,
        releases=[
            MentorScoreRelease(
                version=1,
                status=ScoreReleaseStatus.PUBLISHED,
                created_at=EXTRACTED,
                published_at=REVIEWED,
                claims=[_claim("advisor-a", dimension) for dimension in ScoreDimension],
            )
        ],
    )


def test_claims_reject_raw_student_text_and_under_threshold_aggregate():
    payload = _claim("advisor-a", ScoreDimension.TRAIT_ACUMEN).model_dump()
    payload["raw_student_text"] = "不得入库的可识别原文"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ScoreEvidenceClaim.model_validate(payload)

    payload.pop("raw_student_text")
    payload.update(
        source_kind="authorized_aggregate",
        sample_size=4,
        privacy_threshold=5,
    )
    with pytest.raises(ValidationError, match="隐私样本阈值"):
        ScoreEvidenceClaim.model_validate(payload)


def test_coverage_gate_requires_complete_current_approved_dimensions(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "mentor-scores.json"
    path.write_text(_dataset().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(score_service.settings, "MENTOR_SCORE_DATA_FILE", str(path))
    monkeypatch.setattr(score_service.settings, "MENTOR_SCORE_DATA_EXPECTED_SHA256", None)
    monkeypatch.setattr(score_service.settings, "MENTOR_SCORE_COVERAGE_THRESHOLD", 0.8)
    score_service.clear_score_cache()
    candidates = [{"advisor_id": "advisor-a"}, {"advisor_id": "advisor-b"}]

    closed = score_service.score_coverage_status(candidates, now=REVIEWED)
    assert closed["gate_open"] is False
    assert closed["coverage"] == pytest.approx(0.5)
    assert closed["complete_advisors"] == 1

    monkeypatch.setattr(score_service.settings, "MENTOR_SCORE_COVERAGE_THRESHOLD", 0.5)
    bundles, opened = score_service.public_score_bundles(candidates, now=REVIEWED)
    assert opened["gate_open"] is True
    assert set(bundles) == {"advisor-a"}
    assert bundles["advisor-a"]["values"]["trait_acumen"] == 60.0
    serialized = str(bundles)
    assert "reviewer-fixture" not in serialized
    assert "source_url" in serialized

    expired = score_service.score_coverage_status(
        candidates,
        now=datetime(2028, 1, 1, tzinfo=timezone.utc),
    )
    assert expired["gate_open"] is False
    assert expired["expired_claims"] == len(ScoreDimension)
    assert expired["coverage"] == 0
    score_service.clear_score_cache()


def test_no_score_file_is_an_honest_closed_state(monkeypatch):
    monkeypatch.setattr(score_service.settings, "MENTOR_SCORE_DATA_FILE", None)
    score_service.clear_score_cache()
    status = score_service.score_coverage_status(
        [{"advisor_id": "advisor-a"}],
        now=REVIEWED,
    )
    assert status["gate_open"] is False
    assert status["reason"] == "score_evidence_file_not_configured_or_unavailable"
