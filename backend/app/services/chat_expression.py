"""清小搭入口的访谈回复表达层。

确定性访谈状态机照常推进并持久化回复；本模块只在响应时基于结构化
事实包生成更自然的整段回复。任何失败（未配置凭据 / 网络错误 / 超时 /
输出未通过校验）都返回 disabled/unavailable，调用方必须完全降级回
固定模板——题序、画像状态、确认门与匹配触发绝不依赖本模块。

v4.2.0 多轮自然度增强：事实包扩展只读多轮上下文（最近对话底稿 /
上一轮实际展示话术 / 访谈阶段 / 用户风格标签，全部为服务端已有事实
的确定性投影），配套跨轮防重复闸门与提示词 v3。红线不变：确认门与
匹配结果不增强；题面/选项/招募/记忆逐字校验照常生效。
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
from app.services.prompts import load_prompt_template

logger = logging.getLogger(__name__)

MAX_EXPRESSION_CHARS = 400

# v4.2.0 多轮自然度：事实包新增只读多轮上下文（全部为服务端已有事实的
# 确定性投影，不给 LLM 留新事实空间）。上界用于控制提示词长度。
MAX_PREVIOUS_REPLY_CHARS = 200
_MAX_RECENT_DIALOGUE_MESSAGES = 6
_MAX_RECENT_DIALOGUE_CHARS = 800
_MAX_DIALOGUE_TURN_CHARS = 120
# 跨轮防重复闸门阈值：开头逐字相同 / 正文连续复用上一轮话术的片段长度。
_REPETITION_OPENING_CHARS = 10
_REPETITION_RUN_CHARS = 14

_DIMENSION_LABELS = {
    "research_interests": "研究兴趣",
    "research_mode": "研究方式",
    "mentorship_style": "指导偏好",
    "career_orientation": "生涯方向",
    "innovation_risk": "创新风险",
    "hard_constraints": "硬性条件",
}

_FORBIDDEN_TOKENS = ("画像已确认", "匹配完成", "确认画像")

# v4.1.0 自然度闸门：机器腔/客服腔标记出现在输出里 → 拒绝并降级固定模板
# （降级输出仍正确，只是不自然；宁降级不出戏）。标记若同时出现在事实包
# 提供的内容里（如题目/选项本身含该词），不视为违规，防止误伤合法题面。
_NATURALNESS_REJECT_TOKENS = (
    "作为一个AI",
    "作为一个智能",
    "作为一名人工智能",
    "作为一个语言模型",
    "人工智能语言模型",
    "人工智能助手",
    "亲爱的用户",
    "感谢您的反馈",
    "收到请回复",
    "期待您的回复",
    "亲，",
    # v4.2.0 追加：客服套话 / 服务用语（自然对话中不应出现）
    "很高兴为您",
    "为您服务",
    "还有什么可以帮",
    "希望以上",
    "祝您生活愉快",
)

# v4.0.0 任务1 A-3：提示词版本化。内嵌 v1 文本为兜底常量，运行期按
# prompt_versions.json 登记的当前版本加载（v4.2.0 起 rewrite_template
# 为 v3：多轮上下文 + 防重复衔接）；加载失败 → 回退本常量（fail-closed）。
_REWRITE_TEMPLATE_FALLBACK_V1 = (
    "你是访谈向导，请把服务端给出的下一句话用自然、温暖、口语化的中文"
    "转述给用户，让对话像一位真人导师助理。\n"
    "硬性要求：\n"
    "1. 必须完整保留服务端题目要传达的信息（问题本身、选项、确认指令）；\n"
    "2. 可以用一两句话自然承接用户上一句，但不得添加题目之外的新事实、"
    "新建议或新问题；\n"
    "3. 不得宣布画像已确认或匹配完成，不得出现任何控制标记；\n"
    f"4. 输出不超过 {MAX_EXPRESSION_CHARS} 字；\n"
    "5. 若下方提供了「招募摘要」，可在结尾用一句话自然带出，但必须原样"
    "保留其中的招募名称、截止日期等全部事实，不得改动、增删或美化；"
    "未提供则完全不要提招募；\n"
    "6. 若下方提供了「记忆摘要」，可在承接用户上一句时自然带出，但必须"
    "原样保留其中的用户事实，不得改动、增删；未提供则不要提。\n\n"
    "用户上一句：{user_message}\n"
    "画像进度：已完成维度 {completed}；待完成维度 {missing}；{constraints}\n"
    "服务端题目（必须保留其全部信息）：{question_prompt}\n"
    "选项：{options}\n"
    "招募摘要：{recruitment_summary}\n"
    "记忆摘要：{memory_summary}\n"
    "请直接输出对用户说的话："
)
_REWRITE_TEMPLATE = load_prompt_template(
    "rewrite_template", fallback=_REWRITE_TEMPLATE_FALLBACK_V1
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
    # v4.0.0 可选事实段：默认空串向后兼容，仅调用方显式注入时出现。
    # recruitment_summary 为招募原文事实句；memory_summary 只含已确认的
    # 用户事实片段（不含框架词，如"工程落地"而非"已确认偏好是工程落地"），
    # 逐字校验按 >=4 字片段强校验，防表达层改写用户事实。
    recruitment_summary: str = ""
    memory_summary: str = ""
    # v4.2.0 多轮自然度上下文（只读事实投影，见 build_interview_fact_pack）：
    # recent_dialogue 为最近几轮「用户：…/清小搭：…」对话底稿（assistant 侧
    # 是状态机固定话术底稿，非表达层输出）；previous_reply 为上一轮实际展示
    # 话术（调用方持久化值优先，否则回退状态机底稿推导）；turn_phase 与
    # user_style_hint 为确定性阶段/风格标签。LLM 只被允许引用其中出现的
    # 事实，闸门照常逐字校验，不给自由发挥留空间。
    recent_dialogue: str = ""
    previous_reply: str = ""
    turn_phase: str = ""
    user_style_hint: str = ""


def _dimension_labels(dimensions) -> tuple[str, ...]:
    return tuple(
        _DIMENSION_LABELS.get(getattr(dim, "value", str(dim)), str(dim))
        for dim in dimensions
    )


def _message_parts(messages) -> list[tuple[str, str]]:
    """把 pydantic / dict 两种消息形态统一成 (role, content) 列表。"""
    parts: list[tuple[str, str]] = []
    for item in messages or []:
        if isinstance(item, dict):
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
        else:
            role = str(getattr(item, "role", "") or "")
            content = str(getattr(item, "content", "") or "")
        parts.append((role, content))
    return parts


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _derive_recent_dialogue(messages) -> tuple[str, str]:
    """从状态机消息底稿推导 (recent_dialogue, previous_reply)。

    确定性只读投影：末位 assistant 消息即本轮话术底稿（question_prompt
    已单独注入，跳过）；previous_reply 取其前最后一条 assistant 底稿。
    调用方持久化的「上一轮实际展示话术」优先于本推导（见 chat.py）。
    """
    parts = _message_parts(messages)
    if parts and parts[-1][0] == "assistant":
        parts = parts[:-1]
    previous_reply = ""
    for role, content in reversed(parts):
        if role == "assistant" and content.strip():
            previous_reply = _clip(content, MAX_PREVIOUS_REPLY_CHARS)
            break
    lines = [
        f"{'用户' if role == 'user' else '清小搭'}：{_clip(content, _MAX_DIALOGUE_TURN_CHARS)}"
        for role, content in parts[-_MAX_RECENT_DIALOGUE_MESSAGES:]
        if content.strip()
    ]
    dialogue = "\n".join(lines)
    if len(dialogue) > _MAX_RECENT_DIALOGUE_CHARS:
        dialogue = "…" + dialogue[-_MAX_RECENT_DIALOGUE_CHARS:]
    return dialogue, previous_reply


def _turn_phase(completed, missing) -> str:
    """确定性访谈阶段标签（供提示词做阶段化语气，不影响状态机）。"""
    if not completed:
        return "开场"
    if not missing:
        return "收尾"
    return "中段"


def _user_style_hint(message: str) -> str:
    """用户最新一句的确定性风格标签（长度分档，无 LLM 参与）。"""
    length = len((message or "").strip())
    if not length:
        return "未提供"
    if length <= 8:
        return "简短"
    if length <= 39:
        return "常规"
    return "详细"


def build_interview_fact_pack(
    state: InterviewStateResponse,
    latest_user_message: str,
    *,
    recruitment_summary: str = "",
    memory_summary: str = "",
    previous_reply: str = "",
) -> InterviewFactPack:
    """从只读状态投影构造事实包；不访问数据库、不改变任何状态。

    previous_reply 为调用方持久化的「上一轮实际展示话术」（可为空）；
    非空时优先于状态机底稿推导，使防重复闸门对齐用户真实看到的文本。
    """
    question = state.current_question
    profile = state.profile
    if profile.hard_constraints:
        constraint_status = f"已确认 {len(profile.hard_constraints)} 条硬性条件"
    elif profile.draft_hard_constraints or profile.unresolved_hard_constraints:
        constraint_status = "有硬性条件待确认"
    else:
        constraint_status = "尚未确认硬性条件"
    derived_dialogue, derived_previous = _derive_recent_dialogue(state.messages)
    return InterviewFactPack(
        user_message=(latest_user_message or "").strip(),
        # 以实际展示给用户的回复为准：动态题（如硬约束确认题）只存在于
        # assistant_message，题库 current_question 是静态原始题面，两者会错位。
        question_prompt=(state.assistant_message if question else ""),
        options=(
            tuple(option.label for option in question.options) if question else ()
        ),
        completed_dimensions=_dimension_labels(state.completed_dimensions),
        missing_dimensions=_dimension_labels(state.missing_dimensions),
        hard_constraint_status=constraint_status,
        recruitment_summary=recruitment_summary.strip(),
        memory_summary=memory_summary.strip(),
        recent_dialogue=derived_dialogue,
        previous_reply=(
            _clip(previous_reply, MAX_PREVIOUS_REPLY_CHARS)
            if previous_reply.strip()
            else derived_previous
        ),
        turn_phase=_turn_phase(
            state.completed_dimensions, state.missing_dimensions
        ),
        user_style_hint=_user_style_hint(latest_user_message),
    )


def _core_fragments(prompt: str) -> list[str]:
    """取题目中长度 >=6 的片段作为覆盖检查依据（宽松匹配）。"""
    return [
        part.strip()
        for part in re.split(r"[，。！？；、,.!?;:：\s（）()“”\"']+", prompt)
        if len(part.strip()) >= 6
    ]


def _recruitment_verbatim_tokens(summary: str) -> tuple[str, ...]:
    """招募摘要中的事实性 token（日期/截止/名额），逐字校验用。

    只提取"改动即失实"的硬事实：截止日期、招录名额；申请方式等关键短语
    原样保留。校验时两侧都去掉空白，防 LLM 只改标点/空格。
    """
    tokens: list[str] = []
    for pattern in (r"\d{4}-\d{2}-\d{2}", r"\d{1,2}月\d{1,2}日", r"招\s*\d+\s*名"):
        tokens.extend(re.findall(pattern, summary))
    for phrase in ("邮箱投递", "站内投递", "申请链接", "发送简历"):
        if phrase in summary:
            tokens.append(phrase)
    return tuple(tokens)


def _summary_verbatim_tokens(summary: str) -> tuple[str, ...]:
    """记忆/招募摘要的通用逐字片段（>=4 字），防表达层改写用户事实。"""
    return tuple(
        part.strip()
        for part in re.split(r"[，。！？；、,.!?;:：\s（）()“”\"']+", summary)
        if len(part.strip()) >= 4
    )


def _naturalness_violation(text: str, fact_pack: InterviewFactPack) -> bool:
    """机器腔/客服腔标记检测；标记同时出现在事实包内容里时不误伤。"""
    allowed = " ".join(
        part
        for part in (
            fact_pack.question_prompt,
            " ".join(fact_pack.options),
            fact_pack.recruitment_summary,
            fact_pack.memory_summary,
            fact_pack.user_message,
        )
        if part
    )
    return any(
        token in text and token not in allowed
        for token in _NATURALNESS_REJECT_TOKENS
    )


# v4.3.0 纯文本输出闸门：QXD 渠道不渲染 Markdown，LLM 输出含加粗/
# 标题/代码块/行首列表符号 → 拒绝降级固定模板。保守规则（行首 "- " 只在
# 确为列表时命中），防误伤正常中文文本；标记来自事实包内容（题面本身
# 含列表等）时不视为违规。
_MARKDOWN_INLINE_TOKENS = ("**", "```")
_MARKDOWN_LINE_RE = re.compile(r"^(?:#{1,6}\s|-\s)", re.MULTILINE)


def _markdown_violation(text: str, fact_pack: InterviewFactPack) -> bool:
    allowed = "\n".join(
        part
        for part in (
            fact_pack.question_prompt,
            "\n".join(fact_pack.options),
            fact_pack.recruitment_summary,
            fact_pack.memory_summary,
            fact_pack.user_message,
        )
        if part
    )
    for token in _MARKDOWN_INLINE_TOKENS:
        if token in text and token not in allowed:
            return True
    if _MARKDOWN_LINE_RE.search(text) and not _MARKDOWN_LINE_RE.search(allowed):
        return True
    return False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _maximal_common_runs(a: str, b: str, min_len: int) -> list[str]:
    """a 与 b 的全部极大公共连续子串（长度 >= min_len）。

    输入均为闸门用短串（<=600 字），滚动数组 DP 足够；仅收集无法继续
    延伸的极大片段，避免同一片段重复计数。
    """
    runs: list[str] = []
    if len(a) < min_len or len(b) < min_len:
        return runs
    prev_row = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        char = a[i - 1]
        for j in range(1, len(b) + 1):
            if char == b[j - 1]:
                length = prev_row[j - 1] + 1
                cur[j] = length
                if length >= min_len and (
                    i == len(a) or j == len(b) or a[i] != b[j]
                ):
                    runs.append(a[i - length : i])
        prev_row = cur
    return runs


def _repetition_violation(text: str, fact_pack: InterviewFactPack) -> bool:
    """v4.2.0 跨轮防重复闸门（确定性）。

    上一轮话术存在时，以下任一命中即拒绝并降级固定模板：
    1. 开头连续 {_REPETITION_OPENING_CHARS} 字（去空白）与上一轮完全相同——
       表达层最常见的机器式雷同承接（「好的，那我们……」逐轮复读）；
    2. 与上一轮话术共享 >={_REPETITION_RUN_CHARS} 字的连续片段，且该片段
       不属于本轮合法内容（题面/选项/招募/记忆/用户原话）——题面等逐字
       必现内容豁免，避免误伤正常复述。
    """
    previous = fact_pack.previous_reply
    if not previous:
        return False
    candidate = _normalize(text)
    prev = _normalize(previous)
    if not candidate or not prev:
        return False
    if (
        len(candidate) >= _REPETITION_OPENING_CHARS
        and len(prev) >= _REPETITION_OPENING_CHARS
        and candidate[:_REPETITION_OPENING_CHARS]
        == prev[:_REPETITION_OPENING_CHARS]
    ):
        return True
    allowed = _normalize(
        " ".join(
            part
            for part in (
                fact_pack.question_prompt,
                " ".join(fact_pack.options),
                fact_pack.recruitment_summary,
                fact_pack.memory_summary,
                fact_pack.user_message,
            )
            if part
        )
    )
    return any(
        run not in allowed
        for run in _maximal_common_runs(
            candidate, prev, _REPETITION_RUN_CHARS
        )
    )


def _validate_expression(text: str, fact_pack: InterviewFactPack) -> bool:
    """输出闸门：非空 / 长度 / 禁词 / 题面关键信息覆盖 / 事实段逐字校验 /
    自然度标记（机器腔/客服腔 → 拒绝降级）。"""
    if not text:
        return False
    if len(text) > MAX_EXPRESSION_CHARS:
        return False
    if any(token in text for token in _FORBIDDEN_TOKENS):
        return False
    if _naturalness_violation(text, fact_pack):
        return False
    # v4.3.0 纯文本闸门：Markdown 标记 → 拒绝降级（QXD 渠道不渲染）。
    if _markdown_violation(text, fact_pack):
        return False
    # v4.2.0 跨轮防重复：与上一轮话术雷同（开头逐字相同 / 长片段复用）
    # → 拒绝降级，倒逼承接方式轮换（宁降级不出戏）。
    if _repetition_violation(text, fact_pack):
        return False
    if fact_pack.options and not all(
        option in text for option in fact_pack.options
    ):
        return False
    fragments = _core_fragments(fact_pack.question_prompt)
    if fragments and not any(fragment in text for fragment in fragments):
        return False
    # v4.0.0 事实段逐字校验：招募/记忆摘要里的硬事实必须逐字出现，
    # 只改标点空白也算通过（两侧去空白比较）；缺失/改写即拒绝 → 降级。
    normalized = re.sub(r"\s+", "", text)
    if fact_pack.recruitment_summary:
        tokens = [
            re.sub(r"\s+", "", token)
            for token in _recruitment_verbatim_tokens(
                fact_pack.recruitment_summary
            )
        ]
        if any(token not in normalized for token in tokens):
            return False
    for summary in (fact_pack.recruitment_summary, fact_pack.memory_summary):
        if summary:
            tokens = [
                re.sub(r"\s+", "", token)
                for token in _summary_verbatim_tokens(summary)
            ]
            if tokens and not all(token in normalized for token in tokens):
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
                    recruitment_summary=fact_pack.recruitment_summary or "无",
                    memory_summary=fact_pack.memory_summary or "无",
                    # v4.2.0 多轮自然度上下文（v1 兜底模板不含这些占位符，
                    # str.format 忽略多余实参，向后兼容）
                    recent_dialogue=fact_pack.recent_dialogue or "无",
                    previous_reply=fact_pack.previous_reply or "无",
                    turn_phase=fact_pack.turn_phase or "未提供",
                    user_style_hint=fact_pack.user_style_hint or "未提供",
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
