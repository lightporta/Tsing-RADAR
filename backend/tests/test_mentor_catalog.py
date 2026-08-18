"""mentor_catalog 进程内缓存测试。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import data_loader, mentor_catalog

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_catalog_cache():
    mentor_catalog._reset_cache_for_tests()
    yield
    mentor_catalog._reset_cache_for_tests()


def _counting_score_enrichment(monkeypatch) -> dict[str, int]:
    """把 mentor_catalog 内的 score_enriched_resources 包一层计数器。"""
    calls = {"count": 0}
    original = mentor_catalog.score_enriched_resources

    def counting(records):
        calls["count"] += 1
        return original(records)

    monkeypatch.setattr(mentor_catalog, "score_enriched_resources", counting)
    return calls


def test_second_call_hits_cache(monkeypatch):
    """同参数二次调用命中缓存：底层管线只执行一次且结果一致。"""
    calls = _counting_score_enrichment(monkeypatch)

    first_records, first_status = mentor_catalog.enriched_mentor_resources()
    second_records, second_status = mentor_catalog.enriched_mentor_resources()

    assert calls["count"] == 1
    assert second_records == first_records
    assert second_status == first_status


def test_mentor_file_change_invalidates_cache(tmp_path, monkeypatch):
    """导师数据文件被替换（mtime/size 变化）后必须重新计算。"""
    calls = _counting_score_enrichment(monkeypatch)
    mentor_catalog.enriched_mentor_resources()
    assert calls["count"] == 1

    replacement = tmp_path / "mentors.evidence.json"
    replacement.write_bytes(Path(data_loader._DATA_PATH).read_bytes() + b"\n")
    monkeypatch.setattr(data_loader, "_DATA_PATH", str(replacement))

    mentor_catalog.enriched_mentor_resources()
    assert calls["count"] == 2

    # 新键再次命中缓存，不重复计算。
    mentor_catalog.enriched_mentor_resources()
    assert calls["count"] == 2


def test_mentors_route_serves_consistent_meta():
    """路由级：GET /api/mentors 两次 200 且 meta 一致。"""
    first = client.get("/api/mentors")
    second = client.get("/api/mentors")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert first.json()["meta"] == second.json()["meta"]


def test_scatter_route_serves_consistent_meta():
    """路由级：GET /api/scatter 两次 200 且响应一致。"""
    first = client.get("/api/scatter")
    second = client.get("/api/scatter")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
