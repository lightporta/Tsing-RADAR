"""证据化导师数据加载与发布门。"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Any

from app.schemas.governance import MentorDataset

_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "mentors.evidence.json",
)


@lru_cache(maxsize=1)
def load_mentor_dataset() -> MentorDataset:
    """读取并严格验证治理数据集；验证失败时拒绝启动数据链路。"""
    with open(_DATA_PATH, "rb") as file:
        payload = file.read()
    expected_sha256 = os.getenv("MENTOR_DATA_EXPECTED_FILE_SHA256", "").strip()
    if expected_sha256 and hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("mentor_dataset_sha256_mismatch")
    dataset = MentorDataset.model_validate_json(payload)
    expected_published = os.getenv(
        "MENTOR_DATA_EXPECTED_PUBLISHED_COUNT", ""
    ).strip()
    if expected_published:
        try:
            expected_count = int(expected_published)
        except ValueError as exc:
            raise RuntimeError("mentor_dataset_expected_count_invalid") from exc
        actual_count = sum(
            record.to_public_dict() is not None for record in dataset.records
        )
        if actual_count != expected_count:
            raise RuntimeError("mentor_dataset_published_count_mismatch")
    return dataset


@lru_cache(maxsize=1)
def load_mentors() -> list[dict[str, Any]]:
    """只返回已发布导师字段与脱敏 citation，供公开 API 使用。"""
    published: list[dict[str, Any]] = []
    for record in load_mentor_dataset().records:
        public_record = record.to_public_dict()
        if public_record is not None:
            published.append(public_record)
    return published


@lru_cache(maxsize=1)
def load_match_candidates() -> list[dict[str, Any]]:
    """返回服务端匹配所需的完整证据；调用方必须再次投影为公开解释。"""
    candidates: list[dict[str, Any]] = []
    for record in load_mentor_dataset().records:
        candidate = record.to_internal_match_dict()
        if candidate is not None and candidate.get("resource_type") not in {
            "mentor_catalog_entry",
            "advisor_group_catalog_entry",
        }:
            candidates.append(candidate)
    return candidates


def mentor_data_summary() -> dict[str, int | str]:
    """返回不含导师内容的数据治理计数。"""
    records = load_mentor_dataset().records
    published_count = len(load_mentors())
    return {
        "total_records": len(records),
        "published_records": published_count,
        "withheld_records": len(records) - published_count,
        "policy": "verified_only",
    }


def load_mentor_review_records() -> list[dict[str, Any]]:
    """供离线审核使用；不通过 API 暴露，且隔离项不含原始值。"""
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in load_mentor_dataset().records
    ]


def reload_mentors() -> list[dict[str, Any]]:
    """清除缓存并重新执行治理校验。"""
    load_mentors.cache_clear()
    load_match_candidates.cache_clear()
    load_mentor_dataset.cache_clear()
    return load_mentors()
