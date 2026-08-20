"""v2.5 咨询模块：套磁邮件（确定性模板 + LLM 增强）+ FAQ 咨询。

设计约定：
- 套磁邮件：确定性模板兜底（基于用户画像中的研究兴趣，不编造导师方向）；
  LLM 增强失败或未配置凭据时降级回模板，绝不阻断；诚实提示联系方式
  与导师具体信息以官网为准；
- FAQ：平台机制类问题给确定性答案；涉及导师个体情况（组会/延毕/招生
  名额/学生评价/实验室氛围）且知识库无收录数据时，明确"该信息暂未收录，
  建议通过官方邮箱联系导师确认"，绝不编造。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings
from app.schemas.advisor import LLMMessage
from app.schemas.interview import StudentPortrait
from app.services.llm import _llm_complete_result

# —— 平台机制类 FAQ：确定性答案（不涉及任何导师个体数据）——
_PLATFORM_FAQ: tuple[tuple[str, str], ...] = (
    (
        "怎么匹配",
        "匹配流程：先通过访谈确认你的画像（研究兴趣、科研模式、指导偏好、"
        "硬约束等）；画像确认后由服务端运行唯一一套证据化匹配。结果全部"
        "基于公开可查数据与已审核证据，不会编造评分或名额。",
    ),
    (
        "如何开始",
        "直接告诉我你的研究兴趣、想做的方向与硬性条件（如必须能按时毕业、"
        "需要经费充足的课题组等）即可开始。",
    ),
    (
        "雷达图",
        "雷达图展示导师的已审核客观四维证据：项目广度、主题广度、联系"
        "完备度、材料完备度，满分 100；评分门未开放时不会用推断值冒充，"
        "只会诚实说明暂无已审核证据。",
    ),
    (
        "怎么投递",
        "招募发布与投递记录只在网站内管理 👉 "
        "https://www.tsingradar.com.cn/recruitment；聊天内只做信息推荐，"
        "不收集简历。",
    ),
    (
        "投递流程",
        "同上：网站的招募模块负责发布、审核与投递记录管理；聊天内不做"
        "投递动作。",
    ),
    (
        "简历",
        "简历功能支持三种方式：① 从零生成（回复「帮我写简历」分步采集）；"
        "② 优化已有简历（粘贴简历原文，我会整理表述与结构）；③ 定向优化"
        "（告诉我目标导师或岗位，我帮你突出与岗位要求的匹配点）。只整理"
        "你提供的信息，不会虚构经历。",
    ),
    (
        "怎么选导师",
        "可以从三个维度考虑：① 研究方向重合度（看导师已审核的公开成果与"
        "你的兴趣）；② 你的硬约束（毕业节奏、经费、指导方式等）；③ 客观"
        "证据质量（有独立审核评分时看四维雷达）。我可以帮你做证据化匹配，"
        "但最终决策请结合自身情况综合判断。",
    ),
)

# 命中这些主题的 FAQ 属于"导师个体情况"，本地无收录时必须诚实告知
_INDIVIDUAL_FAQ_TERMS = (
    "组会",
    "延毕",
    "毕业难度",
    "招生名额",
    "学生评价",
    "风评",
    "口碑",
    "实验室氛围",
    "老师怎么样",
    "导师怎么样",
    "人怎么样",
    "好不好",
)

_NOT_COLLECTED_TEMPLATE = (
    "「{topic}」这类信息属于导师个体情况，当前知识库暂未收录经过核实的"
    "公开数据，我不能编造或凭印象作答。\n\n"
    "建议通过导师官网或官方邮箱直接确认；也可以查看该导师的公开成果与"
    "已审核的客观证据来辅助判断。"
)

# —— 套磁邮件 ——
_EMAIL_SYSTEM_PROMPT = (
    "你是清华大学学生的学术套磁信助手。只整理用户提供的信息，不得虚构"
    "导师的研究方向、成果或用户的经历。输出 JSON："
    "{\"subject\": \"邮件主题\", \"body\": \"邮件正文\"}。正文保持礼貌、"
    "简洁、具体，突出用户与研究方向的真实重合点；如用户未提供导师姓名，"
    "用「X老师」占位。"
)

_EMAIL_USER_PROMPT = (
    "用户需求：{request}\n"
    "用户画像中的研究兴趣：{interests}\n"
    "用户背景要点：{background}\n"
    "请生成一封套磁邮件初稿。"
)


def _parse_email_request(latest_user: str) -> dict[str, str]:
    """从消息中提取目标导师名（姓名 ≤ 6 字，去掉邮件套语）。"""
    text = (latest_user or "").strip()
    for marker in ("写给", "给", "联系", "套磁"):
        if marker not in text:
            continue
        remainder = text.split(marker, 1)[1]
        remainder = re.split(r"[，。！？\n]|老师|教授|导师", remainder, 1)[0]
        remainder = remainder.strip(" 的、“”\"'《》（）()")
        # 中文姓氏可单字（如"王"）；含"写/封/发"等套语时不视为姓名
        if (
            remainder
            and len(remainder) <= 6
            and not any(ch in remainder for ch in "写封发弄做请帮忙")
        ):
            return {"advisor_name": remainder}
    return {}


def _interests_text(portrait: StudentPortrait | None) -> str:
    interests = list(getattr(portrait, "research_interests", None) or [])
    return "、".join(interests) if interests else "（未提供，请用占位符）"


def _background_text(portrait: StudentPortrait | None) -> str:
    if portrait is None:
        return "（未提供）"
    parts: list[str] = []
    mode = getattr(portrait, "research_mode", None)
    if mode:
        parts.append(f"科研模式偏好：{mode}")
    career = getattr(portrait, "career_orientation", None)
    if career:
        parts.append(f"职业取向：{career}")
    statement = getattr(portrait, "interest_statement", None)
    if statement:
        parts.append(f"兴趣自述：{statement}")
    return "；".join(parts) if parts else "（未提供）"


def deterministic_email_draft(
    *,
    request: str,
    portrait: StudentPortrait | None,
) -> tuple[str, str]:
    """确定性套磁模板兜底；所有导师/学生细节均以占位符或用户提供为准。"""
    parsed = _parse_email_request(request)
    advisor = parsed.get("advisor_name") or "X老师"
    if not any(advisor.endswith(suffix) for suffix in ("老师", "教授", "导师")):
        advisor = f"{advisor}老师"
    interests = _interests_text(portrait)
    subject = f"关于加入{advisor}课题组的研究申请"
    lines = [
        f"{advisor}，您好！",
        "",
        f"我是清华大学的一名学生，对{interests}方向有持续的兴趣，"
        "看到您在相关领域的工作，希望能进一步了解您课题组的研究安排。",
        "",
        "【我的基本情况】",
        "- 研究兴趣：{}".format(interests),
        "- 相关经历：（请补充你与该方向相关的课程、项目或论文）",
        "",
        "【想请教的问题】",
        "- 课题组当前是否有招收计划；",
        "- 如有机会，是否可以约一次简要交流。",
        "",
        "非常感谢您的时间，盼复。",
        "",
        "此致\n敬礼\n（你的姓名）\n（联系方式，以官网或校内通讯录为准）",
    ]
    return subject, "\n".join(lines)


async def _llm_email_draft(
    *,
    request: str,
    portrait: StudentPortrait | None,
) -> dict | None:
    """LLM 增强套磁初稿；任何失败返回 None（降级确定性模板）。"""
    if not settings.llm_credentials:
        return None

    result = await _llm_complete_result(
        [
            LLMMessage(role="system", content=_EMAIL_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=_EMAIL_USER_PROMPT.format(
                    request=(request or "")[:800],
                    interests=_interests_text(portrait),
                    background=_background_text(portrait),
                ),
            ),
        ],
        timeout_seconds=settings.LLM_TIMEOUT,
    )
    if result is None:
        return None
    raw = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", result.text.strip(), flags=re.MULTILINE
    ).strip()
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not subject or not body or len(body) > 3000:
        return None
    return {"subject": subject, "body": body}


async def handle_consult_email(
    *,
    latest_user: str,
    portrait: StudentPortrait | None = None,
) -> tuple[str, Any]:
    """套磁邮件入口：LLM 增强，失败降级确定性模板（fail-closed）。"""
    subject, body = deterministic_email_draft(
        request=latest_user, portrait=portrait
    )
    llm_draft = await _llm_email_draft(request=latest_user, portrait=portrait)
    if llm_draft is not None:
        subject, body = llm_draft["subject"], llm_draft["body"]
        source_note = "（初稿由文本模型润色；请核对事实后再发送）"
    else:
        source_note = "（确定性模板初稿，未使用文本模型）"
    return (
        f"套磁信初稿{source_note}：\n\n"
        f"主题：{subject}\n\n{body}\n\n"
        "提示：导师的招生名额、联系方式与近期安排以官网或官方邮箱为准，"
        "初稿中的占位信息请发送前自行核实。",
        None,
    )


async def handle_consult_faq(
    *,
    latest_user: str,
    portrait: StudentPortrait | None = None,
) -> tuple[str, Any]:
    """FAQ 咨询入口：平台机制确定性答案；个体情况诚实"未收录"。"""
    text = (latest_user or "").strip()
    for topic, answer in _PLATFORM_FAQ:
        if topic in text:
            return answer, None
    if any(term in text for term in _INDIVIDUAL_FAQ_TERMS):
        # 提取被问的主题词（取消息中最长的命中词，输出更贴切）
        hits = [term for term in _INDIVIDUAL_FAQ_TERMS if term in text]
        topic = max(hits, key=len) if hits else "相关情况"
        return _NOT_COLLECTED_TEMPLATE.format(topic=topic), None
    return (
        "我目前可以回答平台机制类问题（如何匹配、投递流程、雷达图等）"
        "以及套磁邮件撰写；导师个体的组会节奏、招生名额、学生评价等信息"
        "若知识库未收录，我会如实说明，不会编造。",
        None,
    )
