"""雷达图服务合同测试：确定性渲染、SVG 结构、门控与 reportlab Drawing。"""

from __future__ import annotations

import pytest

from app.services.constants import TRAIT_KEYS
from app.services.radar_chart import (
    ADVISOR_TRAIT_COLOR,
    GRID_STEPS,
    RADAR_DIMENSION_LABELS,
    RadarSeries,
    build_radar_series_for_advisor,
    radar_series_from_bundle,
    render_radar_drawing,
    render_radar_svg,
)

SAMPLE_VALUES = [80.0, 60.0, 90.0, 70.0, 50.0, 85.0]


def _series(
    name: str = "导师特质（已审核评分）",
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
            f"trait_{key}": value for key, value in zip(TRAIT_KEYS, values)
        }
    }


def test_render_radar_svg_is_byte_deterministic():
    kwargs = {
        "series": [_series()],
        "title": "导师特质雷达图（已审核评分）",
        "sample_note": "样本量与时间窗见详情页",
    }
    first = render_radar_svg(**kwargs)
    second = render_radar_svg(**kwargs)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_render_radar_svg_structure():
    svg = render_radar_svg(
        series=[_series()],
        title="导师特质雷达图",
        sample_note="样本说明",
    )
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<svg" in svg
    assert svg.endswith("</svg>")

    # 六条轴线
    assert len(TRAIT_KEYS) == 6
    assert svg.count("<line") == 6
    # 5 层网格 polygon + 1 条数据系列 polygon
    assert svg.count("<polygon") == len(GRID_STEPS) + 1
    assert len(GRID_STEPS) == 5
    assert svg.count('fill="none"') == len(GRID_STEPS)
    # 六维中文标签
    for label in RADAR_DIMENSION_LABELS.values():
        assert label in svg
    assert {
        "学术敏锐度",
        "人脉资源",
        "指导意愿",
        "性格包容度",
        "经费实力",
        "产出效率",
    } == set(RADAR_DIMENSION_LABELS.values())
    # 图例 rect 与导师特质橙色
    assert svg.count("<rect") == 1
    assert "#FF9500" in svg
    assert ADVISOR_TRAIT_COLOR == "#FF9500"
    assert "导师特质雷达图" in svg
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
    assert series.name == "导师特质（已审核评分）"
    assert series.line_type == "solid"


@pytest.mark.parametrize(
    "values",
    [
        [80, 60, 90, 70, 50],  # 缺一个维度
        [80, 60, 90, 70, 50, 100.5],  # 越界 >100
        [80, 60, 90, 70, 50, -0.5],  # 越界 <0
        [80, 60, 90, 70, 50, True],  # bool 不是合法评分
        [80, 60, 90, 70, 50, False],
        [80, 60, 90, 70, 50, "85"],  # 字符串不合法
        [80, 60, 90, 70, 50, None],
    ],
)
def test_radar_series_from_bundle_rejects_incomplete_or_invalid(values):
    assert radar_series_from_bundle(_bundle(values)) is None


def test_radar_series_from_bundle_rejects_empty_values_mapping():
    assert radar_series_from_bundle({}) is None
    assert radar_series_from_bundle({"values": None}) is None
    assert radar_series_from_bundle({"values": {}}) is None


def test_radar_series_from_bundle_accepts_boundary_scores():
    series = radar_series_from_bundle(_bundle([0, 100, 0.0, 100.0, 50, 1]))
    assert series is not None
    assert series.values == [0.0, 100.0, 0.0, 100.0, 50.0, 1.0]


def test_build_radar_series_for_advisor_with_explicit_bundles():
    bundles = {"T00001": _bundle(SAMPLE_VALUES)}
    hit = build_radar_series_for_advisor("T00001", bundles)
    assert hit is not None
    assert hit.values == SAMPLE_VALUES

    assert build_radar_series_for_advisor("T99999", bundles) is None
    assert build_radar_series_for_advisor("T00001", {}) is None
    invalid = {"T00002": _bundle([80, 60, 90, 70, 50])}
    assert build_radar_series_for_advisor("T00002", invalid) is None


def test_render_radar_drawing_returns_reportlab_drawing():
    from reportlab.graphics.shapes import Drawing, Line, Polygon, String

    drawing = render_radar_drawing(
        series=[_series()],
        title="导师特质雷达图",
        sample_note="样本说明",
    )
    assert isinstance(drawing, Drawing)

    lines = [item for item in drawing.contents if isinstance(item, Line)]
    polygons = [item for item in drawing.contents if isinstance(item, Polygon)]
    strings = [item for item in drawing.contents if isinstance(item, String)]
    # 6 条轴线；5 层网格 + 1 条数据系列；标题 + 6 个轴标签 + 样本说明
    assert len(lines) == 6
    assert len(polygons) == len(GRID_STEPS) + 1
    assert len(strings) == 1 + len(TRAIT_KEYS) + 1
    labels = {item.text for item in strings}
    assert "导师特质雷达图" in labels
    assert "样本说明" in labels
    for label in RADAR_DIMENSION_LABELS.values():
        assert label in labels


def test_render_radar_drawing_without_sample_note():
    from reportlab.graphics.shapes import Drawing, String

    drawing = render_radar_drawing(series=[_series()], title="雷达图")
    assert isinstance(drawing, Drawing)
    strings = [item for item in drawing.contents if isinstance(item, String)]
    assert len(strings) == 1 + len(TRAIT_KEYS)
