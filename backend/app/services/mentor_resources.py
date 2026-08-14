"""Public mentor-resource grouping and aggregate views.

Raw governance records remain immutable.  This module only builds a public
read model that joins independently published profile/catalog resources for
the same advisor and never invents missing facts or scores.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections import Counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit


OFFICIAL_DEPARTMENTS = (
    "建筑学院",
    "土木水利学院",
    "环境学院",
    "机械工程系",
    "精密仪器系",
    "能源与动力工程系",
    "车辆与运载学院",
    "工业工程系",
    "自动化系",
    "计算机科学与技术系",
    "电子工程系",
    "电机工程与应用电子技术系",
    "材料学院",
    "航天航空学院",
    "工程物理系",
    "化学工程系",
    "交叉信息研究院",
    "软件学院",
    "网络科学与网络空间研究院",
    "集成电路学院",
    "医学院",
    "临床医学院",
    "万科公共卫生与健康学院",
    "药学院",
    "生命科学学院",
    "化学系",
    "物理系",
    "数学科学系",
    "经济管理学院",
    "公共管理学院",
    "五道口金融学院",
    "人文学院",
    "社会科学学院",
    "法学院",
    "新闻与传播学院",
    "美术学院",
    "马克思主义学院",
    "教育研究院",
    "深圳国际研究生院",
    "新雅书院",
    "探微书院",
    "未央书院",
    "行健书院",
    "致理书院",
    "日新书院",
    "苏世民书院",
)

_RESOURCE_PRIORITY = {
    "verified_mentor_profile": 0,
    "mentor_catalog_entry": 1,
    "advisor_group_catalog_entry": 2,
}

_REVIEWED_NAME_OVERRIDES = {
    "JI JOHN S": "John S. Ji",
    "RICHARDSON SOL": "Sol Richardson",
}

_LIST_FIELDS = (
    "catalog_entries",
    "catalog_types",
    "programs",
    "research_keywords",
)

_cached_source: list[dict[str, Any]] | None = None
_cached_grouped: list[dict[str, Any]] | None = None


def _normalized_identity(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w\u3400-\u9fff]+", text))


def _display_name(value: object) -> str:
    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    if name in _REVIEWED_NAME_OVERRIDES:
        return _REVIEWED_NAME_OVERRIDES[name]
    if name and re.fullmatch(r"[A-Z][A-Z .'-]*", name):
        return " ".join(
            part if len(part) == 1 else part.capitalize()
            for part in name.split()
        )
    return name


def _unique(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(copy.deepcopy(item))
    return result


def _normalize_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, "")
    )


def _merge_provenance(records: list[dict[str, Any]]) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    markers: dict[str, set[tuple[str, str]]] = {}
    for record in records:
        for field, citations in (record.get("provenance") or {}).items():
            target = merged.setdefault(field, [])
            field_markers = markers.setdefault(field, set())
            for citation in citations or []:
                marker = (
                    _normalize_url(citation.get("source_url")),
                    str(citation.get("evidence_id", "")),
                )
                if marker in field_markers:
                    continue
                field_markers.add(marker)
                target.append(copy.deepcopy(citation))
    return merged


def group_mentor_resources(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join profile/catalog resources by stable published identity facts."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            str(record.get("entity_type") or "person"),
            _normalized_identity(record.get("name")),
            _normalized_identity(record.get("dept")),
        )
        grouped.setdefault(key, []).append(record)

    result: list[dict[str, Any]] = []
    for members in grouped.values():
        ordered = sorted(
            members,
            key=lambda item: (
                _RESOURCE_PRIORITY.get(str(item.get("resource_type")), 99),
                str(item.get("advisor_id", "")),
            ),
        )
        primary = copy.deepcopy(ordered[0])
        primary["name"] = _display_name(primary.get("name"))
        primary["resource_types"] = sorted(
            {
                str(item.get("resource_type"))
                for item in ordered
                if item.get("resource_type")
            },
            key=lambda value: _RESOURCE_PRIORITY.get(value, 99),
        )
        primary["linked_resource_ids"] = [
            str(item.get("advisor_id"))
            for item in ordered
            if item.get("advisor_id")
        ]
        primary["resource_record_count"] = len(ordered)
        primary["provenance"] = _merge_provenance(ordered)

        for field in _LIST_FIELDS:
            primary[field] = _unique(
                [value for item in ordered for value in (item.get(field) or [])]
            )
        for field in ("official_homepage", "title", "academic_year"):
            if not primary.get(field):
                primary[field] = next(
                    (item.get(field) for item in ordered if item.get(field)),
                    primary.get(field),
                )
        result.append(primary)
    return result


def grouped_mentor_resources(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reuse the grouped read model while the immutable source list is unchanged."""
    global _cached_source, _cached_grouped
    if records is not _cached_source or _cached_grouped is None:
        _cached_source = records
        _cached_grouped = group_mentor_resources(records)
    return _cached_grouped


def department_options(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = grouped_mentor_resources(records)
    counts = Counter(
        str(item.get("dept") or "").strip()
        for item in grouped
        if str(item.get("dept") or "").strip()
    )
    ordered = list(OFFICIAL_DEPARTMENTS)
    ordered.extend(sorted(name for name in counts if name not in set(ordered)))
    return [{"name": name, "advisor_count": counts.get(name, 0)} for name in ordered]


def mentor_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = grouped_mentor_resources(records)
    departments = Counter(
        str(item.get("dept") or "未标注院系").strip() or "未标注院系"
        for item in grouped
    )
    resource_types = Counter(
        str(item.get("resource_type") or "unknown") for item in records
    )
    return {
        "departments": [
            {"name": name, "advisor_count": count}
            for name, count in sorted(
                departments.items(), key=lambda pair: (-pair[1], pair[0])
            )[:12]
        ],
        "resource_types": [
            {"resource_type": name, "resource_count": resource_types.get(name, 0)}
            for name in (
                "verified_mentor_profile",
                "mentor_catalog_entry",
                "advisor_group_catalog_entry",
            )
        ],
        "meta": {
            "grouped_advisors": len(grouped),
            "raw_resource_records": len(records),
            "basis": "published_resources_only",
        },
    }
