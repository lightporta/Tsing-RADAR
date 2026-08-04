"""导师列表与排序路由。"""

from fastapi import APIRouter, HTTPException

from app.services.constants import SORT_METRICS
from app.services.data_loader import load_mentors, mentor_data_summary

router = APIRouter()


@router.get("/mentors")
def get_all_mentors():
    """只返回通过证据审核与发布门的导师数据。"""
    return {"data": load_mentors(), "meta": mentor_data_summary()}


@router.get("/mentors/sort")
def sort_mentors(metric: str):
    """按指标降序排序导师。metric ∈ 六维雷达指标 + popularity。"""
    if metric not in SORT_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的指标: {metric}，支持: {sorted(SORT_METRICS)}",
        )

    def metric_value(m: dict) -> float:
        if metric == "popularity":
            return float(m.get("popularity", 0))
        return float((m.get("radar_traits", {}) or {}).get(metric, 0))

    sorted_data = sorted(load_mentors(), key=metric_value, reverse=True)
    return {
        "data": sorted_data,
        "metric": metric,
        "meta": mentor_data_summary(),
    }
