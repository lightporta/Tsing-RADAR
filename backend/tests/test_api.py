"""API 集成测试（使用 FastAPI TestClient）。"""

import os
import sys

# 确保使用测试专用 SQLite，避免污染开发库
os.environ["DATABASE_URL"] = "sqlite:///./test_tsing_radar.db"

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


def test_get_mentors():
    """无证据旧数据默认暂缓，不得进入导师列表。"""
    resp = client.get("/api/mentors")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"] == []
    assert payload["meta"] == {
        "total_records": 0,
        "published_records": 0,
        "withheld_records": 0,
        "policy": "verified_only",
    }


def test_sort_mentors():
    """按指标排序导师。"""
    resp = client.get("/api/mentors/sort", params={"metric": "popularity"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == []
    assert resp.json()["meta"]["withheld_records"] == 0


def test_sort_mentors_invalid_metric():
    """无效指标应返回 400。"""
    resp = client.get("/api/mentors/sort", params={"metric": "invalid"})
    assert resp.status_code == 400


def test_scatter():
    """无证据热门度与行业标签不得进入散点图。"""
    resp = client.get("/api/scatter")
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert resp.json()["meta"]["policy"] == "verified_only"


def test_match():
    """缺少已确认访谈会话时不得进入匹配。"""
    resp = client.post(
        "/api/match",
        headers=WEB_HEADERS,
        json={"interest": "自然语言处理 对话系统"},
    )
    assert resp.status_code == 409


def test_recruitments():
    """未审核的旧招募和新提交不得公开。"""
    resp = client.get("/api/recruitments")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == []
    assert resp.json()["meta"]["policy"] == "verified_only"


def test_publish_recruitment():
    """提交招募后进入审核队列，不直接发布。"""
    resp = client.post(
        "/api/recruitments",
        headers=WEB_HEADERS,
        json={
            "type": "招生",
            "title": "测试招募",
            "req": "要求测试",
            "major": "自动化",
            "deadline": "2026-12-31",
            "is_urgent": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "pending_review"
    assert payload["publication_status"] == "restricted"

    listed = client.get("/api/recruitments").json()
    assert all(
        item["recruit_id"] != payload["recruit_id"]
        for item in listed["data"]
    )
    assert listed["meta"]["withheld_submissions"] >= 1


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


def test_train_trigger():
    """Proxy labels must not activate learned ranking."""
    resp = client.post(
        "/api/train/trigger",
        headers={"X-Admin-Token": "test-admin-token-not-for-production"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked_by_data_readiness_gate"
    assert data["training_started"] is False
    assert data["weights"] is None
    assert data["readiness"]["learned_ranking_enabled"] is False


def test_train_trigger_forbidden():
    """错误管理员 header 应返回 403。"""
    resp = client.post(
        "/api/train/trigger",
        headers={"X-Admin-Token": "wrong-admin-token"},
    )
    assert resp.status_code == 403


def test_train_body_token_is_not_an_authorization_mechanism():
    """公开旧默认值放在 JSON body 中不得获得管理员权限。"""
    resp = client.post("/api/train/trigger", json={"admin_token": "admin"})
    assert resp.status_code in {403, 422}


def test_tsinghua_verify_fails_closed():
    """未接入校内身份提供者时不得模拟成功。"""
    resp = client.get("/api/tsinghua/auth/verify", params={"token": "test"})
    assert resp.status_code == 501
