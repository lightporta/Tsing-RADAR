"""清小搭入口表达层（chat_expression）单元测试。"""

from __future__ import annotations

import dataclasses

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

    def test_customer_service_phrases_rejected(self):
        # v4.2.0 追加客服套话词表：服务用语 → 拒绝降级
        pack = _plain_pack()
        for text in (
            "很高兴为您介绍这个问题：喜欢什么？",
            "还有什么可以帮你的吗？先说说喜欢什么？",
            "希望以上说明对你有帮助。喜欢什么？",
        ):
            assert expr._validate_expression(text, pack) is False, text


# —— v4.3.0 纯文本输出闸门：Markdown 标记 → 拒绝降级（验收①-⑥） ——


class TestMarkdownGate:
    def test_bold_markup_rejected(self):
        pack = _plain_pack()
        text = "**好的**，说说你喜欢什么？"
        assert expr._validate_expression(text, pack) is False

    def test_code_fence_rejected(self):
        pack = _plain_pack()
        text = "我们来聊聊：```\n喜欢什么\n```"
        assert expr._validate_expression(text, pack) is False

    def test_heading_rejected(self):
        pack = _plain_pack()
        text = "## 聊聊\n你喜欢什么？"
        assert expr._validate_expression(text, pack) is False

    def test_list_marker_rejected(self):
        pack = _plain_pack()
        text = "- 喜欢什么？"
        assert expr._validate_expression(text, pack) is False

    def test_normal_chinese_text_not_misjudged(self):
        pack = _plain_pack()
        # 破折号/连字符/编号正文不误伤（保守规则只命中行首 "- "）
        for text in (
            "这个——或者那个，你喜欢什么？",
            "a-b 方案你选哪个？你喜欢什么？",
            "第1个还是第2个，你喜欢什么？",
        ):
            assert expr._validate_expression(text, pack) is True, text

    def test_marker_from_fact_pack_content_allowed(self):
        # 题面本身含列表/加粗时，复述题面不视为违规（防误伤合法题面）
        pack = _plain_pack(
            question_prompt="- 说说你的兴趣\n- 或者研究方向"
        )
        text = "- 说说你的兴趣\n- 或者研究方向"
        assert expr._validate_expression(text, pack) is True


# —— v4.2.0 多轮自然度：事实包多轮上下文投影 ——


def _multiturn_state() -> InterviewStateResponse:
    state = _sample_state()
    state.messages = [
        {"role": "user", "content": "我对强化学习感兴趣"},
        {"role": "assistant", "content": "你更关注哪个层面的研究问题？"},
        {"role": "user", "content": "偏工程落地一点"},
        # 末位 assistant 即本轮话术底稿（question_prompt 已单独注入）
        {
            "role": "assistant",
            "content": "你更偏好算法理论研究，还是实际应用？",
        },
    ]
    return state


class TestMultiturnContext:
    def test_build_fact_pack_derives_recent_dialogue(self):
        pack = expr.build_interview_fact_pack(
            _multiturn_state(), "偏工程落地一点"
        )
        # 末位 assistant（本轮底稿）跳过；其余轮次保留为「用户/清小搭」底稿
        assert "用户：我对强化学习感兴趣" in pack.recent_dialogue
        assert "清小搭：你更关注哪个层面的研究问题？" in pack.recent_dialogue
        assert "用户：偏工程落地一点" in pack.recent_dialogue
        assert "算法理论研究，还是实际应用" not in pack.recent_dialogue

    def test_build_fact_pack_derives_previous_reply_from_transcript(self):
        pack = expr.build_interview_fact_pack(
            _multiturn_state(), "偏工程落地一点"
        )
        # 上一轮话术 = 本轮底稿之前的最后一条 assistant 底稿
        assert pack.previous_reply == "你更关注哪个层面的研究问题？"

    def test_previous_reply_kwarg_overrides_derived(self):
        """调用方持久化的「上一轮实际展示话术」优先于底稿推导。"""
        pack = expr.build_interview_fact_pack(
            _multiturn_state(),
            "偏工程落地一点",
            previous_reply="听起来你对强化学习挺有热情——那研究方式上呢？",
        )
        assert pack.previous_reply == "听起来你对强化学习挺有热情——那研究方式上呢？"

    def test_turn_phase_variants(self):
        state = _sample_state()
        state.completed_dimensions = []
        state.messages = []
        assert (
            expr.build_interview_fact_pack(state, "你好").turn_phase == "开场"
        )
        state.completed_dimensions = [InterviewDimension.RESEARCH_INTERESTS]
        assert (
            expr.build_interview_fact_pack(state, "你好").turn_phase == "中段"
        )
        state.missing_dimensions = []
        assert (
            expr.build_interview_fact_pack(state, "你好").turn_phase == "收尾"
        )

    def test_user_style_hint_variants(self):
        state = _sample_state()
        state.messages = []
        assert expr.build_interview_fact_pack(state, "工程").user_style_hint == "简短"
        assert (
            expr.build_interview_fact_pack(state, "我比较喜欢动手做工程落地")
            .user_style_hint
            == "常规"
        )
        long_message = "我本科做过两个强化学习的工程项目，" * 3
        assert (
            expr.build_interview_fact_pack(state, long_message).user_style_hint
            == "详细"
        )
        assert (
            expr.build_interview_fact_pack(state, "").user_style_hint
            == "未提供"
        )

    def test_empty_messages_yield_empty_context(self):
        state = _sample_state()
        state.messages = []
        pack = expr.build_interview_fact_pack(state, "你好")
        assert pack.recent_dialogue == ""
        assert pack.previous_reply == ""


# —— v4.2.0 多轮自然度：跨轮防重复闸门 ——


class TestRepetitionGate:
    def test_identical_opening_rejected(self):
        pack = _plain_pack(
            previous_reply="明白了，那我们继续聊聊：你更喜欢理论研究还是动手做工程？"
        )
        text = "明白了，那我们继续聊聊：换个说法，喜欢什么？"
        assert expr._validate_expression(text, pack) is False

    def test_shared_bridge_run_rejected(self):
        previous = "上一题聊得差不多，这个偏好挺有意思的，我们继续下一题。"
        pack = _plain_pack(previous_reply=previous)
        text = "好，这个偏好挺有意思的，我们继续下一题。喜欢什么？"
        # 开头不同，但复用了上一轮 ≥14 字承接片段 → 拒绝
        assert expr._validate_expression(text, pack) is False

    def test_shared_run_from_current_question_allowed(self):
        # 上一轮模板含本轮题面（如重问题复述）：题面属合法内容，不误伤
        pack = _plain_pack(
            previous_reply="没太明白，再说一次：你更喜欢理论研究还是动手做工程？",
            question_prompt="你更喜欢理论研究还是动手做工程？",
            options=("理论研究", "动手做工程"),
        )
        text = "换个说法哈，你更喜欢理论研究还是动手做工程？"
        assert expr._validate_expression(text, pack) is True

    def test_no_previous_reply_passes(self):
        pack = _plain_pack()
        text = "说到这个，你平时更喜欢琢磨哪块呢？"
        assert expr._validate_expression(text, pack) is True

    def test_fresh_opening_passes(self):
        pack = _plain_pack(
            previous_reply="明白了，那我们继续聊聊：你更喜欢理论研究还是动手做工程？"
        )
        text = "工程落地挺锻炼人的。那回到问题本身——喜欢什么？"
        assert expr._validate_expression(text, pack) is True


@pytest.mark.asyncio
async def test_render_prompt_includes_multiturn_sections(monkeypatch):
    """v3 模板必须加载成功并注入多轮上下文（加载失败回退 v1 时本用例失败）。"""
    _configured(monkeypatch)
    captured: dict = {}

    async def fake_result(messages, **_kwargs):
        captured["prompt"] = messages[0].content
        return LLMCompletionResult(
            text=_VALID_REWRITE,
            provider="glm",
            model="glm-4-flash",
        )

    monkeypatch.setattr(expr, "_llm_complete_result", fake_result)
    pack = dataclasses.replace(
        _sample_fact_pack(),
        recent_dialogue="用户：我对强化学习感兴趣\n清小搭：聊聊研究方式？",
        previous_reply="上一轮已经聊过研究兴趣了",
        turn_phase="中段",
        user_style_hint="简短",
    )
    result = await expr.render_interview_reply(pack)
    assert result.status == "available"
    prompt = captured["prompt"]
    assert "最近对话" in prompt
    assert "用户：我对强化学习感兴趣" in prompt
    assert "上一轮话术" in prompt
    assert "上一轮已经聊过研究兴趣了" in prompt
    assert "中段" in prompt
    assert "简短" in prompt


@pytest.mark.asyncio
async def test_render_backward_compatible_with_v1_fields_only(monkeypatch):
    """旧调用方（无多轮字段）仍可渲染：v3 占位符有默认值兜底。"""
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
