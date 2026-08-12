from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from app.schemas.governance import MentorDataset
from scripts.export_formal_mentor_projection import (
    PROFILE_FIELDS,
    ProjectionError,
    audit_formal_projection,
    promote_formal_projection,
)


CAPTURED_AT = "2026-08-12T12:00:00+08:00"
REVIEWED_AT = "2026-08-13T12:00:00+08:00"


def _candidate() -> MentorDataset:
    fields = {
        "name": "示例导师",
        "dept": "示例院系",
        "title": "教授",
        "official_homepage": "https://www.tsinghua.edu.cn/example",
        "entity_type": "person",
        "resource_type": "verified_mentor_profile",
        "identity_status": "pending_review",
        "recommendation_eligibility": "withheld",
        "academic_year": 2027,
        "catalog_types": ["doctoral_general"],
        "programs": ["示例专业"],
        "research_keywords": ["可信研究方向"],
        "catalog_entries": [
            {
                "catalog_type": "doctoral_general",
                "department_code": "001",
                "program_code": "080000",
                "direction_code": "01",
            }
        ],
        "identity_scope": "2027_department_name_plus_official_profile",
    }
    assert set(fields) == PROFILE_FIELDS
    provenance = {}
    for field_name in fields:
        inferred = field_name in {
            "resource_type",
            "identity_status",
            "recommendation_eligibility",
            "identity_scope",
        }
        provenance[field_name] = [
            {
                "evidence_id": str(uuid.uuid4()),
                "source_type": "inference" if inferred else "public_fact",
                "source_ref": (
                    f"strict-official-identity:{field_name}"
                    if inferred
                    else "https://www.tsinghua.edu.cn/example"
                ),
                "captured_at": CAPTURED_AT,
                "verification_status": "unverified",
                "confidence": 1.0,
                "method": "test",
                "method_version": "1.0",
            }
        ]
    return MentorDataset.model_validate(
        {
            "schema_version": "2.0",
            "generated_at": CAPTURED_AT,
            "source": {
                "source_type": "official_catalog_and_profiles",
                "content_sha256": "1" * 64,
                "original_record_count": 1,
                "raw_retained": False,
            },
            "records": [
                {
                    "schema_version": "2.0",
                    "advisor_id": "prof_123456789012345",
                    "fields": fields,
                    "provenance": provenance,
                    "governance": {
                        "review_status": "pending_review",
                        "publication_status": "restricted",
                        "created_at": CAPTURED_AT,
                        "updated_at": CAPTURED_AT,
                        "expires_at": "2027-02-08T12:00:00+08:00",
                        "authorization": {
                            "basis": "public_source",
                            "scope": sorted(fields),
                        },
                        "takedown": {"status": "active"},
                    },
                    "quarantined_fields": {},
                }
            ],
        }
    )


def _write_candidate(path: Path) -> bytes:
    payload = json.dumps(
        _candidate().model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path.read_bytes()


def _write_receipt(path: Path, candidate_bytes: bytes, candidate_hash: str | None = None):
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "decision": "approved",
                "candidate_sha256": candidate_hash
                or hashlib.sha256(candidate_bytes).hexdigest(),
                "reviewer_role_id": "independent-mentor-release-auditor",
                "reviewed_at": REVIEWED_AT,
            }
        ),
        encoding="utf-8",
    )


def test_formal_publish_is_receipt_bound_and_makes_profile_eligible(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    receipt_path = tmp_path / "approval.json"
    candidate_bytes = _write_candidate(candidate_path)
    _write_receipt(receipt_path, candidate_bytes)

    published = promote_formal_projection(candidate_path, receipt_path)
    record = published.records[0]
    assert record.fields["identity_status"] == "verified"
    assert record.fields["recommendation_eligibility"] == "eligible"
    assert record.to_public_dict() is not None

    published_path = tmp_path / "published.json"
    published_path.write_text(
        json.dumps(
            published.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    audit = audit_formal_projection(
        candidate_path,
        published_path,
        stage="published",
        approval_path=receipt_path,
    )
    assert audit["status"] == "PASS"
    assert audit["match_candidate_records"] == 1


def test_formal_publish_rejects_receipt_for_other_bytes(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    receipt_path = tmp_path / "approval.json"
    candidate_bytes = _write_candidate(candidate_path)
    _write_receipt(receipt_path, candidate_bytes, candidate_hash="0" * 64)

    with pytest.raises(ProjectionError, match="does not match candidate bytes"):
        promote_formal_projection(candidate_path, receipt_path)
