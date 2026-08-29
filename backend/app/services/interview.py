"""A3 持久化动态访谈状态机。

该模块只负责收集、编辑和确认学生画像。它不读取导师、不计算分数，
也不实现 A4 的召回或排序。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.questionnaire_session import QuestionnaireSession
from app.schemas.interview import (
    DraftHardConstraint,
    HardConstraint,
    InterviewDimension,
    InterviewQuestion,
    InterviewStateResponse,
    InterviewStatus,
    StudentPortrait,
    StudentPortraitPatch,
)
from app.services import off_topic
from app.services.memory_service import remember_confirmed_portrait


class InterviewNotFoundError(LookupError):
    pass


class InterviewAccessError(PermissionError):
    pass


class InterviewConflictError(ValueError):
    pass


QUESTION_ORDER = (
    InterviewDimension.RESEARCH_INTERESTS,
    InterviewDimension.RESEARCH_MODE,
    InterviewDimension.MENTORSHIP_STYLE,
    InterviewDimension.CAREER_ORIENTATION,
    InterviewDimension.INNOVATION_RISK,
    InterviewDimension.HARD_CONSTRAINTS,
)

QUESTION_BANK: dict[InterviewDimension, InterviewQuestion] = {
    InterviewDimension.RESEARCH_INTERESTS: InterviewQuestion(
        question_id="research_interests",
        dimension=InterviewDimension.RESEARCH_INTERESTS,
        prompt="先聊聊你真正好奇的事：最想投入哪 1—3 个研究主题或具体问题？写到子方向会更有帮助。",
        answer_type="text",
        information_goal="确定主题召回边界，避免只使用宽泛专业名称。",
    ),
    InterviewDimension.RESEARCH_MODE: InterviewQuestion(
        question_id="research_mode",
        dimension=InterviewDimension.RESEARCH_MODE,
        prompt="面对同一研究主题，你更偏好理论与原理、工程与落地，还是两者结合？",
        answer_type="single_choice",
        options=[
            {"value": "theory", "label": "更爱追根究底：理论与原理"},
            {"value": "engineering", "label": "更爱把想法做出来：工程与落地"},
            {"value": "mixed", "label": "理论和落地都想兼顾"},
            {"value": "undecided", "label": "还在探索，暂不确定"},
        ],
        information_goal="区分研究方法与产出形态偏好。",
    ),
    InterviewDimension.MENTORSHIP_STYLE: InterviewQuestion(
        question_id="mentorship_style",
        dimension=InterviewDimension.MENTORSHIP_STYLE,
        prompt="想象一下理想的合作节奏：你希望导师高频具体指导、给方向后放手探索，还是两者平衡？",
        answer_type="single_choice",
        options=[
            {"value": "high_guidance", "label": "希望多交流、多给具体反馈"},
            {"value": "balanced", "label": "关键节点指导，平时自主推进"},
            {"value": "autonomous", "label": "给我方向，我喜欢自主探索"},
            {"value": "undecided", "label": "还没想好，可以边做边看"},
        ],
        information_goal="识别指导密度与自主性需求。",
    ),
    InterviewDimension.CAREER_ORIENTATION: InterviewQuestion(
        question_id="career_orientation",
        dimension=InterviewDimension.CAREER_ORIENTATION,
        prompt="把时间拨到未来三到五年，你更想走向学术深造、产业就业、国家任务，还是保留混合选择？",
        answer_type="single_choice",
        options=[
            {"value": "academic", "label": "继续深挖，走学术道路"},
            {"value": "industry", "label": "进入产业，解决真实问题"},
            {"value": "national_mission", "label": "参与国家任务与重大工程"},
            {"value": "mixed", "label": "先保留多种可能"},
            {"value": "undecided", "label": "暂不确定，想继续了解"},
        ],
        information_goal="确定长期目标，避免把使命或市场倾向强加给学生。",
    ),
    InterviewDimension.INNOVATION_RISK: InterviewQuestion(
        question_id="innovation_risk",
        dimension=InterviewDimension.INNOVATION_RISK,
        prompt="选课题像选路线：你更愿意闯少有人走的高风险新方向、沿成熟路径稳步推进，还是两者平衡？",
        answer_type="single_choice",
        options=[
            {"value": "pioneering", "label": "愿意冒险，探索新方向"},
            {"value": "balanced", "label": "新意与可行性都要"},
            {"value": "mature", "label": "偏好成熟路径和清晰回报"},
            {"value": "undecided", "label": "暂不确定"},
        ],
        information_goal="识别原始创新偏好与可承受的不确定性。",
    ),
    InterviewDimension.HARD_CONSTRAINTS: InterviewQuestion(
        question_id="hard_constraints",
        dimension=InterviewDimension.HARD_CONSTRAINTS,
        prompt="最后划一下不可妥协的边界：地点、时间投入、学历阶段、语言、保密资格或毕业安排，有必须满足的条件吗？没有就回答“无”。",
        answer_type="text",
        information_goal="提前发现不可妥协条件，供后续硬约束使用。",
    ),
}

_CONFIRM_SIGNALS = {
    "确认画像",
    "画像确认",
    "确认无误",
    "确认并匹配",
    "以上无误",
}
_GREETING_ONLY = {
    "你好",
    "您好",
    "嗨",
    "hello",
    "hi",
    "开始",
    "开始吧",
}
_EMPTY_CONSTRAINTS = {"无", "没有", "暂无", "都没有", "无硬性条件", "没有硬性条件"}
_DRAFT_CONFIRM_SIGNALS = {"确认", "是", "是的", "对", "正确", "不可妥协"}
_DRAFT_REJECT_SIGNALS = {
    "否",
    "不是",
    "取消",
    "删除",
    "不作为硬约束",
    "只是偏好",
    "可以放宽",
}
# v4.2.x 修复1/2：硬约束值黑名单与负向表达模式统一收口在 off_topic.py
# （权威词表，matching 复用，避免双份定义漂移）。命中即整体清空，不产生
# 任何草案；与 off_topic 守卫不同，这里是"已放行的答案"进入画像前的
# 最后一层值清洗。
from app.services.off_topic import (  # noqa: E402
    CONSTRAINT_JUNK_SIGNALS,
    is_constraint_rejection_answer,
)


def _is_constraint_rejection(answer: str) -> bool:
    cleaned = answer.strip(" ，。；、,.!?！？")
    if cleaned in _DRAFT_REJECT_SIGNALS or cleaned.lower() in _EMPTY_CONSTRAINTS:
        return True
    return is_constraint_rejection_answer(cleaned)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _message(role: str, content: str) -> dict[str, str]:
    return {
        "role": role,
        "content": content,
        "created_at": _now().isoformat(),
    }


def _portrait(session: QuestionnaireSession) -> StudentPortrait:
    return StudentPortrait.model_validate(session.portrait or {})


def _completed_dimensions(profile: StudentPortrait) -> list[InterviewDimension]:
    completed: list[InterviewDimension] = []
    if profile.research_interests or profile.interest_statement:
        # v4.2.2（P1-K②）：研究兴趣题答"无方向"时仅写 interest_statement
        # 也算已作答（熔断回声环）；正常路径两者同写，行为不变。
        completed.append(InterviewDimension.RESEARCH_INTERESTS)
    if profile.research_mode is not None:
        completed.append(InterviewDimension.RESEARCH_MODE)
    if profile.mentorship_style is not None:
        completed.append(InterviewDimension.MENTORSHIP_STYLE)
    if profile.career_orientation is not None:
        completed.append(InterviewDimension.CAREER_ORIENTATION)
    if profile.innovation_risk is not None:
        completed.append(InterviewDimension.INNOVATION_RISK)
    if (
        profile.hard_constraints is not None
        and not profile.draft_hard_constraints
        and not profile.unresolved_hard_constraints
    ):
        completed.append(InterviewDimension.HARD_CONSTRAINTS)
    return completed


def _missing_dimensions(profile: StudentPortrait) -> list[InterviewDimension]:
    completed = set(_completed_dimensions(profile))
    return [dimension for dimension in QUESTION_ORDER if dimension not in completed]


def _next_question(profile: StudentPortrait) -> InterviewQuestion | None:
    if profile.draft_hard_constraints:
        return QUESTION_BANK[InterviewDimension.HARD_CONSTRAINTS].model_copy(
            update={
                "prompt": profile.draft_hard_constraints[
                    0
                ].confirmation_prompt,
                "information_goal": "逐条确认自然语言约束草案，确认前不生效。",
            }
        )
    if profile.unresolved_hard_constraints:
        source_text = profile.unresolved_hard_constraints[0]
        return QUESTION_BANK[InterviewDimension.HARD_CONSTRAINTS].model_copy(
            update={
                "prompt": (
                    f"关于“{source_text}”，你希望约束的具体条件是什么？"
                    "请用自然语言说明必须满足的值，或回复“不作为硬约束”。"
                ),
                "information_goal": "澄清低置信自然语言约束，不猜测其含义。",
            }
        )
    missing = _missing_dimensions(profile)
    return QUESTION_BANK[missing[0]] if missing else None


# v4.2.x 修复6：画像字段清洗 —— 命令句式（帮我推荐/想要/想找）与疑问句式
# （怎么样/是什么）不入档；"推荐系统"这类名词短语不误伤（推荐仅后接请求词
# 时视为命令）。配合长度上限与前后缀剥离，整句开场白不再整句入档。
_INTEREST_COMMAND_RE = re.compile(
    r"帮我|麻烦|请(?:求|问|教)?|想要|想找|可以吗|给我|"
    r"推荐(?:一下|几个|导师|些|个|您|你)|求推荐"
)
_INTEREST_QUESTION_RE = re.compile(
    r"怎么样|怎么|为什么|为啥|什么|哪里|哪儿|如何|哪个|哪些"
)
# v4.2.2 修复（P1-H/P1-I）：长句/复杂开场白中的非方向性碎块 —— 绩点排名、
# 连接词与修饰碎块不入档（"绩点3.8""排名前5%""顺便""还有"）。
_INTEREST_JUNK_RE = re.compile(
    r"绩点|排名|分数|成绩|GPA|前\s*\d|top\s*\d|顺便|另外|还有|同时|然后|"
    r"的话|其实|就是|主要是|因为|所以|目前|现在|暂时|基本|大概|差不多|"
    r"之后|以后|后来|平时|日常|也挺|也比较|比较|挺想|蛮想|想先|想从"
)
# 长句首尾的软性连接词/承接词（多维修改"顺便把指导偏好…"拆分后的残余）
_INTEREST_JOINER_RE = re.compile(
    r"^(?:顺便|另外|还有|然后|同时|再|也|以及|和|还有|接着|之后|后面|"
    r"剩下|其余的?|其他的?)\s*"
    r"|(?:\s*(?:顺便|另外|还有|然后|同时|也|以及|和|接着))$"
)
_INTEREST_DECLINE = frozenset({
    "无", "没有", "都没", "暂无", "暂时没有", "没想好", "还没想好",
    "不确定", "不知道", "不清楚", "都可以", "都行", "随便", "无所谓",
    "再说吧", "看看再说", "再看看", "还没", "想不出来", "没什么想法",
    "没想法", "先看看", "了解下", "了解一下",
})


def _normalize_interest_piece(value: str) -> str:
    value = value.strip(" ，。；、,.!?！？")
    # v4.2.2（P1-H）：先剥离长句首尾的连接/承接词（"顺便""另外""还有"…），
    # 再剥离声明前缀/后缀，使"顺便我也想研究推荐系统"→"推荐系统"。
    # 迭代剥离直到稳定："顺便也想…"需先剥"顺便"再剥"也"（正则锚定 ^ 单次）。
    previous = None
    while value != previous:
        previous = value
        value = _INTEREST_JOINER_RE.sub("", value).strip()
    prefixes = (
        "我对",
        "我是学",
        "我的方向是",
        "我方向是",
        "我也想研究",
        "我也想做",
        "我也想",
        "我想研究",
        "我想做",
        "我想",
        "我也",
        "希望研究",
        "想做",
        "想研究",
        "想学",
        "我是",
        "研究",
        "做",
    )
    suffixes = ("很感兴趣", "感兴趣", "相关研究", "方向", "领域", "的")
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    for suffix in suffixes:
        if value.endswith(suffix):
            value = value[: -len(suffix)].strip()
    return value


def _is_interest_decline(answer: str) -> bool:
    """P1-K②/P2-L：研究兴趣题的"无方向"整体拒绝表达 → 熔断推进，不回声环。

    只匹配整体拒绝（去掉句尾标点后精确等于），不做子串匹配——"不确定在
    AI 还是 CV"这类夹带方向词的表达不走熔断（交给标签提取）。
    """
    cleaned = answer.strip(" ，。；、,.!?！？~～")
    return cleaned in _INTEREST_DECLINE


def _english_interest_tags(text: str) -> list[str]:
    """P2-E：从英文答案中提取方向词标签（原词大小写入档，词法召回可命中）。

    纯英文句子（"I'm interested in NLP and machine learning"）在中文分隔下是
    单个超长片段，会被 12 字符上限整体丢弃 → 维度永不完成、同题无限重问。
    这里按词边界从 _ENGLISH_DIRECTION_WORDS 词表提取（含多词短语如
    machine learning），不在此表内的英文单词不进画像，避免整句当标签。
    """
    lowered = f" {text.lower()} "
    found: list[str] = []
    for word in off_topic._ENGLISH_DIRECTION_WORDS:
        if (
            f" {word} " in lowered
            or lowered.startswith(f"{word} ")
            or lowered.endswith(f" {word}")
        ):
            match = re.search(re.escape(word), text, flags=re.IGNORECASE)
            canonical = match.group(0) if match else word
            if canonical.lower() not in {tag.lower() for tag in found}:
                found.append(canonical)
    return found


def _interest_tags(answer: str) -> list[str]:
    cleaned = answer.strip()
    if (
        cleaned.lower() in _GREETING_ONLY
        or cleaned in _CONFIRM_SIGNALS
        or cleaned in CONSTRAINT_JUNK_SIGNALS
        or off_topic.is_uncertain(cleaned)
        or len(cleaned) < 2
    ):
        return []
    pieces = re.split(r"[，,、；;。\n]|\s+(?:和|与|及)\s+|和|以及", cleaned)
    tags: list[str] = []
    for piece in pieces:
        item = _normalize_interest_piece(piece)
        if (
            1 < len(item) <= 12
            and item not in tags
            and item not in CONSTRAINT_JUNK_SIGNALS
            and not _INTEREST_COMMAND_RE.search(item)
            and not _INTEREST_QUESTION_RE.search(item)
            and not _INTEREST_JUNK_RE.search(item)
        ):
            tags.append(item)
    # P2-E：中英文混排时英文方向词单独补入（中文片段已提取的部分按大小写去重）
    tags.extend(_english_interest_tags(cleaned))
    return tags[:8]


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _choice_from_answer(
    answer: str,
    mappings: tuple[tuple[str, tuple[str, ...]], ...],
) -> str:
    for value, keywords in mappings:
        if _contains_any(answer, keywords):
            return value
    return "undecided"


def _extract_categorical_signals(
    profile: dict[str, Any],
    answer: str,
    *,
    overwrite: bool = False,
) -> None:
    if (profile.get("research_mode") is None or overwrite) and _contains_any(
        answer,
        ("理论", "原理", "证明", "工程", "落地", "应用", "都想", "结合", "不确定", "都可以"),
    ):
        profile["research_mode"] = _choice_from_answer(
            answer,
            (
                ("mixed", ("结合", "都想", "两者", "兼顾")),
                ("theory", ("理论", "原理", "证明", "基础研究")),
                ("engineering", ("工程", "落地", "应用", "系统实现")),
                ("undecided", ("不确定", "都可以", "无所谓")),
            ),
        )
    if (profile.get("mentorship_style") is None or overwrite) and _contains_any(
        answer,
        ("手把手", "高频", "具体指导", "自主", "自由探索", "放养", "平衡", "都可以"),
    ):
        profile["mentorship_style"] = _choice_from_answer(
            answer,
            (
                ("high_guidance", ("手把手", "高频", "具体指导", "多指导")),
                ("autonomous", ("自主", "自由探索", "放养", "少干预")),
                ("balanced", ("平衡", "适度", "结合")),
                ("undecided", ("不确定", "都可以", "无所谓")),
            ),
        )
    if (profile.get("career_orientation") is None or overwrite) and _contains_any(
        answer,
        ("读博", "学术", "高校", "研究所", "就业", "大厂", "产业", "国家任务", "大国重器", "军工", "航天", "混合", "都可以"),
    ):
        profile["career_orientation"] = _choice_from_answer(
            answer,
            (
                ("national_mission", ("国家任务", "大国重器", "军工", "航天")),
                ("academic", ("读博", "学术", "高校", "研究所")),
                ("industry", ("就业", "大厂", "产业", "创业", "挣钱")),
                ("mixed", ("混合", "兼顾", "都想")),
                ("undecided", ("不确定", "都可以", "无所谓")),
            ),
        )
    explicit_risk_signal = _contains_any(
        answer,
        ("蓝海", "原始创新", "少有人", "高风险", "探索新", "成熟", "稳妥"),
    )
    contextual_risk_signal = _contains_any(
        answer,
        ("平衡", "兼顾", "适中", "都可以", "不确定", "无所谓"),
    ) and _contains_any(answer, ("创新", "风险", "路线", "方向"))
    if (profile.get("innovation_risk") is None or overwrite) and (
        explicit_risk_signal or contextual_risk_signal
    ):
        profile["innovation_risk"] = _choice_from_answer(
            answer,
            (
                ("balanced", ("平衡", "兼顾", "适中")),
                ("pioneering", ("蓝海", "原始创新", "少有人", "高风险", "探索新")),
                ("mature", ("成熟", "稳妥", "低风险", "确定性")),
                ("undecided", ("不确定", "都可以", "无所谓")),
            ),
        )


def _extract_freeform_corrections(profile: dict[str, Any], answer: str) -> None:
    interest_match = re.search(
        r"(?:研究兴趣|研究方向|兴趣方向).{0,8}(?:改成|改为|是)\s*(.+)",
        answer,
    )
    if interest_match:
        revised = interest_match.group(1).strip()
        tags = _interest_tags(revised)
        if tags:
            profile["research_interests"] = tags
            profile["interest_statement"] = revised

    constraint_match = re.search(
        r"(?:硬性条件|约束条件).{0,8}(?:改成|改为|是)\s*(.+)",
        answer,
    )
    if constraint_match:
        revised = constraint_match.group(1).strip()
        if revised.lower() in _EMPTY_CONSTRAINTS:
            profile["hard_constraints"] = []
            profile["draft_hard_constraints"] = []
            profile["unresolved_hard_constraints"] = []
        else:
            drafts = _draft_constraints(revised)
            profile["hard_constraints"] = []
            profile["draft_hard_constraints"] = [
                draft.model_dump(mode="json") for draft in drafts
            ]
            profile["unresolved_hard_constraints"] = [
                draft.source_text
                for draft in drafts
                if draft.proposed_constraint is None
            ]


def _draft_constraint(source_text: str) -> DraftHardConstraint:
    """把自然语言转成不生效的草案；只做有限、高精度候选解析。"""
    text = source_text.strip()

    department = re.search(
        r"(?:只考虑|仅限|必须是|只能是)\s*(.+?(?:系|学院))$",
        text,
    )
    if department:
        value = department.group(1).strip()
        proposed = HardConstraint(
            field="department",
            operator="one_of",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为院系必须是“{value}”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.95,
            confirmation_prompt=prompt,
        )

    weekly = re.search(
        r"每周.{0,8}?(?:至少|最少|不低于)\s*(\d+(?:\.\d+)?|[一二三四五六七])\s*天",
        text,
    )
    if weekly:
        value = {
            "一": "1",
            "二": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
        }.get(weekly.group(1), weekly.group(1))
        proposed = HardConstraint(
            field="weekly_commitment_days",
            operator="minimum",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为每周至少投入 {value} 天。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.98,
            confirmation_prompt=prompt,
        )

    location = re.search(
        r"(?:地点)?(?:只能|必须|仅限|限定)(?:在|是|选择)?\s*([\u3400-\u9fff]{2,12})$",
        text,
    )
    if location:
        value = location.group(1).strip()
        proposed = HardConstraint(
            field="location",
            operator="one_of",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为地点必须在“{value}”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.98,
            confirmation_prompt=prompt,
        )

    degree = re.search(
        r"(?:只接受|必须是|仅限|只能是)\s*(本科生?|硕士生?|博士生?)",
        text,
    )
    if degree:
        value = degree.group(1)
        proposed = HardConstraint(
            field="degree_stage",
            operator="one_of",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为学历阶段必须是“{value}”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.9,
            confirmation_prompt=prompt,
        )

    language = re.search(
        r"(?:必须|只能|要求).{0,6}?(中文|英语|英文)",
        text,
    )
    if language:
        value = "英语" if language.group(1) == "英文" else language.group(1)
        proposed = HardConstraint(
            field="language",
            operator="one_of",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为必须支持“{value}”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.85,
            confirmation_prompt=prompt,
        )

    if "保密" in text and _contains_any(
        text, ("不能", "不接受", "必须", "可以", "接受")
    ):
        value = (
            "不接受保密要求"
            if _contains_any(text, ("不能", "不接受"))
            else "可接受保密要求"
        )
        proposed = HardConstraint(
            field="confidentiality",
            operator="equals",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为“{value}”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.82,
            confirmation_prompt=prompt,
        )

    if _contains_any(text, ("毕业", "延毕")) and _contains_any(
        text, ("必须", "不能", "不接受", "按时")
    ):
        value = "不接受延毕" if "延毕" in text else "按时毕业"
        proposed = HardConstraint(
            field="graduation_arrangement",
            operator="contains",
            value=[value],
            source_text=text,
        )
        prompt = f"我理解为毕业安排必须满足“{value}”。这是不可妥协条件吗？请回复“确认”或“修改为……”。"
        return DraftHardConstraint(
            source_text=text,
            proposed_constraint=proposed,
            parsing_confidence=0.82,
            confirmation_prompt=prompt,
        )

    if _contains_any(text, ("地点", "城市", "本地")):
        question = f"关于“{text}”，具体必须在哪个城市或地点？如果只是偏好，请回复“不作为硬约束”。"
    elif _contains_any(text, ("每周", "时间", "投入")):
        question = f"关于“{text}”，最低每周必须投入几天？如果只是偏好，请回复“不作为硬约束”。"
    elif _contains_any(text, ("学历", "本科", "硕士", "博士")):
        question = f"关于“{text}”，必须满足哪个学历阶段？如果只是偏好，请回复“不作为硬约束”。"
    elif _contains_any(text, ("语言", "英语", "英文", "中文")):
        question = f"关于“{text}”，必须使用哪种语言？如果只是偏好，请回复“不作为硬约束”。"
    elif "保密" in text:
        question = f"关于“{text}”，你是必须接受还是不能接受保密要求？"
    elif _contains_any(text, ("毕业", "延毕")):
        question = f"关于“{text}”，哪项毕业安排是不可妥协的？"
    else:
        question = f"关于“{text}”，它是不可妥协条件还是一般偏好？若是硬约束，请说明具体必须满足的值。"
    return DraftHardConstraint(
        source_text=text,
        proposed_constraint=None,
        parsing_confidence=0.0,
        confirmation_prompt=question,
    )


# v4.2.2（P1-N）：多分句边界答案中"其他都可以商量/随便/不是约束"等软性
# 分句不产生草案（否则逐条审问，否认还会被引用成约束值，形成死循环）。
_SOFT_CLAUSE_RE = re.compile(
    r"其他.{0,6}(?:都可以|都行|无所谓|随便|商量|再议|再说|先这样|不用|没有|不算|不是)"
    r"|其余|别的|剩下|另外|别的条件|其他条件"
    r"|都可以|都行|无所谓|随便|商量|再议|再说|先这样"
    r"|不是约束|不算约束|不构成约束|只是偏好|仅偏好|一般偏好"
)


def _is_soft_constraint_clause(clause: str) -> bool:
    return (
        _is_constraint_rejection(clause)
        or bool(_SOFT_CLAUSE_RE.search(clause))
        or clause.lower() in _EMPTY_CONSTRAINTS
    )


# v4.2.2（P0-J）：约束澄清环内的结构指令识别。换方向/放宽/确认画像/雷达图/
# 招募/报告/简历/套磁/第N个/改偏好等不是硬约束内容，整句吸收会造成
# "复合指令被引用成约束值、逐条审问"黑洞 → 引导回硬条件环节、不吸收。
_STRUCTURAL_CMD_RE = re.compile(
    r"(?:换方向\s*[:：]?\s*\S+)"
    r"|(?:放宽(?:硬|条件|约束|要求)?)"
    r"|(?:确认\s*画像)"
    r"|(?:雷达图)"
    r"|(?:招募|实习|招生信息|科研助理)"
    r"|(?:匹配报告|生成报告)"
    r"|(?:写简历|做简历|简历优化|简历生成|润色)"
    r"|(?:套磁|写邮件)"
    r"|(?:第\s*[一二两三四五六七八九十\d]+\s*个)"
    r"|(?:改\s*(?:指导|研究|生涯|风险|偏好|画像))"
)


def _contains_structural_command(text: str) -> bool:
    return bool(_STRUCTURAL_CMD_RE.search(text))


def _draft_constraints(answer: str) -> list[DraftHardConstraint]:
    return [
        _draft_constraint(item)
        for item in re.split(r"[，,、；;\n]+", answer)
        if item.strip()
        and not _is_soft_constraint_clause(item.strip())
        and not _contains_structural_command(item.strip())
    ][:12]


def _modify_draft(
    draft: DraftHardConstraint,
    revised: str,
) -> DraftHardConstraint:
    """在已知字段语境内处理“修改为…”，仍需再次中文确认。"""
    proposed = draft.proposed_constraint
    if proposed is not None:
        if proposed.field.value == "location":
            value = revised.strip(" 在")
            return _draft_constraint(f"必须在{value}")
        if proposed.field.value == "weekly_commitment_days":
            number = re.search(r"\d+(?:\.\d+)?", revised)
            if number:
                return _draft_constraint(f"每周至少{number.group(0)}天")
    return _draft_constraint(revised)


def _process_constraint_followup(
    profile: dict[str, Any],
    answer: str,
) -> bool:
    drafts = [
        DraftHardConstraint.model_validate(item)
        for item in profile.get("draft_hard_constraints") or []
    ]
    unresolved = list(profile.get("unresolved_hard_constraints") or [])
    if not drafts and not unresolved:
        return False

    cleaned = answer.strip()
    if drafts:
        current = drafts[0]
        if cleaned in _DRAFT_CONFIRM_SIGNALS:
            if current.proposed_constraint is None:
                # v4.2.x 修复2：无结构化形态的草案无法被"确认"（确认什么？
                # 值未给出）。按"放弃这条低置信草案"处理，避免澄清死循环。
                drafts.pop(0)
                if current.source_text in unresolved:
                    unresolved.remove(current.source_text)
            else:
                confirmed = list(profile.get("hard_constraints") or [])
                # v4.2.2（P0-B 残留）：同一约束重复确认（"确认"×2）不重复入档
                proposed = current.proposed_constraint.model_dump(mode="json")
                duplicate = any(
                    item.get("field") == proposed.get("field")
                    and item.get("operator") == proposed.get("operator")
                    and item.get("value") == proposed.get("value")
                    for item in confirmed
                )
                if not duplicate:
                    confirmed.append(proposed)
                profile["hard_constraints"] = confirmed
                drafts.pop(0)
                if current.source_text in unresolved:
                    unresolved.remove(current.source_text)
        elif _is_constraint_rejection(cleaned):
            drafts.pop(0)
            if current.source_text in unresolved:
                unresolved.remove(current.source_text)
        elif _is_soft_constraint_clause(cleaned):
            # v4.2.2（P1-N）：澄清环中对软性表达的回答（"其他都可以商量"）
            # 视为放弃当前草案，不再生成新的低置信草案（避免逐条审问环）。
            drafts.pop(0)
            if current.source_text in unresolved:
                unresolved.remove(current.source_text)
        else:
            modification = re.match(r"(?:修改为|改为)\s*(.+)", cleaned)
            if modification:
                revised = _modify_draft(current, modification.group(1))
            elif current.proposed_constraint is None:
                revised = _draft_constraint(cleaned)
            else:
                return True
            drafts[0] = revised
            if current.source_text in unresolved:
                unresolved.remove(current.source_text)
            if revised.proposed_constraint is None:
                unresolved.append(revised.source_text)
    else:
        if _is_constraint_rejection(cleaned) or _is_soft_constraint_clause(cleaned):
            # v4.2.2（P1-N）：无结构化草案的澄清环中，软性表达同样丢弃
            # 当前 unresolved（"不是约束，无"不再被引用成约束值）。
            unresolved.pop(0)
        else:
            revised = _draft_constraint(cleaned)
            drafts.append(revised)
            unresolved.pop(0)
            if revised.proposed_constraint is None:
                unresolved.append(revised.source_text)

    profile["draft_hard_constraints"] = [
        draft.model_dump(mode="json") for draft in drafts
    ]
    profile["unresolved_hard_constraints"] = unresolved
    return True


# 选择题关键词映射（单选答案 → 维度值）；与 off_topic 守卫共用同一份词表
# v4.2.2 修复：加宽句子式答案的映射覆盖面（"倾向先深造读研"→academic、
# "放手探索"→autonomous、"平衡，导师给方向我执行"→balanced），让非选项式
# 句子答案降级为选项匹配而非丢弃/判跑题（线上回归问题1）。
_RESEARCH_MODE_KEYWORDS = (
    ("mixed", ("结合", "两者", "兼顾", "都想", "都要", "都做", "都可以")),
    ("theory", ("理论", "原理", "证明", "推导", "基础", "追根究底")),
    ("engineering", ("工程", "落地", "应用", "系统", "做实验", "写代码", "动手", "实现")),
    ("undecided", ("不确定", "没想好", "还没想", "看看", "随便")),
)
_MENTORSHIP_STYLE_KEYWORDS = (
    ("high_guidance", ("手把手", "高频", "具体", "多指导", "多交流", "多沟通", "盯得", "严")),
    ("autonomous", ("自主", "自由", "放养", "少干预", "放手", "独立", "自己")),
    ("balanced", ("平衡", "适度", "结合", "折中", "适中", "一半")),
    ("undecided", ("不确定", "都可以", "无所谓", "没想好", "随便")),
)
_CAREER_ORIENTATION_KEYWORDS = (
    ("national_mission", ("国家", "大国重器", "军工", "航天", "国企", "部队")),
    ("academic", ("学术", "读博", "高校", "研究所", "深造", "读研", "留校", "科研")),
    ("industry", ("产业", "就业", "大厂", "创业", "上班", "进公司", "挣钱")),
    ("mixed", ("混合", "兼顾", "都想", "都要", "先保留")),
    ("undecided", ("不确定", "都可以", "无所谓", "没想好", "随便")),
)
_INNOVATION_RISK_KEYWORDS = (
    ("balanced", ("平衡", "兼顾", "适中", "折中")),
    ("pioneering", ("蓝海", "新方向", "少有人", "高风险", "探索", "冒险", "大胆", "闯")),
    ("mature", ("成熟", "稳妥", "低风险", "确定", "保守", "保险", "稳")),
    ("undecided", ("不确定", "都可以", "无所谓", "没想好", "随便")),
)


def _apply_target_answer(
    profile: dict[str, Any],
    dimension: InterviewDimension,
    answer: str,
) -> None:
    if dimension == InterviewDimension.RESEARCH_INTERESTS:
        tags = _interest_tags(answer)
        if tags:
            profile["research_interests"] = tags
            profile["interest_statement"] = answer.strip()
        elif _is_interest_decline(answer):
            # v4.2.2（P1-K②/P2-L）：研究兴趣题的整体拒绝/无方向表达
            # （"无""没想好""都可以"…）→ 标记"暂无明确方向"并推进状态机，
            # 不回声环（否则"无"会被无限重问同一题）。
            profile["research_interests"] = []
            profile["interest_statement"] = "暂无明确方向"
        return
    if dimension == InterviewDimension.RESEARCH_MODE:
        profile["research_mode"] = _choice_from_answer(
            answer,
            _RESEARCH_MODE_KEYWORDS,
        )
        return
    if dimension == InterviewDimension.MENTORSHIP_STYLE:
        profile["mentorship_style"] = _choice_from_answer(
            answer,
            _MENTORSHIP_STYLE_KEYWORDS,
        )
        return
    if dimension == InterviewDimension.CAREER_ORIENTATION:
        profile["career_orientation"] = _choice_from_answer(
            answer,
            _CAREER_ORIENTATION_KEYWORDS,
        )
        return
    if dimension == InterviewDimension.INNOVATION_RISK:
        profile["innovation_risk"] = _choice_from_answer(
            answer,
            _INNOVATION_RISK_KEYWORDS,
        )
        return
    if dimension == InterviewDimension.HARD_CONSTRAINTS:
        stripped = answer.strip()
        # v4.2.x 修复1/2：负向表达/确认指令/态度词 → 视为"无硬约束"，
        # 整体清空（含已确认项按计划语义处理，澄清环内走短路分支保留已确认项）
        if (
            stripped.lower() in _EMPTY_CONSTRAINTS
            or _is_constraint_rejection(stripped)
        ):
            profile["hard_constraints"] = []
            profile["draft_hard_constraints"] = []
            profile["unresolved_hard_constraints"] = []
        else:
            drafts = _draft_constraints(stripped)
            profile["hard_constraints"] = []
            profile["draft_hard_constraints"] = [
                draft.model_dump(mode="json") for draft in drafts
            ]
            profile["unresolved_hard_constraints"] = [
                draft.source_text
                for draft in drafts
                if draft.proposed_constraint is None
            ]


_VALUE_LABELS = {
    "theory": "理论与原理",
    "engineering": "工程与落地",
    "mixed": "混合/兼顾",
    "undecided": "暂不确定",
    "high_guidance": "高频具体指导",
    "balanced": "平衡",
    "autonomous": "自主探索",
    "academic": "学术深造",
    "industry": "产业就业",
    "national_mission": "国家任务",
    "pioneering": "高风险新方向",
    "mature": "成熟路径",
}

_CONSTRAINT_FIELD_LABELS = {
    "location": "地点",
    "weekly_commitment_days": "每周投入天数",
    "degree_stage": "学历阶段",
    "language": "语言",
    "confidentiality": "保密要求",
    "graduation_arrangement": "毕业安排",
    "department": "院系",
    "research_topic": "研究主题",
    "advisor_id": "导师",
}
_CONSTRAINT_OPERATOR_LABELS = {
    "equals": "必须等于",
    "one_of": "必须属于",
    "excludes": "必须排除",
    "contains": "必须包含",
    "minimum": "至少",
    "maximum": "至多",
}


def _constraint_label(constraint: HardConstraint) -> str:
    return (
        f"{_CONSTRAINT_FIELD_LABELS[constraint.field.value]}"
        f"{_CONSTRAINT_OPERATOR_LABELS[constraint.operator.value]}"
        f"{' / '.join(constraint.value)}"
    )


def _summary(profile: StudentPortrait) -> str:
    constraints = "；".join(
        _constraint_label(constraint)
        for constraint in profile.hard_constraints or []
    ) or "无已确认的结构化条件"
    focus: list[str] = []
    if profile.research_interests:
        focus.append(f"研究方向：{'、'.join(profile.research_interests)}")
    if profile.research_mode:
        focus.append(f"研究方式：{_VALUE_LABELS.get(profile.research_mode, profile.research_mode)}")
    if profile.career_orientation:
        focus.append(f"生涯方向：{_VALUE_LABELS.get(profile.career_orientation, profile.career_orientation)}")
    if profile.mentorship_style:
        focus.append(f"指导偏好：{_VALUE_LABELS.get(profile.mentorship_style, profile.mentorship_style)}")
    if profile.hard_constraints:
        focus.append(f"硬性条件：{constraints}")
    focus_line = "；".join(focus) if focus else "暂无已确认信息，先匹配会较宽泛"
    open_items = [
        draft.confirmation_prompt
        for draft in profile.draft_hard_constraints or []
    ]
    open_items.extend(
        item
        for item in profile.unresolved_hard_constraints or []
        if item not in {d.source_text for d in profile.draft_hard_constraints or []}
    )
    if profile.research_mode is None:
        open_items.append("研究方式（理论/工程/混合）")
    if profile.career_orientation is None:
        open_items.append("生涯方向（学术深造/产业就业）")
    open_line = (
        "；".join(open_items[:5]) + (" 等" if len(open_items) > 5 else "")
        if open_items
        else "无"
    )
    return (
        "好，我们已经把选择线索拼成了一版可编辑画像：\n"
        f"- 研究兴趣：{'、'.join(profile.research_interests)}\n"
        f"- 研究方式：{_VALUE_LABELS.get(profile.research_mode or '', '暂不确定')}\n"
        f"- 指导偏好：{_VALUE_LABELS.get(profile.mentorship_style or '', '暂不确定')}\n"
        f"- 生涯方向：{_VALUE_LABELS.get(profile.career_orientation or '', '暂不确定')}\n"
        f"- 创新风险：{_VALUE_LABELS.get(profile.innovation_risk or '', '暂不确定')}\n"
        f"- 已确认硬性条件：{constraints}\n\n"
        f"**匹配时将重点考虑**：{focus_line}\n"
        f"**尚未明确（可选补充）**：{open_line}\n\n"
        "看看是否像你？需要调整就直接说；确认无误请回复“确认画像”，我们再开始匹配。"
    )


def clarification_questions(profile: StudentPortrait) -> list[str]:
    questions = [
        draft.confirmation_prompt
        for draft in profile.draft_hard_constraints
    ]
    questions.extend(
        f"关于“{item}”，请说明哪一项具体条件是不可妥协的。"
        for item in profile.unresolved_hard_constraints or []
        if item
        not in {
            draft.source_text for draft in profile.draft_hard_constraints
        }
    )
    return questions


def get_session(
    db: Session,
    session_id: str,
    student_id: str | None,
) -> QuestionnaireSession:
    session = db.get(QuestionnaireSession, session_id)
    if session is None:
        raise InterviewNotFoundError("访谈会话不存在")
    if student_id is None or session.student_id != student_id:
        raise InterviewAccessError("无权访问该访谈会话")
    return session


def create_session(
    db: Session,
    *,
    student_id: str | None,
    session_id: str | None = None,
) -> QuestionnaireSession:
    resolved_id = session_id or str(uuid.uuid4())
    existing = db.get(QuestionnaireSession, resolved_id)
    if existing is not None:
        if student_id is None or existing.student_id != student_id:
            raise InterviewAccessError("无权访问该访谈会话")
        return existing

    first_question = QUESTION_BANK[InterviewDimension.RESEARCH_INTERESTS]
    session = QuestionnaireSession(
        session_id=resolved_id,
        student_id=student_id,
        messages=[_message("assistant", first_question.prompt)],
        portrait=StudentPortrait().model_dump(mode="json"),
        status=InterviewStatus.IN_PROGRESS.value,
        current_question_id=first_question.question_id,
        answered_dimensions=[],
        profile_version=1,
        confirmed_at=None,
        updated_at=_now(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _set_state_after_profile_change(
    session: QuestionnaireSession,
    profile: StudentPortrait,
) -> str:
    next_question = _next_question(profile)
    if next_question is None:
        session.status = InterviewStatus.AWAITING_CONFIRMATION.value
        session.current_question_id = None
        session.confirmed_at = None
        return _summary(profile)
    session.status = InterviewStatus.IN_PROGRESS.value
    session.current_question_id = next_question.question_id
    session.confirmed_at = None
    return next_question.prompt


_OFF_TOPIC_NUDGE = (
    "刚才这句好像和导师匹配的话题有点远，我担心会记错你的想法，"
    "所以先不写入画像～\n\n我们还是继续刚才的问题："
)
_CLARIFY_STALL_NOTE = (
    "这几轮澄清没有收敛到可确认的硬性条件，我先不再追问："
    "已确认的保留，其余按“无硬性条件”处理。可随时在画像卡里补充或修改。\n\n"
)


def _constraint_clarify_stall(messages: list[dict[str, str]]) -> bool:
    """v4.2.x 修复2：同一澄清提问连续出现 3 次（本轮将复述第 4 次）→ 卡死。"""
    assistant_texts = [
        message.get("content") or ""
        for message in reversed(messages)
        if message.get("role") == "assistant"
    ][:3]
    return len(assistant_texts) == 3 and len(set(assistant_texts)) == 1


def _last_assistant_text(messages: list[dict[str, str]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return message.get("content") or ""
    return None


def _off_topic_reply(
    current_dimension: InterviewDimension,
    answer: str,
    messages: list[dict[str, str]],
) -> str | None:
    """跑题检测（v4.0.0）：命中返回温和重问文案，未命中返回 None 放行。

    只在"当前题"上下文生效；已确认/待确认状态（current_question_id 为空）
    不会走到这里，自由文本修正照旧。
    """
    if current_dimension == InterviewDimension.RESEARCH_INTERESTS:
        if not off_topic.detect_off_topic_interests(answer):
            return None
    elif current_dimension == InterviewDimension.RESEARCH_MODE:
        if not off_topic.detect_off_topic_choice(
            answer, tuple(k for _, kws in _RESEARCH_MODE_KEYWORDS for k in kws)
        ):
            return None
    elif current_dimension == InterviewDimension.MENTORSHIP_STYLE:
        if not off_topic.detect_off_topic_choice(
            answer, tuple(k for _, kws in _MENTORSHIP_STYLE_KEYWORDS for k in kws)
        ):
            return None
    elif current_dimension == InterviewDimension.CAREER_ORIENTATION:
        if not off_topic.detect_off_topic_choice(
            answer, tuple(k for _, kws in _CAREER_ORIENTATION_KEYWORDS for k in kws)
        ):
            return None
    elif current_dimension == InterviewDimension.INNOVATION_RISK:
        if not off_topic.detect_off_topic_choice(
            answer, tuple(k for _, kws in _INNOVATION_RISK_KEYWORDS for k in kws)
        ):
            return None
    elif current_dimension == InterviewDimension.HARD_CONSTRAINTS:
        if not off_topic.detect_off_topic_constraints(answer):
            return None
    else:
        return None
    last_question = _last_assistant_text(messages) or ""
    return f"{_OFF_TOPIC_NUDGE}{last_question}"


def answer_session(
    db: Session,
    *,
    session_id: str,
    answer: str,
    student_id: str | None,
) -> QuestionnaireSession:
    session = get_session(db, session_id, student_id)
    cleaned_answer = answer.strip()
    messages = list(session.messages or [])
    profile = _portrait(session)

    if (
        session.status == InterviewStatus.CONFIRMED.value
        and cleaned_answer in _CONFIRM_SIGNALS
    ):
        reply = "这版画像已经确认啦，不需要重复操作。"
        messages.extend([_message("user", cleaned_answer), _message("assistant", reply)])
        session.messages = messages
        session.updated_at = _now()
        db.commit()
        db.refresh(session)
        return session

    if (
        session.status == InterviewStatus.AWAITING_CONFIRMATION.value
        and cleaned_answer in _CONFIRM_SIGNALS
    ):
        if _missing_dimensions(profile):
            raise InterviewConflictError("画像仍有未完成字段，不能确认")
        if (
            profile.draft_hard_constraints
            or profile.unresolved_hard_constraints
        ):
            reply = (
                "还有自然语言硬约束尚未由你确认成结构化条件，暂不能匹配。\n"
                + "\n".join(clarification_questions(profile))
            )
            messages.extend(
                [_message("user", cleaned_answer), _message("assistant", reply)]
            )
            session.messages = messages
            session.updated_at = _now()
            db.commit()
            db.refresh(session)
            return session
        reply = "画像已确认，接下来会基于这份信息开始匹配。"
        messages.extend([_message("user", cleaned_answer), _message("assistant", reply)])
        session.status = InterviewStatus.CONFIRMED.value
        session.current_question_id = None
        session.confirmed_at = _now()
        session.profile_version = int(session.profile_version or 1) + 1
        session.messages = messages
        session.updated_at = _now()
        # v4.0.0 长期记忆：确认门通过后写入白名单事实（仅六维+硬条件+标记）
        remember_confirmed_portrait(
            db,
            student_id=session.student_id,
            portrait=profile.model_dump(mode="json"),
        )
        db.commit()
        db.refresh(session)
        return session

    # v4.2.x 修复1+3：硬约束澄清环中"确认画像"短路 —— 视为"不再补充硬性
    # 条件"：保留已确认项、丢弃悬空草案，边界直接闭合出总览卡（回声环
    # 就此终止，下一条"确认画像"走上方待确认分支完成确认）。
    if (
        session.current_question_id == InterviewDimension.HARD_CONSTRAINTS.value
        and cleaned_answer in _CONFIRM_SIGNALS
    ):
        profile.draft_hard_constraints = []
        profile.unresolved_hard_constraints = []
        profile.hard_constraints = list(profile.hard_constraints or [])
        updated_profile = StudentPortrait.model_validate(profile)
        reply = _set_state_after_profile_change(session, updated_profile)
        session.profile_version = int(session.profile_version or 1) + 1
        messages.extend(
            [_message("user", cleaned_answer), _message("assistant", reply)]
        )
        session.messages = messages
        session.portrait = updated_profile.model_dump(mode="json")
        session.answered_dimensions = [
            dimension.value
            for dimension in _completed_dimensions(updated_profile)
        ]
        session.updated_at = _now()
        db.commit()
        db.refresh(session)
        return session

    profile_data = profile.model_dump(mode="json")
    before = dict(profile_data)
    current_dimension = (
        InterviewDimension(session.current_question_id)
        if session.current_question_id
        else None
    )

    # v4.2.2（P0-J）：约束澄清环内的结构/复合指令（"换个方向看电池安全，
    # 顺便改指导偏好"）不是硬约束内容，整句吸收会生成低置信草案并逐条
    # 审问（黑洞）。只引导回硬条件环节，不吸收、不丢已确认的悬空进度。
    if (
        current_dimension == InterviewDimension.HARD_CONSTRAINTS
        and _contains_structural_command(cleaned_answer)
    ):
        updated_profile = StudentPortrait.model_validate(profile_data)
        question_reply = _set_state_after_profile_change(
            session, updated_profile
        )
        reply = (
            "这条消息里有「换方向 / 放宽 / 调整偏好」等操作指令，我先不把它"
            "并进硬性条件里。换方向、放宽等操作可以在确认画像、看到匹配"
            "结果后执行；现在请先完成硬约束确认（可直接回复「无」跳过）。"
            f"\n\n{question_reply}"
        )
        session.profile_version = int(session.profile_version or 1) + 1
        messages.extend(
            [_message("user", cleaned_answer), _message("assistant", reply)]
        )
        session.messages = messages
        session.portrait = updated_profile.model_dump(mode="json")
        session.answered_dimensions = [
            dimension.value
            for dimension in _completed_dimensions(updated_profile)
        ]
        session.updated_at = _now()
        db.commit()
        db.refresh(session)
        return session

    handled_constraint_followup = (
        current_dimension == InterviewDimension.HARD_CONSTRAINTS
        and _process_constraint_followup(profile_data, cleaned_answer)
    )
    if not handled_constraint_followup and current_dimension is not None:
        # v4.0.0 防吸收守卫：跑题文本温和重问，不写入画像
        off_topic_reply = _off_topic_reply(
            current_dimension, cleaned_answer, messages
        )
        if off_topic_reply is not None:
            messages.extend(
                [
                    _message("user", cleaned_answer),
                    _message("assistant", off_topic_reply),
                ]
            )
            session.messages = messages
            session.updated_at = _now()
            db.commit()
            db.refresh(session)
            return session
        _apply_target_answer(profile_data, current_dimension, cleaned_answer)
    overwrite = (
        current_dimension is None
        and session.status
        in {
            InterviewStatus.AWAITING_CONFIRMATION.value,
            InterviewStatus.CONFIRMED.value,
        }
    )
    _extract_categorical_signals(
        profile_data,
        cleaned_answer,
        overwrite=overwrite,
    )
    if overwrite:
        _extract_freeform_corrections(profile_data, cleaned_answer)
    updated_profile = StudentPortrait.model_validate(profile_data)

    # v4.2.x 修复2 轮次硬限制：硬约束澄清环同一提问连续 3 次无进展 →
    # 丢弃悬空草案、保留已确认项，强制闭合边界（总览卡直出，不再复读）。
    stalled_closure = (
        current_dimension == InterviewDimension.HARD_CONSTRAINTS
        and handled_constraint_followup
        and (
            updated_profile.draft_hard_constraints
            or updated_profile.unresolved_hard_constraints
        )
        and _constraint_clarify_stall(messages)
    )
    if stalled_closure:
        profile_data["draft_hard_constraints"] = []
        profile_data["unresolved_hard_constraints"] = []
        updated_profile = StudentPortrait.model_validate(profile_data)

    if session.status == InterviewStatus.CONFIRMED.value and before == profile_data:
        reply = (
            "画像已确认。如需修改，请明确说明要改的偏好，"
            "或在网页画像卡中编辑后重新确认。"
        )
    else:
        reply = _set_state_after_profile_change(session, updated_profile)
        if stalled_closure:
            reply = _CLARIFY_STALL_NOTE + reply
        session.profile_version = int(session.profile_version or 1) + 1

    messages.extend([_message("user", cleaned_answer), _message("assistant", reply)])
    session.messages = messages
    session.portrait = updated_profile.model_dump(mode="json")
    session.answered_dimensions = [
        dimension.value for dimension in _completed_dimensions(updated_profile)
    ]
    session.updated_at = _now()
    db.commit()
    db.refresh(session)
    return session


def patch_profile(
    db: Session,
    *,
    session_id: str,
    patch: StudentPortraitPatch,
    student_id: str | None,
) -> QuestionnaireSession:
    session = get_session(db, session_id, student_id)
    if int(session.profile_version or 1) != patch.expected_version:
        raise InterviewConflictError("画像版本已变化，请刷新后重试")

    data = _portrait(session).model_dump(mode="json")
    changes = patch.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if "research_interests" in changes and changes["research_interests"] is None:
        changes["research_interests"] = []
    data.update(changes)
    profile = StudentPortrait.model_validate(data)
    reply = _set_state_after_profile_change(session, profile)
    session.portrait = profile.model_dump(mode="json")
    session.answered_dimensions = [
        dimension.value for dimension in _completed_dimensions(profile)
    ]
    session.profile_version = int(session.profile_version or 1) + 1
    session.messages = list(session.messages or []) + [_message("assistant", reply)]
    session.updated_at = _now()
    db.commit()
    db.refresh(session)
    return session


def upsert_portrait_field(
    db: Session,
    *,
    session_id: str,
    student_id: str | None,
    changes: dict[str, Any],
) -> QuestionnaireSession:
    """对话端口专用：把单字段写回画像（无版本冲突检查，内部自增版本）。

    语义与 patch_profile 一致：画像变化后状态回落 awaiting_confirmation
    （已确认画像需重新确认），确认门与诚实红线不受影响。v3.1.6 供
    科研风格速测「确认」回填 research_mode、方向地图选方向回填
    research_interests 使用。
    research_interests 为合并去重语义（保留既有值，追加新标签，上限 8）；
    原 interest_statement 为空时按合并后的兴趣自动补一句，忠实于用户所选。
    """
    session = create_session(db, student_id=student_id, session_id=session_id)
    data = _portrait(session).model_dump(mode="json")
    if "research_interests" in changes:
        existing = list(data.get("research_interests") or [])
        merged = list(existing)
        for tag in changes["research_interests"] or []:
            tag = (tag or "").strip()
            if tag and tag not in merged:
                merged.append(tag)
        merged = merged[:8]
        changes = {**changes, "research_interests": merged}
        if not data.get("interest_statement"):
            changes["interest_statement"] = f"我对{'、'.join(merged)}方向感兴趣。"
    data.update(changes)
    profile = StudentPortrait.model_validate(data)
    reply = _set_state_after_profile_change(session, profile)
    session.portrait = profile.model_dump(mode="json")
    session.answered_dimensions = [
        dimension.value for dimension in _completed_dimensions(profile)
    ]
    session.profile_version = int(session.profile_version or 1) + 1
    session.messages = list(session.messages or []) + [_message("assistant", reply)]
    session.updated_at = _now()
    db.commit()
    db.refresh(session)
    return session


def confirm_profile(
    db: Session,
    *,
    session_id: str,
    expected_version: int,
    student_id: str | None,
) -> QuestionnaireSession:
    session = get_session(db, session_id, student_id)
    if int(session.profile_version or 1) != expected_version:
        raise InterviewConflictError("画像版本已变化，请刷新后重试")
    profile = _portrait(session)
    if profile.draft_hard_constraints or profile.unresolved_hard_constraints:
        raise InterviewConflictError(
            "硬约束仍需澄清：" + "；".join(clarification_questions(profile))
        )
    missing = _missing_dimensions(profile)
    if missing:
        raise InterviewConflictError(
            f"画像尚未完成：{', '.join(item.value for item in missing)}"
        )
    reply = "画像已确认，接下来会基于这份信息开始匹配。"
    session.status = InterviewStatus.CONFIRMED.value
    session.current_question_id = None
    session.confirmed_at = _now()
    session.profile_version = int(session.profile_version or 1) + 1
    session.messages = list(session.messages or []) + [_message("assistant", reply)]
    session.updated_at = _now()
    # v4.0.0 长期记忆：Web 画像卡确认同样只写白名单事实
    remember_confirmed_portrait(
        db,
        student_id=session.student_id,
        portrait=profile.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(session)
    return session


def state_response(session: QuestionnaireSession) -> InterviewStateResponse:
    profile = _portrait(session)
    completed = _completed_dimensions(profile)
    missing = _missing_dimensions(profile)
    question = (
        QUESTION_BANK[InterviewDimension(session.current_question_id)]
        if session.current_question_id
        else None
    )
    messages = list(session.messages or [])
    assistant_message = next(
        (
            item.get("content", "")
            for item in reversed(messages)
            if item.get("role") == "assistant"
        ),
        question.prompt if question else "",
    )
    status = InterviewStatus(session.status)
    return InterviewStateResponse(
        session_id=session.session_id,
        status=status,
        profile=profile,
        profile_version=int(session.profile_version or 1),
        current_question=question,
        completed_dimensions=completed,
        missing_dimensions=missing,
        needs_confirmation=status == InterviewStatus.AWAITING_CONFIRMATION,
        needs_clarification=bool(
            profile.draft_hard_constraints
            or profile.unresolved_hard_constraints
        ),
        clarification_questions=clarification_questions(profile),
        recommend_ready=(
            status == InterviewStatus.CONFIRMED
            and not profile.draft_hard_constraints
            and not profile.unresolved_hard_constraints
        ),
        assistant_message=assistant_message,
        messages=messages,
    )


def sync_user_transcript(
    db: Session,
    *,
    session_id: str,
    student_id: str | None,
    user_messages: list[str],
) -> QuestionnaireSession:
    """将客户端携带的完整 user 历史增量同步到持久会话。"""
    session = create_session(db, student_id=student_id, session_id=session_id)
    persisted_user_turns = sum(
        1 for item in (session.messages or []) if item.get("role") == "user"
    )
    for answer in user_messages[persisted_user_turns:]:
        session = answer_session(
            db,
            session_id=session_id,
            answer=answer,
            student_id=student_id,
        )
    return session


def confirmed_portrait(
    db: Session,
    *,
    session_id: str,
    student_id: str | None,
) -> StudentPortrait:
    session = get_session(db, session_id, student_id)
    if (
        session.status != InterviewStatus.CONFIRMED.value
        or session.confirmed_at is None
    ):
        raise InterviewConflictError("匹配前必须完成并确认学生画像")
    return _portrait(session)
