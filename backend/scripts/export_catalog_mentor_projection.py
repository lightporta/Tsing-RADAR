#!/usr/bin/env python3
"""Build, audit, and publish a governed projection of official catalog entries.

Source catalogs and generated projections remain outside Git. ``build`` creates
only a restricted candidate. ``publish`` requires an independent approval
receipt bound to the exact candidate bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.schemas.catalog import CatalogDataset
from app.schemas.governance import MentorDataset


EXPORTER_VERSION = "official-catalog-mentor-projection/1.0"
CATALOG_SCOPE = "2027_doctoral_catalog"
ALLOWED_SOURCE_HOSTS = {"yz.tsinghua.edu.cn", "yzbm.tsinghua.edu.cn"}
ALLOWED_FIELDS = {
    "name",
    "dept",
    "entity_type",
    "resource_type",
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
    "home_address",
}


class ProjectionError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionError("reviewed_at must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProjectionError("reviewed_at must include a timezone")
    return parsed


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


class IdRegistry:
    """Persist UUIDv4 assignments without retaining names in registry keys."""

    def __init__(self, path: Path):
        self.path = path
        self.values: dict[str, str] = {}
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "1.0-private":
                raise ProjectionError("invalid private ID registry schema")
            self.values = dict(payload.get("values", {}))

    def get(self, namespace: str, material: str) -> str:
        key = _sha256_bytes(f"{namespace}\0{material}".encode())
        value = self.values.setdefault(key, str(uuid4()))
        if UUID(value).version != 4:
            raise ProjectionError("ID registry accepts UUIDv4 values only")
        return value

    def save(self) -> None:
        _write_json_atomic(
            self.path,
            {"schema_version": "1.0-private", "values": dict(sorted(self.values.items()))},
        )


def _advisor_id(identity_key: str) -> str:
    return "cat_" + hashlib.sha256(identity_key.encode()).hexdigest()[:16]


def _evidence_payload(
    registry: IdRegistry,
    *,
    record_key: str,
    field_name: str,
    evidence: Any,
) -> dict[str, Any]:
    material = ":".join(
        (record_key, field_name, str(evidence.source_url), evidence.fragment_sha256)
    )
    return {
        "evidence_id": registry.get("evidence", material),
        "source_type": "public_fact",
        "source_ref": str(evidence.source_url),
        "captured_at": evidence.captured_at.isoformat(),
        "verification_status": "unverified",
        "confidence": 1.0,
        "method": EXPORTER_VERSION,
        "method_version": "1.0",
    }


def _deduplicate_provenance(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = {str(value["evidence_id"]): value for value in values}
    return [selected[key] for key in sorted(selected)]


def _group_catalog(dataset: CatalogDataset) -> dict[tuple[str, str, str], list[Any]]:
    departments = {item.department_id: item for item in dataset.departments}
    grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for advisor in dataset.advisors_or_groups:
        department = departments[advisor.department_id]
        grouped[
            (department.code, advisor.entity_type.value, _normalize_label(advisor.source_label))
        ].append(advisor)
    return grouped


def build_projection(dataset: CatalogDataset, registry: IdRegistry) -> MentorDataset:
    snapshots = {item.snapshot_id: item for item in dataset.snapshots}
    departments = {item.department_id: item for item in dataset.departments}
    programs = {item.program_id: item for item in dataset.programs}
    directions = {item.direction_id: item for item in dataset.research_directions}
    offerings_by_advisor: dict[str, list[Any]] = defaultdict(list)
    for offering in dataset.offerings:
        if offering.advisor_or_group_id:
            offerings_by_advisor[offering.advisor_or_group_id].append(offering)

    records: list[dict[str, Any]] = []
    for group_key, rows in sorted(_group_catalog(dataset).items()):
        advisor_rows = sorted(rows, key=lambda item: (item.snapshot_id, item.advisor_or_group_id))
        representative = advisor_rows[0]
        representative_department = departments[representative.department_id]
        identity_key = f"2027:{group_key[0]}:{group_key[1]}:{group_key[2]}"
        record_key = _sha256_bytes(identity_key.encode())
        fields: dict[str, Any] = {
            "name": representative.source_label,
            "dept": representative_department.name,
            "entity_type": representative.entity_type.value,
            "resource_type": (
                "mentor_catalog_entry"
                if representative.entity_type.value == "person"
                else "advisor_group_catalog_entry"
            ),
            "academic_year": 2027,
            "identity_scope": "academic_year_department_source_label",
        }
        provenance: dict[str, list[dict[str, Any]]] = defaultdict(list)
        program_values: dict[str, Any] = {}
        direction_values: dict[str, Any] = {}
        catalog_types: dict[str, Any] = {}
        entry_values: dict[str, tuple[dict[str, str], Any]] = {}
        timestamps: list[datetime] = []

        for advisor in advisor_rows:
            department = departments[advisor.department_id]
            snapshot = snapshots[advisor.snapshot_id]
            name_evidence = advisor.provenance["source_label"]
            type_evidence = advisor.provenance["entity_type"]
            timestamps.extend(
                [name_evidence.captured_at, type_evidence.captured_at, snapshot.captured_at]
            )
            source_fields = {
                "name": name_evidence,
                "dept": department.provenance["name"],
                "entity_type": type_evidence,
                "resource_type": type_evidence,
                "academic_year": snapshot.provenance["academic_year"],
                "identity_scope": name_evidence,
            }
            for field_name, evidence in source_fields.items():
                provenance[field_name].append(
                    _evidence_payload(
                        registry,
                        record_key=record_key,
                        field_name=field_name,
                        evidence=evidence,
                    )
                )
            catalog_types.setdefault(
                snapshot.catalog_type.value, snapshot.provenance["catalog_type"]
            )
            for offering in offerings_by_advisor.get(advisor.advisor_or_group_id, []):
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
                entry_key = "|".join(entry.values())
                entry_values.setdefault(entry_key, (entry, offering.provenance["relation"]))

        fields["catalog_types"] = sorted(catalog_types)
        fields["programs"] = sorted(program_values)
        fields["research_keywords"] = sorted(direction_values)
        fields["catalog_entries"] = [entry_values[key][0] for key in sorted(entry_values)]
        for value, evidence in sorted(catalog_types.items()):
            provenance["catalog_types"].append(
                _evidence_payload(
                    registry,
                    record_key=record_key,
                    field_name=f"catalog_types:{value}",
                    evidence=evidence,
                )
            )
        for field_name, values in (
            ("programs", program_values),
            ("research_keywords", direction_values),
        ):
            for value, evidence in sorted(values.items()):
                provenance[field_name].append(
                    _evidence_payload(
                        registry,
                        record_key=record_key,
                        field_name=f"{field_name}:{value}",
                        evidence=evidence,
                    )
                )
        for value, (_, evidence) in sorted(entry_values.items()):
            provenance["catalog_entries"].append(
                _evidence_payload(
                    registry,
                    record_key=record_key,
                    field_name=f"catalog_entries:{value}",
                    evidence=evidence,
                )
            )

        records.append(
            {
                "schema_version": "2.0",
                "advisor_id": _advisor_id(identity_key),
                "fields": fields,
                "provenance": {
                    key: _deduplicate_provenance(value)
                    for key, value in sorted(provenance.items())
                },
                "governance": {
                    "review_status": "pending_review",
                    "publication_status": "restricted",
                    "created_at": min(timestamps).isoformat(),
                    "updated_at": max(timestamps).isoformat(),
                    "authorization": {
                        "basis": "public_source",
                        "scope": sorted(fields),
                    },
                    "takedown": {"status": "active"},
                },
                "quarantined_fields": {},
            }
        )

    return MentorDataset.model_validate(
        {
            "schema_version": "2.0",
            "generated_at": dataset.generated_at.isoformat(),
            "source": {
                "source_type": "official_catalog",
                "content_sha256": dataset.content_sha256,
                "original_record_count": len(dataset.advisors_or_groups),
                "raw_retained": False,
            },
            "records": records,
        }
    )


def promote_projection(candidate_path: Path, approval_path: Path) -> MentorDataset:
    candidate_bytes = candidate_path.read_bytes()
    candidate = MentorDataset.model_validate_json(candidate_bytes)
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if approval.get("schema_version") != "1.0":
        raise ProjectionError("invalid approval receipt schema")
    if approval.get("decision") != "approved":
        raise ProjectionError("independent review did not approve publication")
    if approval.get("candidate_sha256") != _sha256_bytes(candidate_bytes):
        raise ProjectionError("approval receipt does not match candidate bytes")
    reviewer = str(approval.get("reviewer_role_id") or "")
    if not reviewer or reviewer == EXPORTER_VERSION:
        raise ProjectionError("independent reviewer role is missing")
    reviewed_at = _aware_datetime(str(approval.get("reviewed_at") or ""))

    payload = candidate.model_dump(mode="json")
    payload["generated_at"] = reviewed_at.isoformat()
    for record in payload["records"]:
        governance = record["governance"]
        if reviewed_at < _aware_datetime(governance["updated_at"]):
            raise ProjectionError("review time predates captured facts")
        if (
            governance["review_status"] != "pending_review"
            or governance["publication_status"] != "restricted"
        ):
            raise ProjectionError("candidate is not in the restricted review state")
        governance.update(
            {
                "review_status": "verified",
                "publication_status": "published",
                "verified_at": reviewed_at.isoformat(),
                "updated_at": reviewed_at.isoformat(),
            }
        )
        for values in record["provenance"].values():
            for evidence in values:
                evidence["verification_status"] = "verified"
    return MentorDataset.model_validate(payload)


def audit_projection(
    catalog: CatalogDataset,
    projection: MentorDataset,
    *,
    stage: str,
    candidate_sha256: str,
) -> dict[str, Any]:
    expected_groups = _group_catalog(catalog)
    snapshots = {item.snapshot_id: item for item in catalog.snapshots}
    departments = {item.department_id: item for item in catalog.departments}
    programs = {item.program_id: item for item in catalog.programs}
    directions = {item.direction_id: item for item in catalog.research_directions}
    offerings_by_advisor: dict[str, list[Any]] = defaultdict(list)
    for offering in catalog.offerings:
        if offering.advisor_or_group_id:
            offerings_by_advisor[offering.advisor_or_group_id].append(offering)
    expected_status = (
        ("pending_review", "restricted", "unverified")
        if stage == "review"
        else ("verified", "published", "verified")
    )
    errors: list[str] = []
    advisor_ids: set[str] = set()
    evidence_ids: set[str] = set()
    observed_keys: set[tuple[str, str, str]] = set()
    entity_counts: dict[str, int] = defaultdict(int)
    if projection.source.source_type != "official_catalog":
        errors.append("source_type_mismatch")
    if projection.source.content_sha256 != catalog.content_sha256:
        errors.append("catalog_content_sha256_mismatch")
    if projection.source.original_record_count != len(catalog.advisors_or_groups):
        errors.append("original_record_count_mismatch")
    if len(projection.records) != len(expected_groups):
        errors.append("projected_record_count_mismatch")

    department_codes: dict[str, set[str]] = defaultdict(set)
    for item in catalog.departments:
        department_codes[item.name].add(item.code)
    for record in projection.records:
        fields = record.fields
        field_names = set(fields)
        if field_names != ALLOWED_FIELDS:
            errors.append("field_allowlist_mismatch")
        if field_names & FORBIDDEN_FIELDS:
            errors.append("forbidden_field_present")
        entity_type = str(fields.get("entity_type", ""))
        entity_counts[entity_type] += 1
        codes = department_codes.get(str(fields.get("dept", "")), set())
        if len(codes) != 1:
            errors.append("department_name_code_not_unique")
            department_code = ""
        else:
            department_code = next(iter(codes))
        key = (
            department_code,
            entity_type,
            _normalize_label(str(fields.get("name", ""))),
        )
        observed_keys.add(key)
        if key not in expected_groups:
            errors.append("record_not_backed_by_catalog_group")
        else:
            rows = sorted(
                expected_groups[key],
                key=lambda item: (item.snapshot_id, item.advisor_or_group_id),
            )
            expected_programs: set[str] = set()
            expected_directions: set[str] = set()
            expected_entries: dict[str, dict[str, str]] = {}
            for row in rows:
                snapshot = snapshots[row.snapshot_id]
                for offering in offerings_by_advisor.get(row.advisor_or_group_id, []):
                    direction = directions[offering.direction_id]
                    program = programs[direction.program_id]
                    expected_programs.add(program.name)
                    expected_directions.add(direction.name)
                    entry = {
                        "catalog_type": snapshot.catalog_type.value,
                        "department_code": departments[row.department_id].code,
                        "program_code": program.code,
                        "direction_code": direction.code,
                    }
                    expected_entries["|".join(entry.values())] = entry
            expected_fields = {
                "name": rows[0].source_label,
                "dept": departments[rows[0].department_id].name,
                "entity_type": entity_type,
                "resource_type": (
                    "mentor_catalog_entry"
                    if entity_type == "person"
                    else "advisor_group_catalog_entry"
                ),
                "academic_year": 2027,
                "catalog_types": sorted(
                    {snapshots[row.snapshot_id].catalog_type.value for row in rows}
                ),
                "programs": sorted(expected_programs),
                "research_keywords": sorted(expected_directions),
                "catalog_entries": [
                    expected_entries[value] for value in sorted(expected_entries)
                ],
                "identity_scope": "academic_year_department_source_label",
            }
            if fields != expected_fields:
                errors.append("projected_fields_mismatch")
        identity_key = f"2027:{key[0]}:{key[1]}:{key[2]}"
        if record.advisor_id != _advisor_id(identity_key):
            errors.append("advisor_id_mismatch")
        if record.advisor_id in advisor_ids:
            errors.append("duplicate_advisor_id")
        advisor_ids.add(record.advisor_id)
        if (
            record.governance.review_status.value,
            record.governance.publication_status.value,
        ) != expected_status[:2]:
            errors.append("governance_stage_mismatch")
        if set(record.provenance) != field_names:
            errors.append("field_provenance_coverage_mismatch")
        if any(not record.provenance.get(field_name) for field_name in field_names):
            errors.append("empty_field_provenance")
        for values in record.provenance.values():
            for evidence in values:
                evidence_id = str(evidence.evidence_id)
                if evidence_id in evidence_ids:
                    errors.append("duplicate_evidence_id")
                evidence_ids.add(evidence_id)
                parsed = urlsplit(evidence.source_ref)
                if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
                    errors.append("non_official_source_url")
                if evidence.source_type.value != "public_fact" or evidence.consent_id:
                    errors.append("non_public_or_private_provenance")
                if evidence.verification_status.value != expected_status[2]:
                    errors.append("evidence_stage_mismatch")
    if observed_keys != set(expected_groups):
        errors.append("catalog_group_coverage_mismatch")
    public_count = sum(record.to_public_dict() is not None for record in projection.records)
    expected_public_count = 0 if stage == "review" else len(projection.records)
    if public_count != expected_public_count:
        errors.append("public_projection_stage_mismatch")

    unique_errors = sorted(set(errors))
    return {
        "schema_version": "1.0",
        "status": "PASS" if not unique_errors else "FAIL",
        "stage": stage,
        "scope": CATALOG_SCOPE,
        "candidate_sha256": candidate_sha256,
        "catalog_content_sha256": catalog.content_sha256,
        "source_advisor_or_group_rows": len(catalog.advisors_or_groups),
        "projected_records": len(projection.records),
        "person_records": entity_counts.get("person", 0),
        "advisor_group_records": entity_counts.get("advisor_group", 0),
        "evidence_records": len(evidence_ids),
        "public_records": public_count,
        "errors": unique_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--id-registry", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--candidate", type=Path, required=True)
    publish.add_argument("--approval-receipt", type=Path, required=True)
    publish.add_argument("--output", type=Path, required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--catalog", type=Path, required=True)
    audit.add_argument("--projection", type=Path, required=True)
    audit.add_argument("--stage", choices=("review", "published"), required=True)
    audit.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            dataset = CatalogDataset.model_validate_json(args.catalog.read_bytes())
            registry = IdRegistry(args.id_registry)
            projection = build_projection(dataset, registry)
            _write_json_atomic(args.output, projection.model_dump(mode="json"))
            registry.save()
            result = {
                "status": "PASS",
                "command": "build",
                "records": len(projection.records),
                "published": 0,
                "source_sha256": projection.source.content_sha256,
                "file_sha256": _sha256_bytes(args.output.read_bytes()),
            }
        elif args.command == "publish":
            projection = promote_projection(args.candidate, args.approval_receipt)
            _write_json_atomic(args.output, projection.model_dump(mode="json"))
            result = {
                "status": "PASS",
                "command": "publish",
                "records": len(projection.records),
                "published": len(projection.records),
                "source_sha256": projection.source.content_sha256,
                "file_sha256": _sha256_bytes(args.output.read_bytes()),
            }
        else:
            catalog = CatalogDataset.model_validate_json(args.catalog.read_bytes())
            projection_bytes = args.projection.read_bytes()
            projection = MentorDataset.model_validate_json(projection_bytes)
            result = audit_projection(
                catalog,
                projection,
                stage=args.stage,
                candidate_sha256=_sha256_bytes(projection_bytes),
            )
            _write_json_atomic(args.report, result)
            if result["status"] != "PASS":
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, ProjectionError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
