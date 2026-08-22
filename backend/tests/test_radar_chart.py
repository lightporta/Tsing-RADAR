"""客观雷达图服务合同测试：确定性渲染、SVG 结构、门控与 reportlab Drawing。"""

from __future__ import annotations

import pytest

from app.services.radar_chart import (
    ADVISOR_TRAIT_COLOR,
    GRID_STEPS,
    OBJECTIVE_DIMENSION_KEYS,
    RADAR_DIMENSION_LABELS,
    RadarSeries,
    build_radar_series_for_advisor,
    radar_polygon_edge_cells,
    radar_series_from_bundle,
    render_radar_bars,
    render_radar_drawing,
    render_radar_svg,
    render_radar_text,
    render_radar_text_auto,
    select_radar_text_form,
)

SAMPLE_VALUES = [80.0, 60.0, 90.0, 70.0]


def _series(
    name: str = "客观证据（已审核）",
    values: list[float] | None = None,
) -> RadarSeries:
    return RadarSeries(
        name=name,
        values=list(SAMPLE_VALUES if values is None else values),
        color=ADVISOR_TRAIT_COLOR,
    )


def _bundle(values: list[object]) -> dict:
    return {
        "values": {
            key: value
            for key, value in zip(OBJECTIVE_DIMENSION_KEYS, values)
        }
    }


def test_render_radar_svg_is_byte_deterministic():
    kwargs = {
        "series": [_series()],
        "title": "导师客观证据雷达图（已审核）",
        "sample_note": "样本量与时间窗见详情页",
    }
    first = render_radar_svg(**kwargs)
    second = render_radar_svg(**kwargs)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_render_radar_svg_structure():
    svg = render_radar_svg(
        series=[_series()],
        title="导师客观证据雷达图",
        sample_note="样本说明",
    )
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<svg" in svg
    assert svg.endswith("</svg>")

    # 四条轴线（客观四维）
    assert len(OBJECTIVE_DIMENSION_KEYS) == 4
    assert svg.count("<line") == 4
    # 5 层网格 polygon + 1 条数据系列 polygon
    assert svg.count("<polygon") == len(GRID_STEPS) + 1
    assert len(GRID_STEPS) == 5
    # v3.1.5 边缘线图勾连：网格 + 数据多边形 + 图例 rect 全部无填充
    assert svg.count('fill="none"') == len(GRID_STEPS) + 2
    assert "fill-opacity" not in svg  # 锁死"无颜色填充"新语义
    # 数据系列顶点勾连点（单系列 4 顶点）
    assert svg.count("<circle") == len(OBJECTIVE_DIMENSION_KEYS)
    # 客观四维中文标签
    for label in RADAR_DIMENSION_LABELS.values():
        assert label in svg
    assert {
        "项目广度",
        "研究主题广度",
        "联系信息完整度",
        "研究资料完整度",
    } == set(RADAR_DIMENSION_LABELS.values())
    # 图例 rect 与客观证据橙色
    assert svg.count("<rect") == 1
    assert "#FF9500" in svg
    assert ADVISOR_TRAIT_COLOR == "#FF9500"
    assert "导师客观证据雷达图" in svg
    assert "样本说明" in svg


def test_render_radar_svg_escapes_xml_special_chars():
    raw_name = '张 & <导> "师"'
    raw_title = '雷达图 <A&B> "对比"'
    svg = render_radar_svg(
        series=[_series(name=raw_name)],
        title=raw_title,
    )
    assert raw_name not in svg
    assert raw_title not in svg
    assert "张 &amp; &lt;导&gt; &quot;师&quot;" in svg
    assert "雷达图 &lt;A&amp;B&gt; &quot;对比&quot;" in svg


def test_radar_series_from_bundle_returns_series_for_complete_bundle():
    series = radar_series_from_bundle(_bundle(SAMPLE_VALUES))
    assert series is not None
    assert series.values == SAMPLE_VALUES
    assert all(isinstance(value, float) for value in series.values)
    assert series.color == ADVISOR_TRAIT_COLOR
    assert series.name == "客观证据（已审核）"
    assert series.line_type == "solid"


@pytest.mark.parametrize(
    "values",
    [
        [80, 60, 90],  # 缺一个维度
        [80, 60, 90, 100.5],  # 越界 >100
        [80, 60, 90, -0.5],  # 越界 <0
        [80, 60, 90, True],  # bool 不是合法评分
        [80, 60, 90, False],
        [80, 60, 90, "85"],  # 字符串不合法
        [80, 60, 90, None],
    ],
)
def test_radar_series_from_bundle_rejects_incomplete_or_invalid(values):
    assert radar_series_from_bundle(_bundle(values)) is None


def test_radar_series_from_bundle_rejects_empty_values_mapping():
    assert radar_series_from_bundle({}) is None
    assert radar_series_from_bundle({"values": None}) is None
    assert radar_series_from_bundle({"values": {}}) is None


def test_radar_series_from_bundle_accepts_boundary_scores():
    series = radar_series_from_bundle(_bundle([0, 100, 0.0, 100.0]))
    assert series is not None
    assert series.values == [0.0, 100.0, 0.0, 100.0]


def test_build_radar_series_for_advisor_with_explicit_bundles():
    bundles = {"T00001": _bundle(SAMPLE_VALUES)}
    hit = build_radar_series_for_advisor("T00001", bundles)
    assert hit is not None
    assert hit.values == SAMPLE_VALUES

    assert build_radar_series_for_advisor("T99999", bundles) is None
    assert build_radar_series_for_advisor("T00001", {}) is None
    invalid = {"T00002": _bundle([80, 60, 90])}
    assert build_radar_series_for_advisor("T00002", invalid) is None


def test_render_radar_drawing_returns_reportlab_drawing():
    from reportlab.graphics.shapes import Drawing, Line, Polygon, String

    drawing = render_radar_drawing(
        series=[_series()],
        title="导师客观证据雷达图",
        sample_note="样本说明",
    )
    assert isinstance(drawing, Drawing)

    lines = [item for item in drawing.contents if isinstance(item, Line)]
    polygons = [item for item in drawing.contents if isinstance(item, Polygon)]
    strings = [item for item in drawing.contents if isinstance(item, String)]
    # 4 条轴线；5 层网格 + 1 条数据系列；标题 + 4 个轴标签 + 样本说明
    assert len(lines) == 4
    assert len(polygons) == len(GRID_STEPS) + 1
    # v3.1.5 边缘线图勾连：网格环与数据多边形均无填充
    assert all(polygon.fillColor is None for polygon in polygons)
    assert len(strings) == 1 + len(OBJECTIVE_DIMENSION_KEYS) + 1
    labels = {item.text for item in strings}
    assert "导师客观证据雷达图" in labels
    assert "样本说明" in labels
    for label in RADAR_DIMENSION_LABELS.values():
        assert label in labels


def test_render_radar_drawing_without_sample_note():
    from reportlab.graphics.shapes import Drawing, String

    drawing = render_radar_drawing(series=[_series()], title="雷达图")
    assert isinstance(drawing, Drawing)
    strings = [item for item in drawing.contents if isinstance(item, String)]
    assert len(strings) == 1 + len(OBJECTIVE_DIMENSION_KEYS)


def test_render_radar_text_is_deterministic_and_contains_chart_and_values():
    kwargs = dict(series=_series(), title="测试导师 雷达图", sample_note="样本说明")
    first = render_radar_text(**kwargs)
    second = render_radar_text(**kwargs)
    assert first == second  # 字节级确定性
    assert "测试导师 雷达图" in first
    assert "样本说明" in first
    # 数据多边形用实心块绘制（非空态）
    assert "█" in first
    # 逐维度数值与条形
    for key, value in zip(OBJECTIVE_DIMENSION_KEYS, SAMPLE_VALUES):
        label = RADAR_DIMENSION_LABELS[key]
        assert f"{label}" in first
        assert f"{value:.0f}" in first
    # 每个维度数值行含 █ 与 ░ 组成的条形
    for line in first.splitlines():
        if " ██" in line or "█" in line.split("  ")[-1]:
            pass
    bar_line = [ln for ln in first.splitlines() if "项目广度" in ln][0]
    assert "█" in bar_line and "░" in bar_line
    assert "  80" in bar_line


def test_render_radar_text_honest_zero_and_full_scale():
    full = render_radar_text(series=_series(values=[100.0] * 4))
    assert "100" in full
    zero = render_radar_text(series=_series(values=[0.0] * 4))
    assert "0" in zero
    # 全 0 时不画大面积填充，条形全空
    zero_bar = [ln for ln in zero.splitlines() if "项目广度" in ln][0]
    assert "░" * 20 in zero_bar


def test_render_radar_text_polygon_is_outline_not_filled():
    """v3.1.5：文本版数据多边形只勾连边缘，不做内部填充。"""
    full = render_radar_text(series=_series(values=[80.0, 100.0, 100.0, 100.0]))
    parts = full.split("\n\n")
    polygon = parts[1]  # 标题后第一个空行分隔出的字符块
    edge_cells = polygon.count("█")
    # 近满值多边形：边缘勾连约 48 格；若内部填充会显著更多（>120），
    # 上界 80 锁死"线图不填充"语义
    assert 0 < edge_cells < 80
    assert "·" in polygon  # 网格环保留
    # 各维数值条形仍带实心刻度（与线图多边形并存）
    bar_line = [ln for ln in full.splitlines() if "项目广度" in ln][0]
    assert "█" in bar_line and "░" in bar_line


def test_render_radar_text_axis_order_matches_objective_keys():
    """values 顺序与 OBJECTIVE_DIMENSION_KEYS 对齐（与 SVG 同一约定）。"""
    values = [10.0, 20.0, 30.0, 40.0]
    text = render_radar_text(series=_series(values=values))
    for idx, key in enumerate(OBJECTIVE_DIMENSION_KEYS):
        assert RADAR_DIMENSION_LABELS[key] in text
        assert f"{values[idx]:.0f}" in text


_BAR_CHARS = "█▉▊▋▌▍▎▏░"


def _display_width(text: str) -> int:
    """与渲染端同口径的显示宽度（East Asian W/F 记 2 列）。"""
    import unicodedata

    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text
    )


def _dimension_lines(rendered: str) -> list[str]:
    """按 OBJECTIVE_DIMENSION_KEYS 顺序取出各维度数值行。"""
    lines = []
    for key in OBJECTIVE_DIMENSION_KEYS:
        line = [
            ln
            for ln in rendered.splitlines()
            if RADAR_DIMENSION_LABELS[key] in ln
        ]
        assert line, f"缺少维度行：{key}"
        lines.append(line[0])
    return lines


def _bar_display_start(line: str) -> int:
    """行内条形首字符的显示列位置（按 CJK 宽度折算，标签列对齐的度量）。"""
    for index, char in enumerate(line):
        if char in _BAR_CHARS:
            return _display_width(line[:index])
    raise AssertionError(f"条形字符缺失：{line}")


def test_render_radar_text_value_columns_aligned_across_cjk_labels():
    """v4.1.0：维度名显示宽度不一致（4~7 个汉字）时条形列仍逐行对齐。"""
    text = render_radar_text(series=_series(values=[70.0, 45.0, 90.0, 30.0]))
    lines = _dimension_lines(text)
    assert len({_bar_display_start(ln) for ln in lines}) == 1
    # 数值列（行尾数值 token）同样按显示宽度对齐
    value_starts = {
        _display_width(ln) - _display_width(ln.rsplit("  ", 1)[-1])
        for ln in lines
    }
    assert len(value_starts) == 1


def test_render_radar_bars_is_deterministic_with_eighth_blocks():
    """v4.1.0 独立柱状图形态：字节级确定性 + 八分档块 + 空位补齐。"""
    kwargs = dict(series=_series(), title="测试导师 客观证据雷达图", sample_note="样本说明")
    first = render_radar_bars(**kwargs)
    second = render_radar_bars(**kwargs)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")
    assert "测试导师 客观证据雷达图" in first
    assert "样本说明" in first
    # 非整格维度（80/60/90/70 折算 24 格均带小数）出现八分档尾块
    assert any(char in first for char in "▏▎▍▌▋▊▉")
    # 柱状图形态用空位补齐（非 ░），条形列与数值列按显示宽度逐行对齐
    assert "░" not in first
    lines = _dimension_lines(first)
    assert len({_bar_display_start(ln) for ln in lines}) == 1
    value_starts = {
        _display_width(ln) - _display_width(ln.rsplit("  ", 1)[-1])
        for ln in lines
    }
    assert len(value_starts) == 1


def test_render_radar_bars_zero_and_full_scale():
    zero = render_radar_bars(series=_series(values=[0.0] * 4))
    zero_line = _dimension_lines(zero)[0]
    # 全 0：条形段（标签与数值之间）不含任何整格/分档块
    bar_segment = zero_line.rsplit("  ", 1)[0].split("  ", 1)[-1]
    assert bar_segment.strip() == ""
    assert zero_line.rstrip().endswith("0")
    full = render_radar_bars(series=_series(values=[100.0] * 4))
    full_line = _dimension_lines(full)[0]
    assert "█" * 24 in full_line
    assert full_line.rstrip().endswith("100")


def test_select_radar_text_form_preference_and_auto_fallback():
    values = [70.0, 45.0, 90.0, 30.0]
    # 显式偏好直接生效
    assert select_radar_text_form(values, preference="bars") == "bars"
    assert select_radar_text_form(values, preference="radar") == "radar"
    # 未知取值按 auto；正常数据 → 线状雷达
    assert select_radar_text_form(values, preference="whatever") == "radar"
    # 退化数据（全 0，多边形退化为中心点）→ 自动降级柱状图
    assert select_radar_text_form([0.0] * 4, preference="auto") == "bars"
    assert radar_polygon_edge_cells([0.0] * 4) <= 1


def test_render_radar_text_auto_dispatches_by_form():
    series = _series(values=[0.0] * 4)
    auto = render_radar_text_auto(series=series, title="t", form="auto")
    bars = render_radar_bars(series=series, title="t")
    radar = render_radar_text(series=series, title="t")
    # 全 0 退化数据自动选择柱状图（无 ░ 空位填充是 bars 形态特征）
    assert auto == bars
    assert auto != radar
    # 显式 radar 偏好覆盖自动降级
    forced = render_radar_text_auto(series=series, title="t", form="radar")
    assert forced == radar
