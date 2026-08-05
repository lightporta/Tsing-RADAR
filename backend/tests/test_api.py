"""API 集成测试（使用 FastAPI TestClient）。"""

import os
import sys

# 确保使用测试专用 SQLite，避免污染开发库
os.environ["DATABASE_URL"] = "sqlite:///./test_tsing_radar.db"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


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
    """获取导师列表应返回非空数组。"""
    resp = client.get("/api/mentors")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) > 0
    assert "name" in data[0]
    assert "radar_traits" in data[0]


def test_sort_mentors():
    """按指标排序导师。"""
    resp = client.get("/api/mentors/sort", params={"metric": "popularity"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 验证降序
    popularities = [m["popularity"] for m in data]
    assert popularities == sorted(popularities, reverse=True)


def test_sort_mentors_invalid_metric():
    """无效指标应返回 400。"""
    resp = client.get("/api/mentors/sort", params={"metric": "invalid"})
    assert resp.status_code == 400


def test_scatter():
    """散点图数据。"""
    resp = client.get("/api/scatter")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) > 0
    assert "x" in data[0] and "y" in data[0] and "color" in data[0]


def test_match():
    """综合匹配接口。"""
    resp = client.post("/api/match", json={"interest": "自然语言处理 对话系统"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) <= 5
    assert "score" in data[0] and "synergy" in data[0]


def test_recruitments():
    """招募列表。"""
    resp = client.get("/api/recruitments")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)


def test_publish_recruitment():
    """发布招募。"""
    resp = client.post(
        "/api/recruitments",
        json={
            "publisher_id": "管晓宏",
            "type": "招生",
            "title": "测试招募",
            "req": "要求测试",
            "major": "自动化",
            "deadline": "2026-12-31",
            "is_urgent": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"


def test_feedback():
    """提交反馈。"""
    resp = client.post(
        "/api/feedback",
        json={"student_id": "2023000000", "advisor_id": "管晓宏", "rating": 1, "comment": "很棒"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "recorded"


def test_feedback_invalid_rating():
    """无效 rating 应返回 400。"""
    resp = client.post(
        "/api/feedback",
        json={"student_id": "2023000000", "advisor_id": "管晓宏", "rating": 0},
    )
    assert resp.status_code == 400


def test_train_trigger():
    """触发训练（管理员）。

    admin_token 通过 X-Admin-Token Header 传递（审计补丁 #11），
    不再从请求体读取。
    """
    resp = client.post("/api/train/trigger", headers={"X-Admin-Token": "admin"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "training_started"
    assert "weights" in data


def test_train_trigger_forbidden():
    """错误 X-Admin-Token 应返回 403。"""
    resp = client.post("/api/train/trigger", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


def test_tsinghua_verify():
    """校内身份校验占位。"""
    resp = client.get("/api/tsinghua/auth/verify", params={"token": "test"})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
