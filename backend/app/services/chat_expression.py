"""清小搭入口的访谈回复表达层。

确定性访谈状态机照常推进并持久化回复；本模块只在响应时基于结构化
事实包生成更自然的整段回复。任何失败（未配置凭据 / 网络错误 / 超时 /
输出未通过校验）都返回 disabled/unavailable，调用方必须完全降级回
固定模板——题序、画像状态、确认门与匹配触发绝不依赖本模块。
"""

import logging
import re
from dataclasses import dataclass

from app.core.config import settings
from app.schemas.advisor import LLMMessage
from app.schemas.interview import InterviewStateResponse
from app.services.llm import (
    LLM_SYSTEM_PROMPT,
    InterviewEnhancement,
    _llm_complete_result,
)

logger = logging.getLogger(__name__)

MAX_EXPRESSION_CHARS = 400

_DIMENSION_LABELS = {
    "research_interests": "研究兴趣",
    "research_mode": "研究方式",
    "mentorship_style": "指导偏好",
    "career_orientation": "生涯方向",
    "innovation_risk": "创新风险",
    "hard_constraints": "硬性条件",
}

_FORBIDDEN_TOKENS = ("画像已确认", "匹配完成", "确认画像")

_REWRITE_TEMPLATE = (
    "你是访谈向导，请把服务端给出的下一句话用自然、温暖、口语化的中文"
    "转述给用户，让对话像一位真人导师助理。\n"
    "硬性要求：\n"
    "1. 必须完整保留服务端题目要传达的信息（问题本身、选项、确认指令）；\n"
    "2. 可以用一两句话自然承接用户上一句，但不得添加题目之外的新事实、"
    "新建议或新问题；\n"
    "3. 不得宣布画像已确认或匹配完成，不得出现任何控制标记；\n"
    f"4. 输出不超过 {MAX_EXPRESSION_CHARS} 字。\n\n"
    "用户上一句：{user_message}\n"
    "画像进度：已完成维度 {completed}；待完成维度 {missing}；{constraints}\n"
    "服务端题目（必须保留其全部信息）：{question_prompt}\n"
    "选项：{options}\n"
    "请直接输出对用户说的话："
)


@dataclass(frozen=True)
class InterviewFactPack:
    """表达层输入：只含状态机已确认的事实，不给 LLM 留自由发挥空间。"""

    user_message: str
    question_prompt: str
    options: tuple[str, ...]
    completed_dimensions: tuple[str, ...]
    missing_dimensions: tuple[str, ...]
    hard_constraint_status: str


def _dimension_labels(dimensions) -> tuple[str, ...]:
    return tuple(
        _DIMENSION_LABELS.get(getattr(dim, "value", str(dim)), str(dim))
        for dim in dimensions
    )


def build_interview_fact_pack(
    state: InterviewStateResponse,
    latest_user_message: str,
) -> InterviewFactPack:
    """从只读状态投影构造事实包；不访问数据库、不改变任何状态。"""
    question = state.current_question
    profile = state.profile
    if profile.hard_constraints:
        constraint_status = f"已确认 {len(profile.hard_constraints)} 条硬性条件"
    elif profile.draft_hard_constraints or profile.unresolved_hard_constraints:
        constraint_status = "有硬性条件待确认"
    else:
        constraint_status = "尚未确认硬性条件"
    return InterviewFactPack(
        user_message=(latest_user_message or "").strip(),
        question_prompt=question.prompt if question else "",
        options=(
            tuple(option.label for option in question.options) if question else ()
        ),
        completed_dimensions=_dimension_labels(state.completed_dimensions),
        missing_dimensions=_dimension_labels(state.missing_dimensions),
        hard_constraint_status=constraint_status,
    )


def _core_fragments(prompt: str) -> list[str]:
    """取题目中长度 >=6 的片段作为覆盖检查依据（宽松匹配）。"""
    return [
        part.strip()
        for part in re.split(r"[，。！？；、,.!?;:：\s（）()“”\"']+", prompt)
        if len(part.strip()) >= 6
    ]


def _validate_expression(text: str, fact_pack: InterviewFactPack) -> bool:
    """输出闸门：非空 / 长度 / 禁词 / 题面关键信息覆盖。"""
    if not text:
        return False
    if len(text) > MAX_EXPRESSION_CHARS:
        return False
    if any(token in text for token in _FORBIDDEN_TOKENS):
        return False
    if fact_pack.options and not all(
        option in text for option in fact_pack.options
    ):
        return False
    fragments = _core_fragments(fact_pack.question_prompt)
    if fragments and not any(fragment in text for fragment in fragments):
        return False
    return True


async def render_interview_reply(
    fact_pack: InterviewFactPack,
) -> InterviewEnhancement:
    """整段重写访谈回复；任何失败都不阻断状态机（调用方降级回固定模板）。"""
    if not settings.llm_credentials:
        return InterviewEnhancement(text=None, provider=None, status="disabled")

    result = await _llm_complete_result(
        [
            LLMMessage(
                role="user",
                content=_REWRITE_TEMPLATE.format(
                    user_message=fact_pack.user_message[:800],
                    completed="、".join(fact_pack.completed_dimensions) or "无",
                    missing="、".join(fact_pack.missing_dimensions) or "无",
                    constraints=fact_pack.hard_constraint_status,
                    question_prompt=fact_pack.question_prompt[:1200],
                    options="；".join(fact_pack.options) or "无",
                ),
            )
        ],
        timeout_seconds=settings.LLM_INTERVIEW_ENHANCEMENT_TIMEOUT_SECONDS,
    )
    if result is None:
        provider = settings.configured_llm_providers[0]
        return InterviewEnhancement(
            text=None,
            provider=provider,
            status="unavailable",
        )

    candidate = re.sub(r"\s+", " ", result.text).strip(" \"'“”")
    if not _validate_expression(candidate, fact_pack):
        logger.warning(
            "chat_expression provider=%s model=%s status=rejected_output",
            result.provider,
            result.model,
        )
        return InterviewEnhancement(
            text=None,
            provider=result.provider,
            status="unavailable",
        )
    logger.info(
        "chat_expression provider=%s model=%s status=available chars=%d",
        result.provider,
        result.model,
        len(candidate),
    )
    return InterviewEnhancement(
        text=candidate,
        provider=result.provider,
        status="available",
    )
