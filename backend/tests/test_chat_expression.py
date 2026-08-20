"""清小搭入口表达层（chat_expression）单元测试。"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.schemas.interview import (
    InterviewDimension,
    InterviewQuestion,
    InterviewQuestionOption,
    InterviewStateResponse,
    InterviewStatus,
    StudentPortrait,
)
from app.services import chat_expression as expr
from app.services.llm import LLMCompletionResult

SYNTHETIC_KEY = "synthetic-llm-credential-not-live"

# 合格输出必须同时覆盖：两个选项 label + 题面 ≥6 字片段
_VALID_REWRITE = "你更偏好算法理论研究，还是实际应用？结合你的兴趣说说看。"


def _sample_state() -> InterviewStateResponse:
    return InterviewStateResponse(
        session_id="s-expression-test",
        status=InterviewStatus.IN_PROGRESS,
        profile=StudentPortrait(),
        profile_version=1,
        current_question=InterviewQuestion(
            question_id="q-research-mode",
            dimension=InterviewDimension.RESEARCH_MODE,
            prompt="你更偏好算法理论研究，还是实际应用？",
            answer_type="single_choice",
            options=[
                InterviewQuestionOption(value="theory", label="算法理论研究"),
                InterviewQuestionOption(value="engineering", label="实际应用"),
            ],
            information_goal="区分研究方式偏好",
        ),
        completed_dimensions=[InterviewDimension.RESEARCH_INTERESTS],
        missing_dimensions=[InterviewDimension.RESEARCH_MODE],
        needs_confirmation=False,
        needs_clarification=False,
        clarification_questions=[],
        recommend_ready=False,
        assistant_message="你更偏好算法理论研究，还是实际应用？",
        messages=[],
    )


def _sample_fact_pack() -> expr.InterviewFactPack:
    return expr.InterviewFactPack(
        user_message="我对强化学习感兴趣",
        question_prompt="你更偏好算法理论研究，还是实际应用？",
        options=("算法理论研究", "实际应用"),
        completed_dimensions=("研究兴趣",),
        missing_dimensions=("研究方式",),
        hard_constraint_status="尚未确认硬性条件",
    )


def _configured(monkeypatch, *, with_key: bool = True) -> Settings:
    kwargs = {}
    if with_key:
        kwargs = {"LLM_PROVIDER": "glm", "GLM_API_KEY": SYNTHETIC_KEY}
    configured = Settings(_env_file=None, **kwargs)
    monkeypatch.setattr(expr, "settings", configured)
    return configured


@pytest.mark.asyncio
async def test_render_disabled_without_credentials(monkeypatch):
    _configured(monkeypatch, with_key=False)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "disabled"
    assert result.text is None
    assert result.provider is None


@pytest.mark.asyncio
async def test_render_available_rewrites_reply(monkeypatch):
    _configured(monkeypatch)

    async def fake_result(_messages, **_kwargs):
        return LLMCompletionResult(
            text=_VALID_REWRITE,
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "available"
    assert result.text == _VALID_REWRITE
    assert result.provider == "glm"


@pytest.mark.asyncio
async def test_render_unavailable_when_llm_fails(monkeypatch):
    _configured(monkeypatch)

    async def fake_result(_messages, **_kwargs):
        return None

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "unavailable"
    assert result.text is None
    assert result.provider == "glm"


@pytest.mark.asyncio
async def test_render_rejects_forbidden_confirmation_tokens(monkeypatch):
    _configured(monkeypatch)

    async def fake_result(_messages, **_kwargs):
        return LLMCompletionResult(
            text=f"好的，画像已确认。{_VALID_REWRITE}",
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "unavailable"
    assert result.text is None


@pytest.mark.asyncio
async def test_render_rejects_missing_question_core(monkeypatch):
    _configured(monkeypatch)

    async def fake_result(_messages, **_kwargs):
        return LLMCompletionResult(
            text="那我们继续聊聊吧，你可以说说自己的偏好。",
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "unavailable"
    assert result.text is None


@pytest.mark.asyncio
async def test_render_rejects_missing_option_label(monkeypatch):
    _configured(monkeypatch)

    async def fake_result(_messages, **_kwargs):
        return LLMCompletionResult(
            text="你更偏好算法理论研究吗？",
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "unavailable"
    assert result.text is None


@pytest.mark.asyncio
async def test_render_rejects_oversized_output(monkeypatch):
    _configured(monkeypatch)

    async def fake_result(_messages, **_kwargs):
        return LLMCompletionResult(
            text=_VALID_REWRITE + "好的，" * 200,
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "unavailable"
    assert result.text is None


@pytest.mark.asyncio
async def test_render_uses_short_enhancement_timeout(monkeypatch):
    configured = _configured(monkeypatch)
    captured: dict = {}

    async def fake_result(_messages, **_kwargs):
        captured["timeout"] = _kwargs.get("timeout_seconds")
        return LLMCompletionResult(
            text=_VALID_REWRITE,
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    result = await expr.render_interview_reply(_sample_fact_pack())
    assert result.status == "available"
    assert captured["timeout"] == configured.LLM_INTERVIEW_ENHANCEMENT_TIMEOUT_SECONDS


def test_build_fact_pack_extracts_state_facts():
    pack = expr.build_interview_fact_pack(_sample_state(), "我对强化学习感兴趣")
    assert pack.user_message == "我对强化学习感兴趣"
    assert pack.question_prompt == "你更偏好算法理论研究，还是实际应用？"
    assert pack.options == ("算法理论研究", "实际应用")
    assert pack.completed_dimensions == ("研究兴趣",)
    assert pack.missing_dimensions == ("研究方式",)
    assert pack.hard_constraint_status == "尚未确认硬性条件"


def test_build_fact_pack_handles_missing_question():
    state = _sample_state()
    state.current_question = None
    pack = expr.build_interview_fact_pack(state, "")
    assert pack.question_prompt == ""
    assert pack.options == ()
    assert pack.user_message == ""


def test_build_fact_pack_uses_assistant_message_for_dynamic_questions():
    """动态题（如硬约束确认题）只存在于 assistant_message；题库 current_question
    是静态原始题面，两者必须一致，否则重写会与真实流程错位。"""
    state = _sample_state()
    state.current_question.prompt = "最后划一下不可妥协的边界……"  # 题库静态题面
    state.assistant_message = (
        "我理解为地点必须在“北京”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
    )
    pack = expr.build_interview_fact_pack(state, "只能北京")
    assert pack.question_prompt == state.assistant_message
    assert "我理解为地点必须在" in pack.question_prompt


def test_build_fact_pack_constraint_status_variants():
    state = _sample_state()
    state.profile.unresolved_hard_constraints = ["必须在北京"]
    pack = expr.build_interview_fact_pack(state, "必须在北京")
    assert pack.hard_constraint_status == "有硬性条件待确认"


# —— v4.1.0 自然度闸门：机器腔/客服腔 → 拒绝并降级固定模板 ——


def _plain_pack(**overrides) -> expr.InterviewFactPack:
    fields = dict(
        user_message="答",
        question_prompt="喜欢什么？",
        options=(),
        completed_dimensions=(),
        missing_dimensions=("研究兴趣",),
        hard_constraint_status="尚未确认硬性条件",
    )
    fields.update(overrides)
    return expr.InterviewFactPack(**fields)


class TestNaturalnessGate:
    def test_ai_self_reference_rejected(self):
        pack = _plain_pack()
        text = "作为一个AI助手，我来问你：喜欢什么？"
        assert expr._validate_expression(text, pack) is False

    def test_customer_service_tone_rejected(self):
        pack = _plain_pack()
        for text in (
            "亲爱的用户，请告诉我你喜欢什么？",
            "感谢您的反馈！那么喜欢什么呢？",
            "收到请回复你的偏好哦。",
        ):
            assert expr._validate_expression(text, pack) is False, text

    def test_natural_tone_still_passes(self):
        pack = _plain_pack()
        text = "说到这个，你平时更喜欢琢磨哪块呢？"
        assert expr._validate_expression(text, pack) is True

    def test_token_from_fact_pack_content_not_misjudged(self):
        # 题面/选项本身含"人工智能助手"字样时不算机器腔（防误伤合法题面）
        pack = _plain_pack(
            options=("人工智能助手伦理", "其他"),
            question_prompt="你怎么看人工智能助手这个研究方向？",
        )
        text = "你怎么看人工智能助手这个研究方向？偏人工智能助手伦理还是其他？"
        assert expr._validate_expression(text, pack) is True
