"""四象限散点图数据路由。"""

from fastapi import APIRouter

from app.services.constants import DEPT_COLORS, DEPT_FALLBACK_COLOR
from app.services.data_loader import load_mentors

router = APIRouter()


@router.get("/scatter")
def scatter():
    """返回散点图数据：x=popularity, y=sector(0=国,1=私), color 按院系分配。"""
    points = []
    for m in load_mentors():
        dept = m.get("dept", "")
        points.append(
            {
                "name": m.get("name", ""),
                "x": float(m.get("popularity", 0)),
                "y": 0 if m.get("sector", "国") == "国" else 1,
                "color": DEPT_COLORS.get(dept, DEPT_FALLBACK_COLOR),
                "dept": dept,
            }
        )
    return {"data": points}
