"""散点图数据路由（客观数据驱动，与主观评价严格分离）。"""

from fastapi import APIRouter

from app.services.constants import DEPT_COLORS, DEPT_FALLBACK_COLOR
from app.services.data_loader import load_mentors, mentor_data_summary
from app.services.mentor_catalog import enriched_mentor_resources

router = APIRouter()


@router.get("/scatter")
def scatter():
    """返回散点图数据：x=项目广度, y=研究主题广度（已审核客观证据），color 按院系分配。"""
    resources, gate = enriched_mentor_resources(load_mentors())
    points = []
    for m in resources:
        objective = m.get("objective_radar") or {}
        x = objective.get("project_breadth")
        y = objective.get("topic_breadth")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        dept = m.get("dept", "")
        points.append(
            {
                "name": m.get("name", ""),
                "x": float(x),
                "y": float(y),
                "color": DEPT_COLORS.get(dept, DEPT_FALLBACK_COLOR),
                "dept": dept,
            }
        )
    return {
        "data": points,
        "meta": {
            **mentor_data_summary(),
            "score_evidence_gate": gate,
            "x_dimension": "project_breadth",
            "y_dimension": "topic_breadth",
            "omitted_without_axis_evidence": (
                len(resources) - len(points)
            ),
        },
    }
