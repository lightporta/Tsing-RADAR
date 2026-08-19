"""兴趣探索（活动兴趣题 → 候选研究方向）测试。

确定性映射约束（修改说明 §6）：
- 候选方向由静态映射计算，同一活动集合必须得到完全相同的结果；
- apply 把选定方向写回画像 research_interests，走既有匹配管线。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
STUDENT_HEADERS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _web_session_headers():
    response = client.get("/api/session")
    assert response.status_code == 200
    STUDENT_HEADERS.clear()
    STUDENT_HEADERS["X-CSRF-Token"] = client.cookies["tsing_radar_csrf"]


def _start() -> dict:
    response = client.post("/api/interviews", headers=STUDENT_HEADERS, json={})
    assert response.status_code == 200
    return response.json()


def _suggestions(activities: list[str]):
    return client.post(
        "/api/interest-exploration/suggestions",
        headers=STUDENT_HEADERS,
        json={"activities": activities},
    )


# =====================================================================
# 活动兴趣题
# =====================================================================


def test_activity_question_is_static_and_complete():
    """题目定义：静态、含足够选项、明确多选边界。"""
    response = client.get("/api/interest-exploration/question", headers=STUDENT_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "activity-interests-v1"
    assert len(body["options"]) >= 8
    assert body["min_selections"] == 1
    assert body["max_selections"] == len(body["options"])
    values = [option["value"] for option in body["options"]]
    assert len(values) == len(set(values))
    assert all(option["label"] and option["description"] for option in body["options"])


# =====================================================================
# 候选方向确定性映射
# =====================================================================


def test_suggestions_are_deterministic_and_ordered():
    """同一活动集合两次请求结果逐字段一致（无模型、无随机性）。"""
    first = _suggestions(["data_patterns", "code_systems"])
    second = _suggestions(["code_systems", "data_patterns"])
    assert first.status_code == 200
    assert first.json() == second.json()

    body = first.json()
    assert body["basis"] == "deterministic_activity_mapping"
    assert body["candidates"], "命中活动必须产生候选方向"
    # 命中两个活动的方向排在最前
    top = body["candidates"][0]
    assert top["match_score"] == 2
    assert top["key"] == "ai_data"
    assert top["matched_activities"]
    assert len(top["description"]) > 10
    # 分数不增
    scores = [candidate["match_score"] for candidate in body["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert len(body["candidates"]) <= 5


def test_suggestions_cap_at_five_candidates():
    """全选活动时最多返回 5 个候选（上限约束）。"""
    response = _suggestions(
        [
            "data_patterns",
            "build_devices",
            "code_systems",
            "prove_theory",
            "talk_people",
            "policy_social",
            "life_health",
            "design_create",
        ]
    )
    assert response.status_code == 200
    assert len(response.json()["candidates"]) == 5


def test_suggestions_reject_unknown_activity_key():
    """映射表之外的活动键 → 422，不静默忽略。"""
    response = _suggestions(["not_a_real_activity"])
    assert response.status_code == 422


# =====================================================================
# 写回画像闭环
# =====================================================================


def test_apply_writes_directions_into_portrait():
    """选定候选方向写回 research_interests，画像版本递增。"""
    started = _start()
    session_id = started["session_id"]
    version = started["profile_version"]

    response = client.post(
        f"/api/interest-exploration/{session_id}/apply",
        headers=STUDENT_HEADERS,
        json={
            "direction_keys": ["ai_data", "hci_design"],
            "activities": ["data_patterns", "code_systems"],
            "expected_version": version,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["research_interests"] == [
        "人工智能与数据科学",
        "人机交互与设计科学",
    ]
    assert body["profile"]["activity_interests"] == [
        "data_patterns",
        "code_systems",
    ]
    assert body["profile_version"] > version
    # 兴趣维度完成后不再缺 research_interests
    assert "research_interests" in body["completed_dimensions"]


def test_apply_rejects_unknown_direction_key():
    """候选池之外的方向键 → 422。"""
    started = _start()
    response = client.post(
        f"/api/interest-exploration/{started['session_id']}/apply",
        headers=STUDENT_HEADERS,
        json={
            "direction_keys": ["no_such_direction"],
            "expected_version": started["profile_version"],
        },
    )
    assert response.status_code == 422


def test_apply_version_conflict_returns_409():
    """画像版本过期 → 409（乐观锁保持一致）。"""
    started = _start()
    response = client.post(
        f"/api/interest-exploration/{started['session_id']}/apply",
        headers=STUDENT_HEADERS,
        json={
            "direction_keys": ["ai_data"],
            "expected_version": started["profile_version"] + 99,
        },
    )
    assert response.status_code == 409
