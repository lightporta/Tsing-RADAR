"""v2.5 四象限文本化测试：象限分类、门控诚实空态、分组输出。"""

from __future__ import annotations

import pytest

from app.services.scatter_dialogue import (
    QUADRANT_HOT_THRESHOLD,
    format_scatter_summary,
    handle_scatter_query,
    quadrant_key,
    quadrant_label,
)


def test_quadrant_threshold_is_strictly_greater():
    assert QUADRANT_HOT_THRESHOLD == 60.0
    assert quadrant_key(60.0, 90.0) == (False, True)  # 60 不算热（>60 才算）
    assert quadrant_key(60.1, 60.1) == (True, True)
    assert quadrant_key(10.0, 10.0) == (False, False)


def test_quadrant_labels_are_honest_descriptions():
    assert "双高活跃" in quadrant_label(True, True)
    assert "项目驱动型" in quadrant_label(True, False)
    assert "主题探索型" in quadrant_label(False, True)
    assert "聚焦深耕型" in quadrant_label(False, False)


def test_format_scatter_summary_groups_and_truncates():
    points = []
    for index in range(5):
        points.append(
            {
                "name": f"导师{index}",
                "dept": "自动化系",
                "advisor_id": f"A{index:03d}",
                "x": 80.0 + index,
                "y": 70.0,
            }
        )
    points.append(
        {
            "name": "冷门导师",
            "dept": "机械工程系",
            "advisor_id": "A099",
            "x": 20.0,
            "y": 30.0,
        }
    )
    text = format_scatter_summary(points)
    assert "共 6 位有已审核客观证据" in text
    assert "双高活跃" in text
    assert "（5 位" in text  # 第一象限 5 位：每象限计数格式
    # 每象限最多展示 3 位（按 项目广度+主题广度 降序取前 3）
    assert "导师4" in text
    assert "导师0" not in text  # 总分最低，超出展示上限
    assert "聚焦深耕型" in text
    assert "冷门导师" in text
    # 明确标注体制属性/热门度不公开
    assert "体制属性（国/私）与热门度属历史推断字段" in text


@pytest.mark.asyncio
async def test_handle_scatter_query_gate_closed_is_honest(monkeypatch):
    # 测试环境未配置评分发布文件 → 门关闭 → 诚实空态，绝不伪造分类
    from app.services import scatter_dialogue as scatter

    monkeypatch.setattr(
        scatter,
        "public_score_bundles",
        lambda: (
            {},
            {
                "gate_open": False,
                "reason": "no_published_score_release",
            },
        ),
    )
    reply, attachment = await handle_scatter_query(latest_user="四象限")
    assert "暂不能诚实地进行四象限分类" in reply
    assert "no_published_score_release" in reply
    assert attachment is None


@pytest.mark.asyncio
async def test_handle_scatter_query_gate_open_but_no_points_is_honest(monkeypatch):
    from app.services import scatter_dialogue as scatter

    monkeypatch.setattr(
        scatter,
        "public_score_bundles",
        lambda: ({}, {"gate_open": True}),
    )
    monkeypatch.setattr(
        scatter,
        "enriched_mentor_resources",
        lambda _records: ([], {}),
    )
    reply, _attachment = await handle_scatter_query(latest_user="导师分布")
    assert "当前没有同时具备项目广度与主题广度已审核证据的导师" in reply
