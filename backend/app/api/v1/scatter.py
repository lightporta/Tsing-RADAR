"""四象限散点图数据路由。"""

from fastapi import APIRouter

from app.services.constants import DEPT_COLORS, DEPT_FALLBACK_COLOR
from app.services.data_loader import load_mentors, mentor_data_summary
from app.services.mentor_catalog import enriched_mentor_resources

router = APIRouter()


@router.get("/scatter")
def scatter():
    """返回散点图数据：x=popularity, y=sector(0=国,1=私), color 按院系分配。"""
    resources, gate = enriched_mentor_resources(load_mentors())
    points = []
    for m in resources:
        if m.get("popularity") is None or m.get("sector") not in {"国", "私"}:
            continue
        dept = m.get("dept", "")
        points.append(
            {
                "name": m.get("name", ""),
                "x": float(m["popularity"]),
                "y": 0 if m["sector"] == "国" else 1,
                "color": DEPT_COLORS.get(dept, DEPT_FALLBACK_COLOR),
                "dept": dept,
            }
        )
    return {
        "data": points,
        "meta": {
            **mentor_data_summary(),
            "score_evidence_gate": gate,
            "omitted_without_axis_evidence": (
                len(resources) - len(points)
            ),
        },
    }
