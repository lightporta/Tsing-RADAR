#!/usr/bin/env python3
"""把无来源导师种子数据迁移为默认 restricted 的证据化数据集。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.governance import MentorDataset, QuarantineReason

CORE_REVIEW_FIELDS = ("name", "dept", "field")
SUBJECTIVE_FIELDS = {
    "score",
    "reason",
    "radar_traits",
    "popularity",
    "sector",
}
PERSONAL_FIELDS = {"contact_email", "office_loc", "phone", "wechat"}
TIME_SENSITIVE_FIELDS = {"projects", "recruitments"}


def _reason_for(field_name: str) -> str:
    if field_name in SUBJECTIVE_FIELDS:
        return QuarantineReason.UNSUPPORTED_SUBJECTIVE_METRIC.value
    if field_name in PERSONAL_FIELDS:
        return QuarantineReason.PERSONAL_DATA_REQUIRES_AUTHORIZATION.value
    if field_name in TIME_SENSITIVE_FIELDS:
        return QuarantineReason.TIME_SENSITIVE_DATA_REQUIRES_VERIFICATION.value
    if field_name == "tags":
        return QuarantineReason.UNSOURCED_FACT.value
    return QuarantineReason.LEGACY_FIELD_REQUIRES_REVIEW.value


def _stable_legacy_id(index: int, mentor: dict[str, Any]) -> str:
    identity = "\0".join(
        [
            str(index),
            str(mentor.get("name", "")),
            str(mentor.get("dept", "")),
        ]
    )
    return f"legacy{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:14]}"


def migrate_payload(
    raw_bytes: bytes,
    *,
    generated_at: datetime,
) -> MentorDataset:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at 必须包含时区")
    raw_records = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw_records, list):
        raise ValueError("旧导师数据必须是数组")

    timestamp = generated_at.isoformat()
    dataset_hash = hashlib.sha256(raw_bytes).hexdigest()
    records: list[dict[str, Any]] = []

    for index, mentor in enumerate(raw_records):
        if not isinstance(mentor, dict):
            raise ValueError(f"旧导师记录 {index} 不是对象")

        fields = {
            field_name: mentor[field_name]
            for field_name in CORE_REVIEW_FIELDS
            if mentor.get(field_name) not in (None, "", [])
        }
        provenance = {
            field_name: [
                {
                    "source_type": "unknown",
                    "source_ref": (
                        f"legacy-dataset:{dataset_hash}#/{index}/{field_name}"
                    ),
                    "captured_at": timestamp,
                    "verification_status": "unverified",
                    "consent_id": None,
                    "confidence": 0,
                }
            ]
            for field_name in fields
        }
        quarantined_fields = {
            field_name: {
                "reason_code": _reason_for(field_name),
                "quarantined_at": timestamp,
                "legacy_pointer": f"removed-legacy-dataset#/{index}/{field_name}",
                "value_retained": False,
            }
            for field_name in mentor
            if field_name not in CORE_REVIEW_FIELDS
        }
        records.append(
            {
                "schema_version": "2.0",
                "advisor_id": _stable_legacy_id(index, mentor),
                "fields": fields,
                "provenance": provenance,
                "governance": {
                    "review_status": "pending_review",
                    "publication_status": "restricted",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "verified_at": None,
                    "expires_at": None,
                    "authorization": {
                        "basis": "legacy_seed",
                        "consent_id": None,
                        "scope": [],
                        "authorized_at": None,
                        "expires_at": None,
                    },
                    "takedown": {
                        "status": "active",
                        "requested_at": None,
                        "effective_at": None,
                        "reason": None,
                    },
                },
                "quarantined_fields": quarantined_fields,
            }
        )

    return MentorDataset.model_validate(
        {
            "schema_version": "2.0",
            "generated_at": timestamp,
            "source": {
                "source_type": "legacy_seed",
                "content_sha256": dataset_hash,
                "original_record_count": len(raw_records),
                "raw_retained": False,
            },
            "records": records,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="旧 mentors.json")
    parser.add_argument("--output", required=True, help="治理数据集输出路径")
    parser.add_argument(
        "--as-of",
        help="带时区 ISO-8601；省略时使用当前 UTC 时间",
    )
    args = parser.parse_args()

    generated_at = (
        datetime.fromisoformat(args.as_of)
        if args.as_of
        else datetime.now(timezone.utc)
    )
    input_path = Path(args.input)
    output_path = Path(args.output)
    dataset = migrate_payload(
        input_path.read_bytes(),
        generated_at=generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            dataset.model_dump(mode="json", exclude_none=False),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    quarantined_count = sum(
        len(record.quarantined_fields) for record in dataset.records
    )
    print(
        f"migrated={len(dataset.records)} "
        f"published=0 quarantined_fields={quarantined_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
