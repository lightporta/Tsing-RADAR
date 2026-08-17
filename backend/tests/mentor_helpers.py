"""导师服务测试共享工具：合成治理数据集、登录与认领流程。

- mentor_dataset fixture：把 data_loader 指向临时合成数据集（含唯一/重名候选），
  测试结束后自动还原并清缓存；
- mentor_web_client / mentor_login / auto_claim：复用 Web 会话 + 邮箱验证码流程。
"""

from __future__ import annotations

import json
import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.services.data_loader as data_loader


def _record(advisor_id: str, name: str, dept: str, title: str) -> dict:
    now = "2026-08-17T00:00:00+08:00"
    fields = {"name": name, "dept": dept, "title": title}
    provenance = {
        field: [
            {
                "evidence_id": str(uuid.uuid4()),
                "source_type": "public_fact",
                "source_ref": (
                    f"https://www.tsinghua.edu.cn/advisor/{advisor_id}"
                ),
                "captured_at": now,
                "verification_status": "verified",
                "confidence": 0.9,
            }
        ]
        for field in fields
    }
    governance = {
        "review_status": "verified",
        "publication_status": "published",
        "created_at": now,
        "updated_at": now,
        "verified_at": now,
        "authorization": {"basis": "public_source", "scope": []},
        "takedown": {"status": "active"},
    }
    return {
        "schema_version": "2.0",
        "advisor_id": advisor_id,
        "fields": fields,
        "provenance": provenance,
        "governance": governance,
        "quarantined_fields": {},
    }


@pytest.fixture()
def mentor_dataset(tmp_path, monkeypatch):
    """合成数据集：A001 张伟唯一；B001/B002 李娜重名跨院系（多候选）。"""
    dataset = {
        "schema_version": "2.0",
        "generated_at": "2026-08-17T00:00:00+08:00",
        "source": {
            "source_type": "official_catalog_and_profiles",
            "content_sha256": "0" * 64,
            "original_record_count": 3,
            "raw_retained": False,
        },
        "records": [
            _record("A001", "张伟", "计算机科学与技术系", "教授"),
            _record("B001", "李娜", "自动化系", "副教授"),
            _record("B002", "李娜", "电子工程系", "研究员"),
        ],
    }
    path = tmp_path / "mentors.evidence.json"
    path.write_text(
        json.dumps(dataset, ensure_ascii=False), encoding="utf-8"
    )
    previous = data_loader._DATA_PATH
    data_loader._DATA_PATH = str(path)
    data_loader.reload_mentors()
    try:
        yield dataset
    finally:
        data_loader._DATA_PATH = previous
        data_loader.reload_mentors()


def mentor_web_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    response = client.get("/api/session")
    assert response.status_code == 200
    return client, {"X-CSRF-Token": client.cookies["tsing_radar_csrf"]}


def _code_from_logs(caplog, email: str) -> str:
    """从 console 邮件日志提取验证码。"""
    for record in caplog.records:
        if getattr(record, "name", "") != "app.services.email_sender":
            continue
        message = record.getMessage()
        if f"email={email}" in message:
            match = re.search(r"code=(\d{6})", message)
            if match:
                return match.group(1)
    raise AssertionError(f"未在日志中找到 {email} 的验证码")


def mentor_login(
    client: TestClient,
    headers: dict[str, str],
    caplog,
    *,
    email: str = "mentor01@tsinghua.edu.cn",
) -> None:
    """发送验证码并用日志中的码完成登录（绑定当前 Web 会话）。"""
    with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
        response = client.post(
            "/api/mentor/auth/email-code",
            headers=headers,
            json={"email": email},
        )
    assert response.status_code == 200, response.text
    code = _code_from_logs(caplog, email)
    response = client.post(
        "/api/mentor/auth/login",
        headers=headers,
        json={"email": email, "code": code},
    )
    assert response.status_code == 200, response.text
    assert response.json()["logged_in"] is True


def auto_claim(
    client: TestClient,
    headers: dict[str, str],
    *,
    candidate_id: str = "A001",
    name: str = "张伟",
    department: str = "计算机科学与技术系",
) -> None:
    """以唯一候选路径完成档案认领（auto_unique 自动绑定）。"""
    response = client.post(
        "/api/mentor/claim",
        headers=headers,
        json={
            "candidate_id": candidate_id,
            "name": name,
            "department": department,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "claimed"
