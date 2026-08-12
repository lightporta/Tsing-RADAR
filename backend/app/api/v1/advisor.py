"""Formal mentor-resource search API."""

from __future__ import annotations

import math
import unicodedata
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.services.data_loader import load_mentors, mentor_data_summary

router = APIRouter()


def _search_text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(_search_text(item) for item in value)
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


@router.get("/mentors")
def get_all_mentors(
    q: str | None = Query(default=None, max_length=100),
    dept: str | None = Query(default=None, max_length=100),
    resource_type: Literal[
        "verified_mentor_profile",
        "mentor_catalog_entry",
        "advisor_group_catalog_entry",
    ]
    | None = None,
    entity_type: Literal["person", "advisor_group"] | None = None,
    catalog_type: Literal[
        "doctoral_general",
        "doctoral_recommendation_exempt",
    ]
    | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Search published resources with bounded, deterministic pagination."""
    records = load_mentors()
    query = _search_text(q).strip() if q else ""
    department = _search_text(dept).strip() if dept else ""

    def selected(record: dict) -> bool:
        if resource_type and record.get("resource_type") != resource_type:
            return False
        if entity_type and record.get("entity_type") != entity_type:
            return False
        if department and department not in _search_text(record.get("dept")):
            return False
        if catalog_type and catalog_type not in (record.get("catalog_types") or []):
            return False
        if query:
            haystack = _search_text(
                [
                    record.get("name"),
                    record.get("dept"),
                    record.get("title"),
                    record.get("programs", []),
                    record.get("research_keywords", []),
                ]
            )
            if query not in haystack:
                return False
        return True

    filtered = sorted(
        (record for record in records if selected(record)),
        key=lambda item: (
            _search_text(item.get("dept")),
            _search_text(item.get("name")),
            str(item.get("advisor_id", "")),
        ),
    )
    offset = (page - 1) * page_size
    meta = {
        **mentor_data_summary(),
        "filtered_records": len(filtered),
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(len(filtered) / page_size) if filtered else 0,
    }
    return {"data": filtered[offset : offset + page_size], "meta": meta}


@router.get("/mentors/sort")
def sort_mentors(metric: str):
    """Reject legacy subjective rankings in the formal product."""
    raise HTTPException(
        status_code=410,
        detail="正式版不提供无证据的主观导师排序；请使用导师检索和证据化匹配。",
    )
