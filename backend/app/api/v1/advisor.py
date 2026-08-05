"""[PATCH] 导师列表与排序路由。

修改点：
- GET /mentors 添加分页参数 page/size
- 响应增加 total/page/size 字段
- 添加 response_model 声明（通过 dict 类型提示）
"""

from fastapi import APIRouter, HTTPException, Query

from app.services.constants import SORT_METRICS
from app.services.data_loader import load_mentors

router = APIRouter()


@router.get("/mentors")
def get_all_mentors(
    # [PATCH] 添加分页参数
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """返回扩展后的导师数据（含 radar_traits/popularity/sector/projects/recruitments）。

    [PATCH] 添加分页支持：page/size 参数，响应包含 total/page/size。
    """
    all_mentors = load_mentors()
    total = len(all_mentors)
    start = (page - 1) * size
    end = start + size
    return {
        "data": all_mentors[start:end],
        "total": total,
        "page": page,
        "size": size,
    }


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
    return {"data": sorted_data, "metric": metric}
