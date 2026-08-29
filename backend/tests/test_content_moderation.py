"""内容分级检测：链接/联系方式/敏感词 → 先审后发；apply_method 联系方式 422。"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.content_moderation import (
    POST_PUBLISH,
    PRE_REVIEW,
    assert_apply_method_allowed,
    classify_content,
)


@pytest.fixture(autouse=True)
def reset_sensitive_words():
    """每个用例后还原词表配置，防止串扰。"""
    yield
    settings.CONTENT_SENSITIVE_WORDS = ""
    settings.CONTENT_SENSITIVE_WORDS_FILE = None


# =====================================================================
# classify_content 分级
# =====================================================================


@pytest.mark.parametrize(
    "text",
    [
        "详见 https://example.com/jd",
        "参考 http://lab.tsinghua.edu.cn",
        "主页 www.example.com 有介绍",
    ],
)
def test_url_forms_trigger_pre_review(text: str):
    assert classify_content(text) == PRE_REVIEW


@pytest.mark.parametrize(
    "text",
    [
        "联系 13812345678 详聊",
        "手机 19900001111",
    ],
)
def test_phone_forms_trigger_pre_review(text: str):
    assert classify_content(text) == PRE_REVIEW


@pytest.mark.parametrize(
    "text",
    [
        "加微信：abc12345 私聊",
        "vx: hello_world",
        "WeChat：test-user-01",
    ],
)
def test_wechat_forms_trigger_pre_review(text: str):
    assert classify_content(text) == PRE_REVIEW


def test_sensitive_word_from_settings_triggers_pre_review(monkeypatch):
    """敏感词表外置：从 settings 注入后命中即先审后发。"""
    monkeypatch.setattr(settings, "CONTENT_SENSITIVE_WORDS", "赌场,代写论文")
    assert classify_content("这里有一句代写论文的广告") == PRE_REVIEW
    assert classify_content("正常讨论课题方向") == POST_PUBLISH


def test_sensitive_word_from_file_triggers_pre_review(tmp_path, monkeypatch):
    """外部文件词表：每行一词，# 注释与空行忽略。"""
    word_file = tmp_path / "words.txt"
    word_file.write_text("# 注释行\n\n禁区词甲\n", encoding="utf-8")
    monkeypatch.setattr(
        settings, "CONTENT_SENSITIVE_WORDS_FILE", str(word_file)
    )
    assert classify_content("这句话包含禁区词甲") == PRE_REVIEW
    assert classify_content("正常内容") == POST_PUBLISH


def test_normal_text_is_post_publish():
    assert classify_content("请问名额还有吗？方向偏系统还是算法？") == POST_PUBLISH


# =====================================================================
# assert_apply_method_allowed
# =====================================================================


def test_apply_method_with_phone_rejected():
    with pytest.raises(HTTPException) as excinfo:
        assert_apply_method_allowed("直接电话联系 13812345678")
    assert excinfo.value.status_code == 422


def test_apply_method_with_wechat_rejected():
    with pytest.raises(HTTPException) as excinfo:
        assert_apply_method_allowed("加微信 abc12345 发简历")
    assert excinfo.value.status_code == 422


def test_apply_method_allows_on_site_text():
    assert_apply_method_allowed("请在站内投递简历，附研究陈述")
    assert_apply_method_allowed(None)


def test_publish_recruitment_with_contact_apply_method_returns_422():
    """API 级：apply_method 含联系方式 → 422，不进入审核队列。"""
    client = TestClient(app)
    assert client.get("/api/session").status_code == 200
    headers = {
        "X-CSRF-Token": client.cookies["tsing_radar_csrf"],
        "Idempotency-Key": f"recruit:{uuid.uuid4()}",
    }
    response = client.post(
        "/api/recruitments",
        headers=headers,
        json={
            "type": "科研助理",
            "title": "课题组招募科研助理",
            "req": "熟悉 Python 与数据处理",
            "major": "计算机科学与技术",
            "deadline": (date.today() + timedelta(days=30)).isoformat(),
            "is_urgent": False,
            "apply_method": "电话 13812345678 联系",
        },
    )
    assert response.status_code == 422
    assert "联系方式" in response.json()["detail"] or "手机号" in response.json()["detail"]
