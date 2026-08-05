"""证据化导师数据加载与发布门。"""

from __future__ import annotations

import json
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
    with open(_DATA_PATH, "r", encoding="utf-8") as file:
        return MentorDataset.model_validate(json.load(file))


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
        if candidate is not None:
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
