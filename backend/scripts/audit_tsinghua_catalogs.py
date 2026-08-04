#!/usr/bin/env python3
"""审计 D1 目录数据集，只输出计数和哈希，不输出导师姓名。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.catalog import (  # noqa: E402
    AdvisorEntityType,
    CatalogDataset,
)
from app.services.catalog_ingestion import audit_catalog_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    try:
        dataset = CatalogDataset.model_validate_json(
            args.dataset.read_text(encoding="utf-8")
        )
        errors = audit_catalog_dataset(dataset)
        if errors:
            for error in errors:
                print(error)
            print(f"FAIL: {len(errors)} issue(s)", file=sys.stderr)
            return 1

        department_by_id = {
            department.department_id: department
            for department in dataset.departments
        }
        directions_by_advisor: dict[str, set[str]] = defaultdict(set)
        for offering in dataset.offerings:
            if offering.advisor_or_group_id:
                directions_by_advisor[offering.advisor_or_group_id].add(
                    offering.direction_id
                )
        labels_to_departments: dict[
            tuple[str, str, str], set[str]
        ] = defaultdict(set)
        for advisor in dataset.advisors_or_groups:
            labels_to_departments[
                (
                    advisor.snapshot_id,
                    advisor.entity_type.value,
                    advisor.source_label,
                )
            ].add(advisor.department_id)

        tag_counts = Counter(
            tag for remark in dataset.remarks for tag in remark.explicit_tags
        )
        scope_counts = Counter(remark.scope.value for remark in dataset.remarks)
        print(
            "PASS "
            f"schema={dataset.schema_version} "
            f"snapshots={len(dataset.snapshots)} "
            f"departments={len(department_by_id)} "
            f"programs={len(dataset.programs)} "
            f"directions={len(dataset.research_directions)} "
            f"advisor_or_groups={len(dataset.advisors_or_groups)} "
            f"offerings={len(dataset.offerings)} "
            f"remarks={len(dataset.remarks)}"
        )
        for snapshot in sorted(
            dataset.snapshots, key=lambda value: value.catalog_type.value
        ):
            key = snapshot.catalog_type.value
            snapshot_programs = sum(
                value.snapshot_id == snapshot.snapshot_id
                for value in dataset.programs
            )
            snapshot_directions = sum(
                value.snapshot_id == snapshot.snapshot_id
                for value in dataset.research_directions
            )
            snapshot_advisors = sum(
                value.snapshot_id == snapshot.snapshot_id
                for value in dataset.advisors_or_groups
            )
            snapshot_offerings = sum(
                value.snapshot_id == snapshot.snapshot_id
                for value in dataset.offerings
            )
            snapshot_remarks = sum(
                value.snapshot_id == snapshot.snapshot_id
                for value in dataset.remarks
            )
            print(
                f"snapshot catalog_type={key} "
                f"uuid={snapshot.snapshot_id} "
                f"source_pages={len(snapshot.page_content_sha256)} "
                f"departments={dataset.coverage.parsed_departments[key]} "
                f"programs={snapshot_programs} "
                f"directions={snapshot_directions} "
                f"advisor_or_groups={snapshot_advisors} "
                f"offerings={snapshot_offerings} "
                f"remarks={snapshot_remarks} "
                f"empty_departments={dataset.coverage.empty_departments[key]} "
                "programs_without_directions="
                f"{dataset.coverage.programs_without_directions[key]} "
                "directions_without_advisors="
                f"{dataset.coverage.directions_without_advisors[key]} "
                "offerings_without_advisor="
                f"{dataset.coverage.offerings_without_advisor[key]} "
                f"snapshot_sha256={snapshot.content_sha256}"
            )
        print(
            "edge_cases "
            f"advisor_groups={sum(value.entity_type == AdvisorEntityType.ADVISOR_GROUP for value in dataset.advisors_or_groups)} "
            f"english_labels={sum(bool(re.search(r'[A-Za-z]', value.source_label)) for value in dataset.advisors_or_groups)} "
            f"source_labels_in_multiple_departments={sum(len(departments) > 1 for departments in labels_to_departments.values())} "
            f"entities_linked_to_multiple_directions={sum(len(directions) > 1 for directions in directions_by_advisor.values())} "
            f"remark_scopes={json.dumps(dict(sorted(scope_counts.items())), ensure_ascii=False, sort_keys=True)} "
            f"explicit_tags={json.dumps(dict(sorted(tag_counts.items())), ensure_ascii=False, sort_keys=True)}"
        )
        print(f"dataset_sha256={dataset.content_sha256}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
