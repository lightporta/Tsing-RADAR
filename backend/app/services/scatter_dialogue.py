"""v2.5 四象限文本化分类（散点图 → 对话文本）。

诚实性设计：
- 复用的数据管线与 /scatter 接口完全一致（load_mentors →
  grouped_mentor_resources → score_enriched_resources），评分门未开放时
  绝不画"基准值"或伪造分类，输出诚实空态；
- 四象限按已审核客观证据双轴（项目广度 × 主题广度）分类，>60 视为
  「热」，与前端口径一致；体制属性（国/私）与热门度属历史推断字段，
  已按治理门禁剥离（D1 禁止字段），不在此公开，输出中明确标注。
"""

from __future__ import annotations

from typing import Any

from app.services.data_loader import load_mentors
from app.services.mentor_catalog import enriched_mentor_resources
from app.services.mentor_score_governance import public_score_bundles

QUADRANT_HOT_THRESHOLD = 60.0
QUADRANT_MAX_PER_GROUP = 3

_SCOPE_NOTE = (
    "四象限按已审核客观证据（项目广度 × 主题广度，>60 视为热）分类；"
    "体制属性（国/私）与热门度属历史推断字段，已按治理门禁剥离，不在此公开。"
)


def _is_hot(value: float | None) -> bool:
    return isinstance(value, (int, float)) and float(value) > QUADRANT_HOT_THRESHOLD


def quadrant_key(x: float, y: float) -> tuple[bool, bool]:
    """返回 (项目广度是否热, 主题广度是否热)。"""
    return (_is_hot(x), _is_hot(y))


def quadrant_label(x_hot: bool, y_hot: bool) -> str:
    if x_hot and y_hot:
        return "双高活跃（项目广度、主题广度均高）"
    if x_hot:
        return "项目驱动型（项目广度高 · 主题广度偏低）"
    if y_hot:
        return "主题探索型（主题广度高 · 项目广度偏低）"
    return "聚焦深耕型（两轴均低于阈值）"


def _points_from_resources(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """与 /scatter 同一投影：只保留两轴都有数值的点。"""
    points: list[dict[str, Any]] = []
    for mentor in resources:
        objective = mentor.get("objective_radar") or {}
        x = objective.get("project_breadth")
        y = objective.get("topic_breadth")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        points.append(
            {
                "name": mentor.get("name") or "",
                "dept": mentor.get("dept") or "",
                "advisor_id": str(mentor.get("advisor_id") or ""),
                "x": float(x),
                "y": float(y),
            }
        )
    return points


def _honest_gate_closed(status: dict[str, Any]) -> str:
    reason = status.get("reason") or "score_evidence_file_not_configured_or_unavailable"
    lines = [
        "暂不能诚实地进行四象限分类：已审核客观评分门未开放"
        f"（{reason}），没有可公开的评分证据。",
        "",
        "说明：导师的客观评分需独立审核、覆盖率达到阈值后才会发布；"
        "发布前不会用推断值或默认值冒充评分。",
        "",
        f"分类口径说明：{_SCOPE_NOTE}",
    ]
    return "\n".join(lines)


def format_scatter_summary(points: list[dict[str, Any]]) -> str:
    """把散点按四象限分组输出为文本。"""
    groups: dict[tuple[bool, bool], list[dict[str, Any]]] = {
        (False, False): [],
        (False, True): [],
        (True, False): [],
        (True, True): [],
    }
    for point in points:
        groups[quadrant_key(point["x"], point["y"])].append(point)

    header = (
        f"导师四象限分布（共 {len(points)} 位有已审核客观证据）：\n{_SCOPE_NOTE}"
    )
    lines: list[str] = [header]
    for key in (
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ):
        members = sorted(
            groups[key],
            key=lambda point: point["x"] + point["y"],
            reverse=True,
        )[:QUADRANT_MAX_PER_GROUP]
        total = len(groups[key])
        if total == 0:
            continue
        lines.append("")
        lines.append(
            f"■ {quadrant_label(*key)}（{total} 位"
            + ("，展示 3 位" if total > QUADRANT_MAX_PER_GROUP else "")
            + "）："
        )
        for point in members:
            dept = point["dept"]
            dept_suffix = f" · {dept}" if dept else ""
            lines.append(
                f"  · {point['name']}{dept_suffix}"
                f"（项目广度 {point['x']:.0f} · 主题广度 {point['y']:.0f}）"
            )
    lines.append("")
    lines.append("需要的话，我可以针对某个象限的导师做进一步的匹配分析。")
    return "\n".join(lines)


async def handle_scatter_query(*, latest_user: str) -> tuple[str, Any]:
    """四象限查询入口：门控检查 → 投影 → 分组文本；返回 (text, attachment)。"""
    _bundles, status = public_score_bundles()
    if not status.get("gate_open"):
        return _honest_gate_closed(status), None
    resources, _gate = enriched_mentor_resources(load_mentors())
    points = _points_from_resources(resources)
    if not points:
        return (
            "评分门已开放，但当前没有同时具备项目广度与主题广度已审核证据的"
            "导师，暂不能进行四象限分类。\n\n"
            f"分类口径说明：{_SCOPE_NOTE}",
            None,
        )
    return format_scatter_summary(points), None
