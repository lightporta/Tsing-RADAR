"""A2 证据化数据模型、迁移和发布门测试。"""

from __future__ import annotations

import json
import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import advisor as advisor_api
from app.api.v1 import scatter as scatter_api
from app.main import app
from app.schemas.governance import (
    GovernedMentorRecord,
    MentorDataset,
    ProvenanceEntry,
    RecordGovernance,
    TakedownMetadata,
)
from app.services.data_loader import (
    load_mentor_dataset,
    load_mentors,
    mentor_data_summary,
)
from app.services import data_loader
from scripts.audit_evidence_data import audit
from scripts.migrate_mentor_evidence import migrate_payload

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
EMPTY_GOVERNANCE_SEED = (
    REPOSITORY_ROOT
    / "deploy"
    / "production"
    / "data"
    / "empty-mentor-governance.json"
)
client = TestClient(app)


def test_public_fact_requires_absolute_source():
    with pytest.raises(ValidationError):
        ProvenanceEntry(
            source_type="public_fact",
            source_ref="legacy-seed",
            captured_at="2026-07-30T00:00:00+08:00",
            verification_status="verified",
            confidence=1,
        )


def test_private_source_requires_consent():
    with pytest.raises(ValidationError):
        ProvenanceEntry(
            source_type="authorized_message",
            source_ref="message:123",
            captured_at="2026-07-30T00:00:00+08:00",
            verification_status="verified",
            confidence=1,
        )


def test_aggregate_evaluation_requires_method_window_and_privacy_threshold():
    with pytest.raises(ValidationError):
        ProvenanceEntry(
            source_type="aggregate_evaluation",
            source_ref="aggregate:mentor-style",
            captured_at="2026-07-30T00:00:00+08:00",
            verification_status="verified",
            confidence=0.8,
            method="weighted_mean",
            method_version="1.0",
            observed_from="2026-01-01T00:00:00+08:00",
            observed_to="2026-06-30T23:59:59+08:00",
            sample_size=2,
            privacy_threshold=5,
        )


def test_published_record_requires_review_and_authorization():
    with pytest.raises(ValidationError):
        RecordGovernance(
            review_status="pending_review",
            publication_status="published",
            created_at="2026-07-30T00:00:00+08:00",
            updated_at="2026-07-30T00:00:00+08:00",
            authorization={"basis": "legacy_seed", "scope": []},
            takedown={"status": "active"},
        )


def _verified_record(*, expires_at: datetime | None = None) -> GovernedMentorRecord:
    timestamp = "2026-07-30T00:00:00+08:00"
    evidence_id = str(uuid.uuid4())
    return GovernedMentorRecord.model_validate(
        {
            "advisor_id": "verified000000000001",
            "fields": {"name": "示例导师"},
            "provenance": {
                "name": [
                    {
                        "evidence_id": evidence_id,
                        "source_type": "public_fact",
                        "source_ref": "https://example.edu/mentor",
                        "captured_at": timestamp,
                        "verification_status": "verified",
                        "confidence": 1,
                    }
                ]
            },
            "governance": {
                "review_status": "verified",
                "publication_status": "published",
                "created_at": timestamp,
                "updated_at": timestamp,
                "verified_at": timestamp,
                "expires_at": expires_at,
                "authorization": {
                    "basis": "public_source",
                    "scope": ["name"],
                },
                "takedown": {"status": "active"},
            },
            "quarantined_fields": {},
        }
    )


def test_private_provenance_is_redacted_and_uses_persisted_random_id():
    timestamp = "2026-07-30T00:00:00+08:00"
    evidence_id = uuid.uuid4()
    internal_ref = "message:123"
    consent_id = "consent-secret-456"
    record = GovernedMentorRecord.model_validate(
        {
            "advisor_id": "verified-private-001",
            "fields": {"name": "授权示例导师"},
            "provenance": {
                "name": [
                    {
                        "evidence_id": str(evidence_id),
                        "source_type": "authorized_message",
                        "source_ref": internal_ref,
                        "captured_at": timestamp,
                        "verification_status": "verified",
                        "consent_id": consent_id,
                        "confidence": 0.8,
                        "method": "internal-review-detail",
                    }
                ]
            },
            "governance": {
                "review_status": "verified",
                "publication_status": "published",
                "created_at": timestamp,
                "updated_at": timestamp,
                "verified_at": timestamp,
                "authorization": {
                    "basis": "explicit_consent",
                    "consent_id": consent_id,
                    "scope": ["name"],
                    "authorized_at": timestamp,
                },
                "takedown": {"status": "active"},
            },
            "quarantined_fields": {},
        }
    )
    public_payload = record.to_public_dict()
    serialized = json.dumps(public_payload, ensure_ascii=False)
    assert internal_ref not in serialized
    assert consent_id not in serialized
    assert "internal-review-detail" not in serialized
    citation = public_payload["provenance"]["name"][0]
    assert citation["evidence_id"] == f"ev_{evidence_id.hex}"
    assert citation["citation_type"] == "authorized_evidence"
    assert "source_url" not in citation

    # 旧式无密钥 hash(context + 低熵引用 + 时间)不能重算公开 ID。
    guessed = hashlib.sha256(
        f"mentor:verified-private-001:name:0\0authorized_message\0{internal_ref}\0{timestamp}".encode()
    ).hexdigest()[:24]
    assert citation["evidence_id"] != f"ev_{guessed}"


def test_mentor_list_and_scatter_never_rehydrate_private_provenance(
    monkeypatch,
):
    published = {
        "advisor_id": "verified-private-001",
        "name": "授权示例导师",
        "dept": "示例院系",
        "provenance": {
            "name": [
                {
                    "evidence_id": f"ev_{uuid.uuid4().hex}",
                    "citation_type": "authorized_evidence",
                    "citation": "已授权且经审核的私域消息",
                    "captured_at": "2026-07-30T00:00:00+08:00",
                    "confidence": 0.8,
                }
            ]
        },
    }
    monkeypatch.setattr(advisor_api, "load_mentors", lambda: [published])
    monkeypatch.setattr(scatter_api, "load_mentors", lambda: [published])
    listed = client.get("/api/mentors").json()
    scattered = client.get("/api/scatter").json()
    serialized = json.dumps([listed, scattered], ensure_ascii=False)
    assert "message:" not in serialized
    assert "consent_id" not in serialized
    assert "source_ref" not in serialized


def test_verified_record_can_publish_but_expired_record_cannot():
    assert _verified_record().to_public_dict()["name"] == "示例导师"
    expired = _verified_record(
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    assert expired.to_public_dict() is None


def test_taken_down_record_cannot_publish():
    record = _verified_record()
    record.governance.takedown = TakedownMetadata(
        status="taken_down",
        requested_at=datetime.now(timezone.utc) - timedelta(hours=1),
        effective_at=datetime.now(timezone.utc),
        reason="owner_request",
    )
    assert record.to_public_dict() is None


def test_legacy_migration_quarantines_unsupported_values():
    raw = json.dumps(
        [
            {
                "name": "示例导师",
                "dept": "示例院系",
                "field": "示例方向",
                "score": 99,
                "radar_traits": {"mentorship": 100},
                "contact_email": "private@example.edu",
                "recruitments": [{"title": "未授权招募"}],
            }
        ],
        ensure_ascii=False,
    ).encode("utf-8")
    dataset = migrate_payload(
        raw,
        generated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )
    record = dataset.records[0]

    assert record.fields == {
        "name": "示例导师",
        "dept": "示例院系",
        "field": "示例方向",
    }
    assert record.to_public_dict() is None
    assert set(record.quarantined_fields) == {
        "score",
        "radar_traits",
        "contact_email",
        "recruitments",
    }
    assert all(
        entry.value_retained is False
        for entry in record.quarantined_fields.values()
    )


def _clear_mentor_caches() -> None:
    data_loader.load_mentors.cache_clear()
    data_loader.load_match_candidates.cache_clear()
    data_loader.load_mentor_dataset.cache_clear()


def test_release_governance_seed_starts_empty_and_valid(monkeypatch):
    monkeypatch.setattr(data_loader, "_DATA_PATH", str(EMPTY_GOVERNANCE_SEED))
    _clear_mentor_caches()
    try:
        dataset = load_mentor_dataset()
        assert isinstance(dataset, MentorDataset)
        assert dataset.records == []
        assert dataset.source.original_record_count == 0
        assert dataset.source.raw_retained is False
        assert load_mentors() == []
        assert mentor_data_summary() == {
            "total_records": 0,
            "published_records": 0,
            "withheld_records": 0,
            "policy": "verified_only",
        }
        assert audit(dataset) == []
    finally:
        _clear_mentor_caches()


def test_missing_governance_seed_fails_closed(monkeypatch, tmp_path):
    missing = tmp_path / "missing-governance.json"
    monkeypatch.setattr(data_loader, "_DATA_PATH", str(missing))
    _clear_mentor_caches()
    try:
        with pytest.raises(FileNotFoundError):
            load_mentor_dataset()
    finally:
        _clear_mentor_caches()


def test_malformed_nonempty_governance_seed_is_rejected(monkeypatch, tmp_path):
    malformed = tmp_path / "malformed-governance.json"
    malformed.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "generated_at": "2026-08-05T00:00:00+08:00",
                "source": {
                    "source_type": "legacy_seed",
                    "content_sha256": "0" * 64,
                    "original_record_count": 1,
                    "raw_retained": False,
                },
                "records": [{}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(data_loader, "_DATA_PATH", str(malformed))
    _clear_mentor_caches()
    try:
        with pytest.raises(ValidationError):
            load_mentor_dataset()
    finally:
        _clear_mentor_caches()


def test_raw_runtime_copies_are_removed():
    assert not (BACKEND_ROOT / "data" / "mentors.json").exists()
    frontend_mock = (
        REPOSITORY_ROOT / "frontend" / "src" / "mock" / "mentors.json"
    )
    assert json.loads(frontend_mock.read_text(encoding="utf-8")) == []
    legacy_root = REPOSITORY_ROOT / "legacy"
    assert not (legacy_root / "mentors.json").exists()
    assert not (legacy_root / "mentors.json.bak").exists()
    legacy_html = (legacy_root / "index.html").read_text(encoding="utf-8")
    assert "const DEFAULT_MENTORS = [];" in legacy_html
    assert "fetch('mentors.json')" not in legacy_html


def test_legacy_app_starts_in_fail_closed_empty_state():
    legacy_app_path = REPOSITORY_ROOT / "legacy" / "app.py"
    spec = importlib.util.spec_from_file_location(
        "tsing_radar_legacy_empty_state",
        legacy_app_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.DEFAULT_MENTORS == []
    source = legacy_app_path.read_text(encoding="utf-8")
    assert "mentors.json" not in source
