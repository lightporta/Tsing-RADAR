#!/usr/bin/env python3
"""Build, audit and publish the formal mentor-resource projection.

The review candidate keeps the already-reviewed official catalog public while
new profile records remain restricted.  Publication is an explicit,
receipt-bound transition performed only after an independent review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.schemas.catalog import CatalogDataset
from app.schemas.governance import MentorDataset
from scripts.export_catalog_mentor_projection import (
    IdRegistry,
    ProjectionError,
    _advisor_id as catalog_advisor_id,
    _aware_datetime,
    _deduplicate_provenance,
    _evidence_payload as catalog_evidence_payload,
    _group_catalog,
    _normalize_label,
    audit_projection as audit_catalog_projection,
)


EXPORTER_VERSION = "formal-mentor-projection/1.0"
PROFILE_RESOURCE_TYPE = "verified_mentor_profile"
FORMAL_SCOPE = "2027_catalog_plus_strict_official_profiles"
PROFILE_EXPIRY_DAYS = 180
PROFILE_FIELDS = {
    "name",
    "dept",
    "title",
    "official_homepage",
    "entity_type",
    "resource_type",
    "identity_status",
    "recommendation_eligibility",
    "academic_year",
    "catalog_types",
    "programs",
    "research_keywords",
    "catalog_entries",
    "identity_scope",
}
FORBIDDEN_FIELDS = {
    "current_admission",
    "quota",
    "admission_probability",
    "competition_score",
    "ranking",
    "rating",
    "mentor_style",
    "funding",
    "group_atmosphere",
    "ethics",
    "sentiment",
    "risk_score",
    "phone",
    "wechat",
    "private_email",
    "public_work_email",
    "home_address",
}
PROFILE_LIST_KEYS = (
    "catalog_links",
    "claims",
    "directions",
    "entities",
    "entity_directions",
    "evidence",
    "issues",
    "names",
    "opportunities",
    "relations",
    "reviews",
    "snapshots",
    "sources",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, str) and "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.isoformat()
    return value


def _record_sha256(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "content_sha256"}
    encoded = json.dumps(
        _canonicalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _normalize_fragment(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _is_official_url(value: str) -> bool:
    parsed = urlsplit(str(value))
    hostname = (parsed.hostname or "").lower()
    return bool(
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and (hostname == "tsinghua.edu.cn" or hostname.endswith(".tsinghua.edu.cn"))
    )


def _uuid4(value: str, context: str) -> None:
    try:
        parsed = UUID(str(value))
    except ValueError as exc:
        raise ProjectionError(f"{context} is not a UUID") from exc
    if parsed.version != 4:
        raise ProjectionError(f"{context} is not UUIDv4")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def _validate_profile_package(
    package_path: Path,
    snapshots_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("schema_version") != "2.1":
        raise ProjectionError("profile package schema must be 2.1")
    if set(PROFILE_LIST_KEYS) - set(package):
        raise ProjectionError("profile package is missing required collections")
    if _record_sha256(package) != package.get("content_sha256"):
        raise ProjectionError("profile package content hash mismatch")
    for collection_name in ("batch", *PROFILE_LIST_KEYS):
        values = package[collection_name]
        records = [values] if collection_name == "batch" else values
        for index, record in enumerate(records):
            if _record_sha256(record) != record.get("content_sha256"):
                raise ProjectionError(
                    f"{collection_name}[{index}] content hash mismatch"
                )
    if package["batch"].get("published_count") != 0 or package["reviews"]:
        raise ProjectionError("reference package must remain unpublished and unreviewed")

    sources = {item["source_id"]: item for item in package["sources"]}
    snapshots = {item["snapshot_id"]: item for item in package["snapshots"]}
    evidence = {item["evidence_id"]: item for item in package["evidence"]}
    if len(sources) != len(package["sources"]):
        raise ProjectionError("duplicate profile source ID")
    if len(snapshots) != len(package["snapshots"]):
        raise ProjectionError("duplicate profile snapshot ID")
    if len(evidence) != len(package["evidence"]):
        raise ProjectionError("duplicate profile evidence ID")

    valid_snapshots: set[str] = set()
    for snapshot_id, snapshot in snapshots.items():
        _uuid4(snapshot_id, "snapshot_id")
        source = sources.get(snapshot["source_id"])
        if source is None or not _is_official_url(source.get("public_url", "")):
            raise ProjectionError("profile snapshot has a non-official source")
        snapshot_file = snapshots_root / snapshot["storage_key"]
        payload = snapshot_file.read_bytes()
        if len(payload) != snapshot["byte_count"]:
            raise ProjectionError("profile snapshot byte count mismatch")
        if _sha256_bytes(payload) != snapshot["page_content_sha256"]:
            raise ProjectionError("profile snapshot page hash mismatch")
        valid_snapshots.add(snapshot_id)

    for evidence_id, item in evidence.items():
        _uuid4(evidence_id, "evidence_id")
        source = sources.get(item["source_id"])
        snapshot = snapshots.get(item["snapshot_id"])
        if (
            source is None
            or snapshot is None
            or item["snapshot_id"] not in valid_snapshots
            or snapshot["source_id"] != item["source_id"]
            or item["page_content_sha256"] != snapshot["page_content_sha256"]
        ):
            raise ProjectionError("profile evidence graph or page hash mismatch")
        if not _is_official_url(source.get("public_url", "")):
            raise ProjectionError("profile evidence source is not official")
        expected_fragment = _sha256_bytes(
            _normalize_fragment(item["raw_text"]).encode("utf-8")
        )
        if expected_fragment != item["fragment_sha256"]:
            raise ProjectionError("profile evidence fragment hash mismatch")

    for claim in package["claims"]:
        _uuid4(claim["claim_id"], "claim_id")
        item = evidence.get(claim["evidence_id"])
        if item is None or item["source_id"] != claim["source_id"]:
            raise ProjectionError("claim evidence/source graph mismatch")
        if (
            claim["review_status"] != "pending_review"
            or claim["publication_status"] != "withheld"
            or claim["verification_status"] != "unverified"
        ):
            raise ProjectionError("reference claim crossed a review gate")
    return package, evidence


def _profile_advisor_id(entity_id: str) -> str:
    return "prof_" + hashlib.sha256(entity_id.encode()).hexdigest()[:15]


def _profile_evidence_payload(
    registry: IdRegistry,
    *,
    advisor_id: str,
    field_name: str,
    claim: dict[str, Any],
    evidence: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    material = f"{advisor_id}:{field_name}:{claim['claim_id']}:{evidence['fragment_sha256']}"
    return {
        "evidence_id": registry.get("formal-profile-evidence", material),
        "source_type": "public_fact",
        "source_ref": source["public_url"],
        "captured_at": evidence["captured_at"],
        "verification_status": "unverified",
        "confidence": 1.0,
        "method": EXPORTER_VERSION,
        "method_version": "1.0",
    }


def _inference_payload(
    registry: IdRegistry,
    *,
    advisor_id: str,
    field_name: str,
    captured_at: datetime,
    identity_material: str,
) -> dict[str, Any]:
    material = f"{advisor_id}:{field_name}:{identity_material}"
    return {
        "evidence_id": registry.get("formal-identity-decision", material),
        "source_type": "inference",
        "source_ref": "strict-official-identity:" + _sha256_bytes(
            identity_material.encode("utf-8")
        ),
        "captured_at": captured_at.isoformat(),
        "verification_status": "unverified",
        "confidence": 1.0,
        "method": "exact-year-department-name-official-profile-match",
        "method_version": "1.0",
    }


def _unique_claim_value(
    claims: list[dict[str, Any]],
    field_name: str,
) -> tuple[str, list[dict[str, Any]]] | None:
    selected = [item for item in claims if item["field_name"] == field_name]
    values = {str(item["normalized_value"]).strip() for item in selected}
    values.discard("")
    if len(values) != 1:
        return None
    value = next(iter(values))
    return value, [item for item in selected if str(item["normalized_value"]).strip() == value]


def _catalog_values(
    rows: list[Any],
    catalog: CatalogDataset,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[datetime]]:
    snapshots = {item.snapshot_id: item for item in catalog.snapshots}
    departments = {item.department_id: item for item in catalog.departments}
    programs = {item.program_id: item for item in catalog.programs}
    directions = {item.direction_id: item for item in catalog.research_directions}
    offerings: dict[str, list[Any]] = defaultdict(list)
    for item in catalog.offerings:
        if item.advisor_or_group_id:
            offerings[item.advisor_or_group_id].append(item)

    catalog_types: dict[str, Any] = {}
    program_values: dict[str, Any] = {}
    direction_values: dict[str, Any] = {}
    entry_values: dict[str, tuple[dict[str, str], Any]] = {}
    timestamps: list[datetime] = []
    for row in rows:
        snapshot = snapshots[row.snapshot_id]
        department = departments[row.department_id]
        timestamps.extend((snapshot.captured_at, row.provenance["source_label"].captured_at))
        catalog_types.setdefault(snapshot.catalog_type.value, snapshot.provenance["catalog_type"])
        for offering in offerings[row.advisor_or_group_id]:
            direction = directions[offering.direction_id]
            program = programs[direction.program_id]
            program_values.setdefault(program.name, program.provenance["name"])
            direction_values.setdefault(direction.name, direction.provenance["name"])
            entry = {
                "catalog_type": snapshot.catalog_type.value,
                "department_code": department.code,
                "program_code": program.code,
                "direction_code": direction.code,
            }
            entry_values.setdefault("|".join(entry.values()), (entry, offering.provenance["relation"]))
    fields = {
        "academic_year": 2027,
        "catalog_types": sorted(catalog_types),
        "programs": sorted(program_values),
        "research_keywords": sorted(direction_values),
        "catalog_entries": [entry_values[key][0] for key in sorted(entry_values)],
    }
    raw_evidence = {
        "academic_year": [snapshots[rows[0].snapshot_id].provenance["academic_year"]],
        "catalog_types": [catalog_types[key] for key in sorted(catalog_types)],
        "programs": [program_values[key] for key in sorted(program_values)],
        "research_keywords": [direction_values[key] for key in sorted(direction_values)],
        "catalog_entries": [entry_values[key][1] for key in sorted(entry_values)],
    }
    return fields, raw_evidence, timestamps


def build_formal_candidate(
    catalog: CatalogDataset,
    published_catalog: MentorDataset,
    profile_package: dict[str, Any],
    profile_evidence: dict[str, dict[str, Any]],
    registry: IdRegistry,
) -> MentorDataset:
    baseline_audit = audit_catalog_projection(
        catalog,
        published_catalog,
        stage="published",
        candidate_sha256="baseline",
    )
    if baseline_audit["status"] != "PASS":
        raise ProjectionError(f"published catalog baseline failed: {baseline_audit['errors']}")

    entities = {item["entity_id"]: item for item in profile_package["entities"]}
    sources = {item["source_id"]: item for item in profile_package["sources"]}
    claims_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in profile_package["claims"]:
        claims_by_subject[claim["subject_id"]].append(claim)
    affiliation: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for relation in profile_package["relations"]:
        if relation["relation_type"] == "affiliated_with":
            affiliation[relation["subject_entity_id"]] = (
                relation,
                entities[relation["object_entity_id"]],
            )
    blocked_targets = {
        item["target_id"]
        for item in profile_package["issues"]
        if item["issue_status"] == "open" and item["severity"] in {"error", "critical"}
    }
    groups = _group_catalog(catalog)
    department_codes: dict[str, set[str]] = defaultdict(set)
    for department in catalog.departments:
        department_codes[department.name].add(department.code)

    profile_records: list[dict[str, Any]] = []
    for person in sorted(profile_package["entities"], key=lambda item: item["entity_id"]):
        if person["entity_type"] != "person" or person["entity_id"] in blocked_targets:
            continue
        relation_and_org = affiliation.get(person["entity_id"])
        if relation_and_org is None:
            continue
        relation, organization = relation_and_org
        codes = department_codes.get(organization["display_name"], set())
        if len(codes) != 1:
            continue
        key = (next(iter(codes)), "person", _normalize_label(person["display_name"]))
        rows = sorted(
            groups.get(key, []),
            key=lambda item: (item.snapshot_id, item.advisor_or_group_id),
        )
        if not rows:
            continue
        catalog_fields, catalog_evidence, catalog_timestamps = _catalog_values(rows, catalog)
        if not catalog_fields["research_keywords"]:
            continue

        person_claims = claims_by_subject[person["entity_id"]]
        name_claim = _unique_claim_value(person_claims, "name_zh")
        title_claim = _unique_claim_value(person_claims, "title")
        homepage_claim = _unique_claim_value(person_claims, "official_homepage")
        dept_claim = _unique_claim_value(
            claims_by_subject[relation["relation_id"]],
            "object_entity_display_name",
        )
        if not all((name_claim, title_claim, homepage_claim, dept_claim)):
            continue
        assert name_claim and title_claim and homepage_claim and dept_claim
        if _normalize_label(name_claim[0]) != _normalize_label(person["display_name"]):
            continue
        if dept_claim[0] != organization["display_name"]:
            continue
        if not _is_official_url(homepage_claim[0]):
            continue

        advisor_id = _profile_advisor_id(person["entity_id"])
        fields: dict[str, Any] = {
            "name": name_claim[0],
            "dept": dept_claim[0],
            "title": title_claim[0],
            "official_homepage": homepage_claim[0],
            "entity_type": "person",
            "resource_type": PROFILE_RESOURCE_TYPE,
            "identity_status": "pending_review",
            "recommendation_eligibility": "withheld",
            **catalog_fields,
            "identity_scope": "2027_department_name_plus_official_profile",
        }
        provenance: dict[str, list[dict[str, Any]]] = defaultdict(list)
        profile_claim_sets = {
            "name": name_claim[1],
            "dept": dept_claim[1],
            "title": title_claim[1],
            "official_homepage": homepage_claim[1],
            "entity_type": name_claim[1],
        }
        timestamps = list(catalog_timestamps)
        for field_name, claims in profile_claim_sets.items():
            for claim in claims:
                item = profile_evidence[claim["evidence_id"]]
                source = sources[claim["source_id"]]
                timestamps.append(_aware_datetime(item["captured_at"]))
                provenance[field_name].append(
                    _profile_evidence_payload(
                        registry,
                        advisor_id=advisor_id,
                        field_name=field_name,
                        claim=claim,
                        evidence=item,
                        source=source,
                    )
                )
        record_key = _sha256_bytes(
            f"2027:{key[0]}:person:{key[2]}".encode("utf-8")
        )
        for field_name, values in catalog_evidence.items():
            for index, item in enumerate(values):
                provenance[field_name].append(
                    catalog_evidence_payload(
                        registry,
                        record_key=record_key,
                        field_name=f"profile:{field_name}:{index}",
                        evidence=item,
                    )
                )
        captured_at = max(timestamps)
        identity_material = ":".join(
            (person["entity_id"], key[0], key[2], *sorted(row.advisor_or_group_id for row in rows))
        )
        for field_name in (
            "resource_type",
            "identity_status",
            "recommendation_eligibility",
            "identity_scope",
        ):
            provenance[field_name].append(
                _inference_payload(
                    registry,
                    advisor_id=advisor_id,
                    field_name=field_name,
                    captured_at=captured_at,
                    identity_material=identity_material,
                )
            )
        profile_records.append(
            {
                "schema_version": "2.0",
                "advisor_id": advisor_id,
                "fields": fields,
                "provenance": {
                    field_name: _deduplicate_provenance(values)
                    for field_name, values in sorted(provenance.items())
                },
                "governance": {
                    "review_status": "pending_review",
                    "publication_status": "restricted",
                    "created_at": min(timestamps).isoformat(),
                    "updated_at": captured_at.isoformat(),
                    "expires_at": (captured_at + timedelta(days=PROFILE_EXPIRY_DAYS)).isoformat(),
                    "authorization": {
                        "basis": "public_source",
                        "scope": sorted(fields),
                    },
                    "takedown": {"status": "active"},
                },
                "quarantined_fields": {},
            }
        )

    if not profile_records:
        raise ProjectionError("formal selection produced zero profile candidates")
    combined_source_hash = _sha256_bytes(
        f"{catalog.content_sha256}:{profile_package['content_sha256']}:{EXPORTER_VERSION}".encode()
    )
    payload = {
        "schema_version": "2.0",
        "generated_at": max(
            catalog.generated_at,
            _aware_datetime(profile_package["batch"]["generated_at"]),
        ).isoformat(),
        "source": {
            "source_type": "official_catalog_and_profiles",
            "content_sha256": combined_source_hash,
            "original_record_count": len(catalog.advisors_or_groups)
            + sum(item["entity_type"] == "person" for item in profile_package["entities"]),
            "raw_retained": False,
        },
        "records": [
            *published_catalog.model_dump(mode="json")["records"],
            *profile_records,
        ],
    }
    return MentorDataset.model_validate(payload)


def promote_formal_projection(candidate_path: Path, approval_path: Path) -> MentorDataset:
    candidate_bytes = candidate_path.read_bytes()
    candidate = MentorDataset.model_validate_json(candidate_bytes)
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if approval.get("schema_version") != "1.0" or approval.get("decision") != "approved":
        raise ProjectionError("independent review did not approve publication")
    if approval.get("candidate_sha256") != _sha256_bytes(candidate_bytes):
        raise ProjectionError("approval receipt does not match candidate bytes")
    reviewer = str(approval.get("reviewer_role_id") or "")
    if not reviewer or reviewer == EXPORTER_VERSION:
        raise ProjectionError("independent reviewer role is missing")
    reviewed_at = _aware_datetime(str(approval.get("reviewed_at") or ""))

    payload = candidate.model_dump(mode="json")
    payload["generated_at"] = reviewed_at.isoformat()
    promoted = 0
    for record in payload["records"]:
        if record["fields"].get("resource_type") != PROFILE_RESOURCE_TYPE:
            continue
        governance = record["governance"]
        if reviewed_at < _aware_datetime(governance["updated_at"]):
            raise ProjectionError("review time predates captured facts")
        if (
            governance["review_status"] != "pending_review"
            or governance["publication_status"] != "restricted"
            or record["fields"].get("identity_status") != "pending_review"
            or record["fields"].get("recommendation_eligibility") != "withheld"
        ):
            raise ProjectionError("profile candidate is not in the review state")
        record["fields"]["identity_status"] = "verified"
        record["fields"]["recommendation_eligibility"] = "eligible"
        governance.update(
            {
                "review_status": "verified",
                "publication_status": "published",
                "verified_at": reviewed_at.isoformat(),
                "updated_at": reviewed_at.isoformat(),
            }
        )
        for values in record["provenance"].values():
            for item in values:
                item["verification_status"] = "verified"
        promoted += 1
    if promoted == 0:
        raise ProjectionError("no formal profiles were promoted")
    return MentorDataset.model_validate(payload)


def audit_formal_projection(
    candidate_path: Path,
    projection_path: Path,
    *,
    stage: str,
    approval_path: Path | None,
) -> dict[str, Any]:
    candidate_bytes = candidate_path.read_bytes()
    candidate = MentorDataset.model_validate_json(candidate_bytes)
    projection_bytes = projection_path.read_bytes()
    projection = MentorDataset.model_validate_json(projection_bytes)
    if stage == "review":
        expected = candidate
    else:
        if approval_path is None:
            raise ProjectionError("published audit requires approval receipt")
        expected = promote_formal_projection(candidate_path, approval_path)
    errors: list[str] = []
    if projection.model_dump(mode="json") != expected.model_dump(mode="json"):
        errors.append("projection_not_exact_expected_transition")
    advisor_ids: set[str] = set()
    evidence_ids: set[str] = set()
    profile_count = 0
    match_candidate_count = 0
    for record in projection.records:
        if record.advisor_id in advisor_ids:
            errors.append("duplicate_advisor_id")
        advisor_ids.add(record.advisor_id)
        fields = record.fields
        if set(fields) & FORBIDDEN_FIELDS:
            errors.append("forbidden_field_present")
        if fields.get("resource_type") == PROFILE_RESOURCE_TYPE:
            profile_count += 1
            if set(fields) != PROFILE_FIELDS:
                errors.append("profile_field_allowlist_mismatch")
            if not _is_official_url(str(fields.get("official_homepage", ""))):
                errors.append("profile_homepage_not_official")
            eligible = (
                record.governance.publication_status.value == "published"
                and record.governance.review_status.value == "verified"
                and fields.get("identity_status") == "verified"
                and fields.get("recommendation_eligibility") == "eligible"
            )
            match_candidate_count += eligible
            if (stage == "published") != eligible:
                errors.append("profile_stage_or_eligibility_mismatch")
        for field_name, values in record.provenance.items():
            if field_name not in fields or not values:
                errors.append("field_provenance_coverage_mismatch")
            for item in values:
                evidence_id = str(item.evidence_id)
                if evidence_id in evidence_ids:
                    errors.append("duplicate_evidence_id")
                evidence_ids.add(evidence_id)
                if item.source_type.value == "public_fact" and not _is_official_url(item.source_ref):
                    errors.append("non_official_public_source")
                if item.consent_id:
                    errors.append("private_consent_identifier_present")
    public_count = sum(record.to_public_dict() is not None for record in projection.records)
    result = {
        "schema_version": "1.0",
        "status": "PASS" if not errors else "FAIL",
        "stage": stage,
        "scope": FORMAL_SCOPE,
        "candidate_sha256": _sha256_bytes(candidate_bytes),
        "projection_sha256": _sha256_bytes(projection_bytes),
        "total_records": len(projection.records),
        "public_records": public_count,
        "profile_records": profile_count,
        "match_candidate_records": match_candidate_count,
        "evidence_records": len(evidence_ids),
        "errors": sorted(set(errors)),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--published-catalog", type=Path, required=True)
    build.add_argument("--profile-package", type=Path, required=True)
    build.add_argument("--profile-snapshots-root", type=Path, required=True)
    build.add_argument("--id-registry", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--candidate", type=Path, required=True)
    publish.add_argument("--approval-receipt", type=Path, required=True)
    publish.add_argument("--output", type=Path, required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--candidate", type=Path, required=True)
    audit.add_argument("--projection", type=Path, required=True)
    audit.add_argument("--stage", choices=("review", "published"), required=True)
    audit.add_argument("--approval-receipt", type=Path)
    audit.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            catalog = CatalogDataset.model_validate_json(args.catalog.read_bytes())
            published_catalog = MentorDataset.model_validate_json(
                args.published_catalog.read_bytes()
            )
            profile_package, profile_evidence = _validate_profile_package(
                args.profile_package,
                args.profile_snapshots_root,
            )
            registry = IdRegistry(args.id_registry)
            projection = build_formal_candidate(
                catalog,
                published_catalog,
                profile_package,
                profile_evidence,
                registry,
            )
            _write_json_atomic(args.output, projection.model_dump(mode="json"))
            registry.save()
            result = {
                "status": "PASS",
                "command": "build",
                "records": len(projection.records),
                "published": sum(
                    item.to_public_dict() is not None for item in projection.records
                ),
                "formal_profiles": sum(
                    item.fields.get("resource_type") == PROFILE_RESOURCE_TYPE
                    for item in projection.records
                ),
                "file_sha256": _sha256_bytes(args.output.read_bytes()),
            }
        elif args.command == "publish":
            projection = promote_formal_projection(
                args.candidate,
                args.approval_receipt,
            )
            _write_json_atomic(args.output, projection.model_dump(mode="json"))
            result = {
                "status": "PASS",
                "command": "publish",
                "records": len(projection.records),
                "published": sum(
                    item.to_public_dict() is not None for item in projection.records
                ),
                "formal_profiles": sum(
                    item.fields.get("resource_type") == PROFILE_RESOURCE_TYPE
                    for item in projection.records
                ),
                "file_sha256": _sha256_bytes(args.output.read_bytes()),
            }
        else:
            result = audit_formal_projection(
                args.candidate,
                args.projection,
                stage=args.stage,
                approval_path=args.approval_receipt,
            )
            _write_json_atomic(args.report, result)
            if result["status"] != "PASS":
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ProjectionError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
