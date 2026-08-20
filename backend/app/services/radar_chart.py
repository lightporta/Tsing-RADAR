"""确定性客观雷达图渲染（SVG + reportlab Drawing）。

设计约定（与前端 useRadarOption.ts / variables.scss 对齐）：
- 输出确定性：固定尺寸/坐标/文本，无时间戳、无随机值，可直接做字节级合同测试；
- 数据源仅为 mentor_score_governance.public_score_bundles 输出的已审核客观评分；
- 客观四维与匿名主观评价严格分离：本渲染器只画公开证据支撑的客观维度，
  学生主观六维评价走 advisor_ratings 管线，不进入本图；
- 视觉语义：客观证据 = 橙色实线（#FF9500），网格/文字沿用前端设计令牌色。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# 客观雷达四维（顺序即渲染轴序）
OBJECTIVE_DIMENSION_KEYS: list[str] = [
    "project_breadth",
    "topic_breadth",
    "contact_completeness",
    "material_completeness",
]

RADAR_DIMENSION_LABELS: dict[str, str] = {
    "project_breadth": "项目广度",
    "topic_breadth": "研究主题广度",
    "contact_completeness": "联系信息完整度",
    "material_completeness": "研究资料完整度",
}

ADVISOR_TRAIT_COLOR = "#FF9500"
GRID_COLOR = "#E4E7ED"
AXIS_COLOR = "#C0C4CC"
AXIS_TEXT_COLOR = "#606266"
TITLE_COLOR = "#303133"
NOTE_COLOR = "#909399"
LEGEND_COLOR = "#606266"

GRID_STEPS = (20, 40, 60, 80, 100)

# —— 文本版雷达图（仅对话端口）——
_TEXT_CANVAS_W = 25
_TEXT_CANVAS_H = 13
_TEXT_CENTER = (12, 6)
_TEXT_RADIUS = (12, 6)  # (x 半径, y 半径)，字符宽高比约 2:1，视觉接近正菱形
_TEXT_BAR_LEN = 20      # 数值条形长度（满格 100）


def _line_points(
    x0: int, y0: int, x1: int, y1: int
) -> list[tuple[int, int]]:
    """整数网格 Bresenham 线段。"""
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _text_vertex(value: float, axis: int) -> tuple[int, int]:
    """文本画布四轴顶点：0 上 / 1 右 / 2 下 / 3 左（与 SVG 轴序一致）。"""
    cx, cy = _TEXT_CENTER
    rx, ry = _TEXT_RADIUS
    ratio = value / 100.0
    if axis == 0:
        return (cx, cy - round(ry * ratio))
    if axis == 1:
        return (cx + round(rx * ratio), cy)
    if axis == 2:
        return (cx, cy + round(ry * ratio))
    return (cx - round(rx * ratio), cy)


def _render_text_polygon(values: list[float]) -> str:
    """把 0~100 四维值渲染为 4 轴字符雷达多边形（网格环 + 数据边缘勾连）。

    v3.1.5：数据多边形只描边不填充（边缘线图风格），与 SVG/PDF 版一致。
    """
    width, height = _TEXT_CANVAS_W, _TEXT_CANVAS_H
    grid: list[list[str]] = [[" "] * width for _ in range(height)]

    # 网格环（20~100）与轴线：浅色点线
    for step in GRID_STEPS:
        ring = [_text_vertex(float(step), i) for i in range(4)]
        for i in range(4):
            for x, y in _line_points(*ring[i], *ring[(i + 1) % 4]):
                if grid[y][x] == " ":
                    grid[y][x] = "·"
    cx, cy = _TEXT_CENTER
    for axis in range(4):
        for x, y in _line_points(cx, cy, *_text_vertex(100.0, axis)):
            if grid[y][x] == " ":
                grid[y][x] = "·"

    # 数据多边形：只勾连边缘（覆盖网格）
    if len(values) == 4:
        data_pts = [_text_vertex(float(v), i) for i, v in enumerate(values)]
        for i in range(4):
            for x, y in _line_points(*data_pts[i], *data_pts[(i + 1) % 4]):
                grid[y][x] = "█"

    return "\n".join("".join(row).rstrip() for row in grid)


def render_radar_text(
    *,
    series: RadarSeries,
    labels: dict[str, str] | None = None,
    title: str = "导师客观证据雷达图（文本版）",
    sample_note: str | None = None,
) -> str:
    """确定性文本雷达图：4 轴字符多边形 + 逐维度条形数值表。

    数据源与 render_radar_svg 完全一致（客观四维，已审核公开证据），
    供清小搭仅对话端口在不支持图片附件时直接渲染；诚实性约定相同：
    无已审核数据时由调用方输出诚实空态，本函数不画推断值。
    """
    dimension_labels = labels or RADAR_DIMENSION_LABELS
    lines: list[str] = [title]
    lines.append("")
    lines.append(_render_text_polygon(list(series.values)))
    lines.append("")
    for key, value in zip(OBJECTIVE_DIMENSION_KEYS, series.values):
        label = dimension_labels.get(key, key)
        filled = round(float(value) / 100.0 * _TEXT_BAR_LEN)
        bar = "█" * filled + "░" * (_TEXT_BAR_LEN - filled)
        lines.append(f"{label}  {bar}  {value:.0f}")
    if sample_note:
        lines.append("")
        lines.append(sample_note)
    return "\n".join(lines)


@dataclass(frozen=True)
class RadarSeries:
    """单条雷达系列；values 顺序与 OBJECTIVE_DIMENSION_KEYS 对齐，取值 0~100。"""

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
    name: str = "客观证据（已审核）",
) -> RadarSeries | None:
    """从 public_score_bundles 的单个 bundle 提取客观四维系列；缺任一维度返回 None。"""
    values_raw = bundle.get("values") or {}
    values: list[float] = []
    for key in OBJECTIVE_DIMENSION_KEYS:
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
    """按 advisor_id 取已审核客观四维评分；门控关闭或无数据时返回 None（诚实空态）。"""
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
    title: str = "导师客观证据雷达图",
    sample_note: str | None = None,
    width: int = 640,
    height: int = 480,
) -> str:
    """确定性 SVG 字符串：标题 + 四轴客观雷达 + 图例 + 样本说明。"""
    cx, cy = width / 2.0, height / 2.0 + 10
    radius = min(width, height) * 0.30
    axis_count = len(OBJECTIVE_DIMENSION_KEYS)
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
    for i, key in enumerate(OBJECTIVE_DIMENSION_KEYS):
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

    # 数据系列：边缘线图勾连（v3.1.5 起不填充，仅描边多边形 + 顶点勾连点）
    for item in series:
        vertices = [
            _vertex(cx, cy, radius * (value / 100.0), i, axis_count)
            for i, value in enumerate(item.values)
        ]
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in vertices)
        stroke_dash = (
            ' stroke-dasharray="6 4"' if item.line_type == "dashed" else ""
        )
        parts.append(
            f'<polygon points="{points}" fill="none" stroke="{item.color}" '
            f'stroke-width="2.5"{stroke_dash}/>'
        )
        for x, y in vertices:
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{item.color}"/>'
            )

    # 图例
    legend_y = height - 34
    legend_gap = min(220, max(140, width // max(len(series), 1) - 60))
    for index, item in enumerate(series):
        lx = width / 2.0 - (len(series) - 1) * legend_gap / 2.0 + index * legend_gap
        parts.append(
            f'<rect x="{lx:.2f}" y="{legend_y}" width="12" height="12" '
            f'fill="none" stroke="{item.color}" stroke-width="1.5"/>'
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
    axis_count = len(OBJECTIVE_DIMENSION_KEYS)
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

    for i, key in enumerate(OBJECTIVE_DIMENSION_KEYS):
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
                fillColor=None,  # v3.1.5：边缘线图勾连，不填充
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
