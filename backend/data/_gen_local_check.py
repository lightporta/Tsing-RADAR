"""临时：生成本地雷达图验证用合成数据（验证后整体删除，不入库不提交）。"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.governance import (
    AuthorizationBasis,
    AuthorizationMetadata,
    DatasetSource,
    GovernedMentorRecord,
    MentorDataset,
    PublicationStatus,
    RecordGovernance,
    ReviewStatus,
    TakedownMetadata,
    TakedownStatus,
)
from app.schemas.mentor_scores import (
    MentorScoreDataset,
    MentorScoreRelease,
    ScoreDimension,
    ScoreEvidenceClaim,
    ScoreReleaseStatus,
)

NOW = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
AID = "A001"


def provenance_for(fields: set[str]) -> dict:
    return {
        field: [
            {
                "evidence_id": str(uuid4()),
                "source_type": "public_fact",
                "source_ref": f"https://www.tsinghua.edu.cn/advisor/{AID}",
                "captured_at": NOW.isoformat(),
                "verification_status": "verified",
                "confidence": 0.9,
            }
        ]
        for field in fields
    }


record = GovernedMentorRecord(
    schema_version="2.0",
    advisor_id=AID,
    fields={
        "name": "张伟",
        "dept": "计算机科学与技术系",
        "title": "教授",
        "resource_type": "verified_mentor_profile",
        "identity_status": "verified",
        "recommendation_eligibility": "eligible",
    },
    provenance=provenance_for(
        {"name", "dept", "title", "resource_type", "identity_status",
         "recommendation_eligibility"}
    ),
    governance=RecordGovernance(
        review_status=ReviewStatus.VERIFIED,
        publication_status=PublicationStatus.PUBLISHED,
        created_at=NOW,
        updated_at=NOW,
        verified_at=NOW,
        authorization=AuthorizationMetadata(
            basis=AuthorizationBasis.PUBLIC_SOURCE, scope=[]
        ),
        takedown=TakedownMetadata(status=TakedownStatus.ACTIVE),
    ),
    quarantined_fields={},
)
dataset = MentorDataset(
    schema_version="2.0",
    generated_at=NOW,
    source=DatasetSource(
        source_type="official_catalog_and_profiles",
        content_sha256="0" * 64,
        original_record_count=1,
        raw_retained=False,
    ),
    records=[record],
)
with open("data/mentors.evidence.json", "w", encoding="utf-8") as f:
    f.write(dataset.model_dump_json(indent=2))
print("evidence ok")


def claim(dim: ScoreDimension) -> ScoreEvidenceClaim:
    if dim == ScoreDimension.SECTOR_ATTRIBUTE:
        value = "state"
    elif dim == ScoreDimension.COMPATIBILITY_RESEARCH_MODE:
        value = ["theory", "mixed"]
    elif dim == ScoreDimension.COMPATIBILITY_MENTORSHIP_STYLE:
        value = ["balanced"]
    elif dim == ScoreDimension.COMPATIBILITY_CAREER_ORIENTATION:
        value = ["academic"]
    elif dim == ScoreDimension.COMPATIBILITY_INNOVATION_RISK:
        value = ["mature"]
    else:
        value = 72.0
    return ScoreEvidenceClaim(
        advisor_id=AID,
        dimension=dim,
        value=value,
        source_kind="official_public",
        source_url=f"https://www.tsinghua.edu.cn/evidence/{AID}/{dim.value}",
        extracted_at=NOW,
        valid_until=datetime(2027, 8, 1, tzinfo=timezone.utc),
        method="逐维公开事实提取并独立审核",
        method_version="local-check-v1",
        review_status="approved",
        reviewer_id="reviewer-local",
        reviewed_at=NOW,
    )


scores = MentorScoreDataset(
    generated_at=NOW,
    releases=[
        MentorScoreRelease(
            version=1,
            status=ScoreReleaseStatus.PUBLISHED,
            created_at=NOW,
            published_at=NOW,
            claims=[claim(d) for d in ScoreDimension],
        )
    ],
)
with open("data/mentor-scores.local.json", "w", encoding="utf-8") as f:
    f.write(scores.model_dump_json(indent=2))
print("scores ok")
