#!/usr/bin/env python3
"""审计证据化导师数据集，不输出导师原始内容。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.schemas.governance import MentorDataset

FORBIDDEN_RUNTIME_FIELDS = {
    "score",
    "reason",
    "radar_traits",
    "popularity",
    "sector",
    "projects",
    "recruitments",
    "contact_email",
    "office_loc",
}


def audit(dataset: MentorDataset) -> list[str]:
    errors: list[str] = []
    advisor_ids: set[str] = set()

    if dataset.source.original_record_count != len(dataset.records):
        errors.append("source.original_record_count 与 records 数量不一致")

    for record in dataset.records:
        if record.advisor_id in advisor_ids:
            errors.append(f"重复 advisor_id: {record.advisor_id}")
        advisor_ids.add(record.advisor_id)

        leaked = FORBIDDEN_RUNTIME_FIELDS & set(record.fields)
        if leaked:
            errors.append(
                f"{record.advisor_id}: 隔离字段进入运行 fields: {sorted(leaked)}"
            )
        if record.to_public_dict() is not None:
            public_record = record.to_public_dict() or {}
            public_leak = FORBIDDEN_RUNTIME_FIELDS & set(public_record)
            if public_leak:
                errors.append(
                    f"{record.advisor_id}: 发布视图泄露字段: {sorted(public_leak)}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    args = parser.parse_args()

    try:
        payload = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        dataset = MentorDataset.model_validate(payload)
        errors = audit(dataset)
        if errors:
            for error in errors:
                print(error)
            print(f"FAIL: {len(errors)} issue(s)", file=sys.stderr)
            return 1
        published = sum(
            record.to_public_dict() is not None for record in dataset.records
        )
        quarantined = sum(
            len(record.quarantined_fields) for record in dataset.records
        )
        print(
            f"PASS: records={len(dataset.records)} "
            f"published={published} quarantined_fields={quarantined}"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
