"""证据化导师数据加载与发布门。"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Any

from app.schemas.governance import MentorDataset

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_REPO_ROOT = os.path.dirname(_BACKEND_ROOT)
_DATA_DIR = os.path.join(_BACKEND_ROOT, "data")
_DATA_PATH = os.path.join(_DATA_DIR, "mentors.evidence.json")
_SIMULATION_DATA_PATH = os.path.join(_DATA_DIR, "mentors.simulation.json")
_EMPTY_FALLBACK_PATH = os.path.join(
    _REPO_ROOT,
    "deploy",
    "production",
    "data",
    "empty-mentor-governance.json",
)

FORMAL_POLICY = "formal_verified_profiles_only"
SIMULATION_POLICY = "simulation_only_not_for_production"


def _simulation_enabled() -> bool:
    from app.core.config import settings

    return settings.simulation_mentors_enabled


def _active_data_path() -> str:
    """Resolve the active mentor dataset path under the simulation gate."""
    if _simulation_enabled():
        return _SIMULATION_DATA_PATH
    if os.path.isfile(_DATA_PATH):
        return _DATA_PATH
    from app.core.config import settings

    if settings.DEBUG and not settings.PRODUCTION_DEPLOYMENT:
        return _EMPTY_FALLBACK_PATH
    # An absent configured production dataset must never look like a healthy
    # empty catalogue. Opening this path raises the original FileNotFoundError.
    return _DATA_PATH


def _clear_loader_caches() -> None:
    load_mentors.cache_clear()
    load_match_candidates.cache_clear()
    load_mentor_dataset.cache_clear()


@lru_cache(maxsize=1)
def load_mentor_dataset() -> MentorDataset:
    """读取并严格验证治理数据集；验证失败时拒绝启动数据链路。"""
    data_path = _active_data_path()
    with open(data_path, "rb") as file:
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
    expected_match_candidates = os.getenv(
        "MENTOR_DATA_EXPECTED_MATCH_CANDIDATE_COUNT", ""
    ).strip()
    if expected_match_candidates:
        try:
            expected_candidate_count = int(expected_match_candidates)
        except ValueError as exc:
            raise RuntimeError(
                "mentor_dataset_expected_match_candidate_count_invalid"
            ) from exc
        actual_candidate_count = sum(
            _is_formal_match_candidate(record.to_internal_match_dict())
            for record in dataset.records
        )
        if actual_candidate_count != expected_candidate_count:
            raise RuntimeError("mentor_dataset_match_candidate_count_mismatch")
    return dataset


def _is_formal_match_candidate(candidate: dict[str, Any] | None) -> bool:
    """Only independently reviewed profile records may enter matching."""
    return bool(
        candidate
        and candidate.get("resource_type") == "verified_mentor_profile"
        and candidate.get("identity_status") == "verified"
        and candidate.get("recommendation_eligibility") == "eligible"
    )


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
        if _is_formal_match_candidate(candidate):
            candidates.append(candidate)
    return candidates


def mentor_data_policy() -> str:
    """Return the active mentor publication policy label."""
    if _simulation_enabled():
        return SIMULATION_POLICY
    return FORMAL_POLICY


def mentor_data_summary() -> dict[str, int | str]:
    """返回不含导师内容的数据治理计数。"""
    records = load_mentor_dataset().records
    published_count = len(load_mentors())
    match_candidate_count = len(load_match_candidates())
    catalog_count = sum(
        record.fields.get("resource_type")
        in {"mentor_catalog_entry", "advisor_group_catalog_entry"}
        and record.to_public_dict() is not None
        for record in records
    )
    profile_count = sum(
        record.fields.get("resource_type") == "verified_mentor_profile"
        and record.to_public_dict() is not None
        for record in records
    )
    return {
        "total_records": len(records),
        "published_records": published_count,
        "withheld_records": len(records) - published_count,
        "catalog_records": catalog_count,
        "verified_profile_records": profile_count,
        "match_candidate_records": match_candidate_count,
        "policy": mentor_data_policy(),
    }


def load_mentor_review_records() -> list[dict[str, Any]]:
    """供离线审核使用；不通过 API 暴露，且隔离项不含原始值。"""
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in load_mentor_dataset().records
    ]


def reload_mentors() -> list[dict[str, Any]]:
    """清除缓存并重新执行治理校验。"""
    _clear_loader_caches()
    return load_mentors()
