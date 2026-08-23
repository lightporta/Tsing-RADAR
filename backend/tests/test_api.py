"""API 集成测试（使用 FastAPI TestClient）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
import pytest  # noqa: E402

client = TestClient(app)
WEB_HEADERS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _web_session_headers():
    response = client.get("/api/session")
    assert response.status_code == 200
    WEB_HEADERS.clear()
    WEB_HEADERS["X-CSRF-Token"] = client.cookies["tsing_radar_csrf"]


def test_root():
    """根路径返回应用信息。"""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert "endpoints" in data


def test_health():
    """健康检查。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_sort_mentors():
    """按指标排序导师。"""
    resp = client.get("/api/mentors/sort", params={"metric": "popularity"})
    assert resp.status_code == 410


def test_sort_mentors_invalid_metric():
    """无效指标应返回 400。"""
    resp = client.get("/api/mentors/sort", params={"metric": "invalid"})
    assert resp.status_code == 410


def test_capabilities_departments_and_score_gate_are_explicit():
    capabilities = client.get(
        "/api/interviews/hard-constraint-capabilities"
    ).json()
    assert capabilities["basis"] == "published_verified_candidate_fields"
    assert capabilities["candidate_count"] == 0
    assert all(not item["available"] for item in capabilities["fields"])

    students = client.get("/api/departments/students").json()
    mentors = client.get("/api/departments/mentors").json()
    assert students["meta"]["scope"] == "student"
    assert students["meta"]["source"]["url"].startswith("https://www.tsinghua.edu.cn/")
    assert mentors["meta"]["scope"] == "mentor"
    assert students["meta"]["basis"] == "official_department_directory"
    student_names = {item["name"] for item in students["data"]}
    assert {
        "苏世民书院",
        "求真书院",
        "至善书院",
        "水木书院",
        "人工智能学院",
        "安全科学学院",
        "核能与新能源技术研究院",
        "深圳国际研究生院",
        "全球创新学院",
        "国家卓越工程师学院",
    } <= student_names
    mentor_names = {item["name"] for item in mentors["data"]}
    assert {"人工智能学院", "安全科学学院", "国家卓越工程师学院"} <= mentor_names
    assert students["meta"]["basis"] != mentors["meta"]["basis"]
    status = client.get("/api/mentor-evidence/status").json()["meta"]
    assert status["gate_open"] is False
    assert status["coverage"] == 0


def test_match():
    """缺少已确认访谈会话时不得进入匹配。"""
    resp = client.post(
        "/api/match",
        headers=WEB_HEADERS,
        json={"interest": "自然语言处理 对话系统"},
    )
    assert resp.status_code == 409


def test_feedback():
    """提交反馈。"""
    resp = client.post(
        "/api/feedback",
        headers=WEB_HEADERS,
        json={"advisor_id": "管晓宏", "rating": 1, "comment": "很棒"},
    )
    assert resp.status_code == 404


def test_feedback_invalid_rating():
    """无效 rating 应返回 400。"""
    resp = client.post(
        "/api/feedback",
        headers=WEB_HEADERS,
        json={"advisor_id": "管晓宏", "rating": 0},
    )
    assert resp.status_code == 400


def test_train_body_token_is_not_an_authorization_mechanism():
    """公开旧默认值放在 JSON body 中不得获得管理员权限。"""
    resp = client.post("/api/train/trigger", json={"admin_token": "admin"})
    assert resp.status_code in {403, 422}


def test_tsinghua_verify_fails_closed():
    """未接入校内身份提供者时不得模拟成功。"""
    resp = client.get("/api/tsinghua/auth/verify", params={"token": "test"})
    assert resp.status_code == 501


def test_llm_chat_rejects_tool_role():
    """B3：role 只接受 user/assistant/system。"""
    resp = client.post(
        "/api/v1/llm/chat",
        headers=WEB_HEADERS,
        json={"messages": [{"role": "tool", "content": "工具结果"}]},
    )
    assert resp.status_code == 422


def test_llm_chat_rejects_oversized_content():
    """B3：单条消息内容超过 20000 字拒绝。"""
    resp = client.post(
        "/api/v1/llm/chat",
        headers=WEB_HEADERS,
        json={"messages": [{"role": "user", "content": "长" * 20_001}]},
    )
    assert resp.status_code == 422


def test_llm_chat_rejects_too_many_messages():
    """B3：消息条数超过 50 拒绝。"""
    resp = client.post(
        "/api/v1/llm/chat",
        headers=WEB_HEADERS,
        json={
            "messages": [
                {"role": "user", "content": f"第 {index} 条"}
                for index in range(51)
            ]
        },
    )
    assert resp.status_code == 422


def test_llm_embeddings_rejects_oversized_text():
    """B3：embedding 文本超过 20000 字拒绝。"""
    resp = client.post(
        "/api/v1/llm/embeddings",
        json={"text": "长" * 20_001},
    )
    assert resp.status_code == 422


def test_llm_request_limits_accept_boundary_values():
    """B3：边界内正常值放行（50 条消息、20000 字内容/文本）。"""
    chat = client.post(
        "/api/v1/llm/chat",
        params={"stream": "false"},
        headers=WEB_HEADERS,
        json={
            "messages": [
                {"role": "system", "content": "系统提示"},
                *[
                    {"role": "user", "content": "自然语言处理"}
                    for _ in range(49)
                ],
            ]
        },
    )
    assert chat.status_code == 200

    embeddings = client.post(
        "/api/v1/llm/embeddings",
        json={"text": "文" * 20_000},
    )
    assert embeddings.status_code == 200
    assert embeddings.json()["data"]
