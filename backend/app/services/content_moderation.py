"""UGC 内容分级检测：链接/联系方式/敏感词识别。

- 词表外置：敏感词从 settings.CONTENT_SENSITIVE_WORDS（逗号分隔）与
  CONTENT_SENSITIVE_WORDS_FILE（每行一词，# 开头为注释）加载，代码中不
  硬编码任何词表内容；
- classify_content 决定评论走「先审后发」（pre_review）还是
  「先发后审 + 抽检」（post_publish）；
- assert_apply_method_allowed 用于招募 apply_method 字段：禁止手机号 /
  微信号直发，引导站内投递（保护发布者不被骚扰、投递记录留在站内）。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings

PRE_REVIEW = "pre_review"
POST_PUBLISH = "post_publish"

_URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
_WECHAT_PATTERN = re.compile(
    r"(微信|wechat|vx)[:：]?\s*[a-zA-Z0-9_-]{5,}", re.IGNORECASE
)


def _file_words() -> list[str]:
    """外部词表文件：每行一词，空行与 # 注释忽略；文件缺失按空表处理。"""
    path_value = settings.CONTENT_SENSITIVE_WORDS_FILE
    if not path_value:
        return []
    path = Path(path_value)
    try:
        if not path.is_file() or path.is_symlink():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def _sensitive_words() -> list[str]:
    """合并 settings 内联词表与外部文件词表（每次调用解析，便于运行时调整）。"""
    inline = [
        word.strip()
        for word in settings.CONTENT_SENSITIVE_WORDS.split(",")
        if word.strip()
    ]
    return inline + _file_words()


def contains_contact_info(text: str) -> bool:
    """是否含手机号 / 微信号等站外联系方式。"""
    return bool(
        _PHONE_PATTERN.search(text) or _WECHAT_PATTERN.search(text)
    )


def contains_link(text: str) -> bool:
    """是否含 URL 链接。"""
    return bool(_URL_PATTERN.search(text))


def contains_sensitive_word(text: str) -> bool:
    """是否命中外置敏感词表（词表为空时永不命中）。"""
    lowered = text.lower()
    return any(word.lower() in lowered for word in _sensitive_words())


def classify_content(text: str) -> str:
    """返回 'pre_review' | 'post_publish'：含链接/联系方式/敏感词 → 先审后发。"""
    if contains_link(text) or contains_contact_info(text):
        return PRE_REVIEW
    if contains_sensitive_word(text):
        return PRE_REVIEW
    return POST_PUBLISH


def assert_apply_method_allowed(text: str | None) -> None:
    """发布招募时校验 apply_method：禁手机号/微信号直发，引导站内投递。"""
    if text is None:
        return
    if contains_contact_info(text):
        raise HTTPException(
            status_code=422,
            detail="投递方式不得包含手机号或微信号，请引导站内投递",
        )
