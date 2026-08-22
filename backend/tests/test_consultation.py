"""v2.5 咨询模块测试：套磁邮件模板/降级、FAQ 诚实问答。"""

from __future__ import annotations

import pytest

from app.schemas.interview import StudentPortrait
from app.services.consultation import (
    _NOT_COLLECTED_TEMPLATE,
    _parse_email_request,
    deterministic_email_draft,
    handle_consult_email,
    handle_consult_faq,
)


def test_parse_email_request_extracts_advisor():
    assert _parse_email_request("给王老师写一封套磁邮件") == {"advisor_name": "王"}
    assert _parse_email_request("联系李教授") == {"advisor_name": "李"}
    assert _parse_email_request("帮我写邮件") == {}


def test_deterministic_email_draft_uses_placeholders_not_fabrication():
    subject, body = deterministic_email_draft(
        request="给张老师写邮件", portrait=None
    )
    assert "张老师" in subject
    assert "研究兴趣" in body
    # 未提供兴趣时用占位符，绝不编造具体方向
    assert "（未提供" in body or "【我的基本情况】" in body
    # 诚实提示联系方式以官网为准
    assert "官网" in body


def test_deterministic_email_draft_uses_profile_interests():
    profile = StudentPortrait(research_interests=["大模型", "自然语言处理"])
    _subject, body = deterministic_email_draft(
        request="给李老师写邮件", portrait=profile
    )
    assert "大模型" in body


@pytest.mark.asyncio
async def test_handle_consult_email_degrades_without_llm():
    # 无 LLM 凭据 → 确定性模板兜底，绝不阻断
    reply, attachment = await handle_consult_email(
        latest_user="给王老师写一封套磁邮件",
        portrait=StudentPortrait(research_interests=["机器学习"]),
    )
    assert "套磁信初稿" in reply
    assert "确定性模板初稿" in reply
    assert "王老师" in reply
    assert attachment is None


@pytest.mark.asyncio
async def test_handle_consult_faq_platform_answers():
    reply, _ = await handle_consult_faq(latest_user="雷达图是什么")
    assert "客观四维证据" in reply
    # 正常人口语说法同样命中雷达图机制答案
    for question in ("雷达图是啥", "雷达图是干嘛的", "雷达图有什么用"):
        reply, _ = await handle_consult_faq(latest_user=question)
        assert "客观四维证据" in reply, question
    reply, _ = await handle_consult_faq(latest_user="怎么投递")
    assert "tsingradar.com.cn/recruitment" in reply
    # 简历机制兜底：口语"简历咋弄"给出功能说明而非访谈路由
    reply, _ = await handle_consult_faq(latest_user="简历咋弄")
    assert "从零生成" in reply
    assert "定向优化" in reply


@pytest.mark.asyncio
async def test_handle_consult_faq_individual_questions_are_honest():
    for question in ("组会频率怎么样", "老师延毕情况", "招生名额有多少", "学生评价怎么样"):
        reply, _ = await handle_consult_faq(latest_user=question)
        assert "暂未收录" in reply
        assert "不能编造" in reply or "官方邮箱" in reply


@pytest.mark.asyncio
async def test_handle_consult_faq_unknown_question_falls_back():
    reply, _ = await handle_consult_faq(latest_user="有什么能帮我的")
    assert "平台机制类问题" in reply


def test_not_collected_template_is_honest():
    text = _NOT_COLLECTED_TEMPLATE.format(topic="组会")
    assert "「组会」这类信息属于导师个体情况" in text
    assert "暂未收录" in text
