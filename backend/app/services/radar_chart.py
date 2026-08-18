"""确定性雷达图渲染（SVG + reportlab Drawing）。

设计约定（与前端 useRadarOption.ts / variables.scss 对齐）：
- 输出确定性：固定尺寸/坐标/文本，无时间戳、无随机值，可直接做字节级合同测试；
- 数据源仅为 mentor_score_governance.public_score_bundles 输出的已审核评分（公开数据）；
- 视觉语义：导师特质 = 橙色实线（#FF9500），网格/文字沿用前端设计令牌色。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.services.constants import TRAIT_KEYS

RADAR_DIMENSION_LABELS: dict[str, str] = {
    "acumen": "学术敏锐度",
    "network": "人脉资源",
    "mentorship": "指导意愿",
    "tolerance": "性格包容度",
    "funding": "经费实力",
    "efficiency": "产出效率",
}

# public_score_bundles 的 values 键名（trait_* 前缀）
TRAIT_VALUE_KEYS: list[str] = [f"trait_{key}" for key in TRAIT_KEYS]

ADVISOR_TRAIT_COLOR = "#FF9500"
ADVISOR_TRAIT_FILL_OPACITY = 0.45
GRID_COLOR = "#E4E7ED"
AXIS_COLOR = "#C0C4CC"
AXIS_TEXT_COLOR = "#606266"
TITLE_COLOR = "#303133"
NOTE_COLOR = "#909399"
LEGEND_COLOR = "#606266"

GRID_STEPS = (20, 40, 60, 80, 100)


@dataclass(frozen=True)
class RadarSeries:
    """单条雷达系列；values 顺序与 TRAIT_KEYS 对齐，取值 0~100。"""

    name: str
    values: list[float]
    color: str
    line_type: str = "solid"


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _vertex(cx: float, cy: float, radius: float, index: int, count: int) -> tuple[float, float]:
    angle = math.radians(index * 360.0 / count)
    return (cx + radius * math.sin(angle), cy - radius * math.cos(angle))


def radar_series_from_bundle(
    bundle: dict[str, Any],
    *,
    name: str = "导师特质（已审核评分）",
) -> RadarSeries | None:
    """从 public_score_bundles 的单个 bundle 提取六维系列；缺任一维度返回 None。"""
    values_raw = bundle.get("values") or {}
    values: list[float] = []
    for key in TRAIT_VALUE_KEYS:
        raw = values_raw.get(key)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return None
        value = float(raw)
        if not 0.0 <= value <= 100.0:
            return None
        values.append(value)
    return RadarSeries(name=name, values=values, color=ADVISOR_TRAIT_COLOR)


def build_radar_series_for_advisor(
    advisor_id: str,
    bundles: dict[str, dict[str, Any]] | None = None,
) -> RadarSeries | None:
    """按 advisor_id 取已审核六维评分；门控关闭或无该导师数据时返回 None（诚实空态）。"""
    if bundles is None:
        from app.services.mentor_score_governance import public_score_bundles

        bundles, _status = public_score_bundles()
    bundle = bundles.get(str(advisor_id))
    if bundle is None:
        return None
    return radar_series_from_bundle(bundle)


def render_radar_svg(
    *,
    series: list[RadarSeries],
    title: str = "导师特质雷达图",
    sample_note: str | None = None,
    width: int = 640,
    height: int = 480,
) -> str:
    """确定性 SVG 字符串：标题 + 六轴雷达 + 图例 + 样本说明。"""
    cx, cy = width / 2.0, height / 2.0 + 10
    radius = min(width, height) * 0.30
    axis_count = len(TRAIT_KEYS)
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape_xml(title)}">',
    ]

    parts.append(
        f'<text x="{width / 2.0:.1f}" y="30" text-anchor="middle" '
        f'font-size="16" font-weight="600" fill="{TITLE_COLOR}">{_escape_xml(title)}</text>'
    )

    # 网格环（20~100）与轴线
    for step in GRID_STEPS:
        ratio = step / 100.0
        ring_radius = radius * ratio
        points = " ".join(
            f"{x:.2f},{y:.2f}"
            for x, y in (
                _vertex(cx, cy, ring_radius, i, axis_count) for i in range(axis_count)
            )
        )
        parts.append(
            f'<polygon points="{points}" fill="none" stroke="{GRID_COLOR}" '
            f'stroke-width="1"/>'
        )
    for i in range(axis_count):
        x, y = _vertex(cx, cy, radius, i, axis_count)
        parts.append(
            f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{x:.2f}" y2="{y:.2f}" '
            f'stroke="{AXIS_COLOR}" stroke-width="1"/>'
        )

    # 轴标签
    for i, key in enumerate(TRAIT_KEYS):
        lx, ly = _vertex(cx, cy, radius + 22, i, axis_count)
        anchor = "middle"
        if lx < cx - 4:
            anchor = "end"
        elif lx > cx + 4:
            anchor = "start"
        parts.append(
            f'<text x="{lx:.2f}" y="{ly + 4:.2f}" text-anchor="{anchor}" '
            f'font-size="12" fill="{AXIS_TEXT_COLOR}">'
            f"{_escape_xml(RADAR_DIMENSION_LABELS[key])}</text>"
        )

    # 数据系列
    for item in series:
        points = " ".join(
            f"{x:.2f},{y:.2f}"
            for x, y in (
                _vertex(cx, cy, radius * (value / 100.0), i, axis_count)
                for i, value in enumerate(item.values)
            )
        )
        stroke_dash = (
            ' stroke-dasharray="6 4"' if item.line_type == "dashed" else ""
        )
        parts.append(
            f'<polygon points="{points}" fill="{item.color}" '
            f'fill-opacity="{ADVISOR_TRAIT_FILL_OPACITY}" stroke="{item.color}" '
            f'stroke-width="2.5"{stroke_dash}/>'
        )

    # 图例
    legend_y = height - 34
    legend_gap = min(220, max(140, width // max(len(series), 1) - 60))
    for index, item in enumerate(series):
        lx = width / 2.0 - (len(series) - 1) * legend_gap / 2.0 + index * legend_gap
        parts.append(
            f'<rect x="{lx:.2f}" y="{legend_y}" width="12" height="12" '
            f'fill="{item.color}" fill-opacity="{ADVISOR_TRAIT_FILL_OPACITY}" '
            f'stroke="{item.color}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{lx + 18:.2f}" y="{legend_y + 11}" font-size="12" '
            f'fill="{LEGEND_COLOR}">{_escape_xml(item.name)}</text>'
        )

    if sample_note:
        parts.append(
            f'<text x="{width / 2.0:.1f}" y="{height - 10}" text-anchor="middle" '
            f'font-size="11" fill="{NOTE_COLOR}">{_escape_xml(sample_note)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_radar_drawing(
    *,
    series: list[RadarSeries],
    title: str,
    sample_note: str | None = None,
    width: int = 340,
    height: int = 300,
    font_name: str = "Helvetica",
    font_size_axis: int = 8,
):
    """reportlab graphics 版本，供 PDF 报告内嵌（颜色/布局与 SVG 版一致）。"""
    from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    cx, cy = width / 2.0, height / 2.0 + 6
    radius = min(width, height) * 0.30
    axis_count = len(TRAIT_KEYS)
    stroke_color = colors.HexColor(ADVISOR_TRAIT_COLOR)
    grid_color = colors.HexColor(GRID_COLOR)
    axis_color = colors.HexColor(AXIS_COLOR)

    drawing.add(
        String(
            width / 2.0,
            height - 12,
            title,
            fontName=font_name,
            fontSize=10,
            fillColor=colors.HexColor(TITLE_COLOR),
            textAnchor="middle",
        )
    )

    for step in GRID_STEPS:
        ring_radius = radius * step / 100.0
        points: list[float] = []
        for i in range(axis_count):
            x, y = _vertex(cx, cy, ring_radius, i, axis_count)
            points.extend((x, y))
        drawing.add(
            Polygon(
                points,
                fillColor=None,
                strokeColor=grid_color,
                strokeWidth=0.5,
            )
        )
    for i in range(axis_count):
        x, y = _vertex(cx, cy, radius, i, axis_count)
        drawing.add(
            Line(cx, cy, x, y, strokeColor=axis_color, strokeWidth=0.5)
        )

    for i, key in enumerate(TRAIT_KEYS):
        lx, ly = _vertex(cx, cy, radius + 16, i, axis_count)
        drawing.add(
            String(
                lx,
                ly,
                RADAR_DIMENSION_LABELS[key],
                fontName=font_name,
                fontSize=font_size_axis,
                fillColor=colors.HexColor(AXIS_TEXT_COLOR),
                textAnchor="middle",
            )
        )

    for item in series:
        points = []
        for i, value in enumerate(item.values):
            x, y = _vertex(cx, cy, radius * (value / 100.0), i, axis_count)
            points.extend((x, y))
        drawing.add(
            Polygon(
                points,
                fillColor=colors.Color(
                    stroke_color.red,
                    stroke_color.green,
                    stroke_color.blue,
                    alpha=ADVISOR_TRAIT_FILL_OPACITY,
                ),
                strokeColor=stroke_color,
                strokeWidth=1.5,
            )
        )

    if sample_note:
        drawing.add(
            String(
                width / 2.0,
                6,
                sample_note,
                fontName=font_name,
                fontSize=7,
                fillColor=colors.HexColor(NOTE_COLOR),
                textAnchor="middle",
            )
        )
    return drawing
