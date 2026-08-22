"""v2.5 简历对话模块：从零生成 / 优化已有 / 定向优化。

设计约定：
- 从零生成：分步采集（dialogue_sessions 持久化），支持智能预填——触发
  消息或任一采集轮里一次性给出的信息，由 LLM（fail-closed）或确定性
  锚点抽取为字段，只问缺失项；采集完成输出结构化 Markdown 简历；可经
  确认后复用确定性 create_resume_artifact 交付 PDF（仅持久主体，非持久
  主体诚实提示走纯文本）；
- 优化已有：用户粘贴原文 → LLM 润色（学术表述 / 经历量化 / 逻辑结构
  三维度 + 3-5 条修改说明），输出校验闸门失败或未配置凭据时降级为
  确定性规范化（分点整理、量化提示），绝不阻断对话；
- 定向优化：解析目标导师 / 岗位关键词，调整各经历表述权重突出匹配点；
- 诚实性：只整理用户提供的信息，不补写虚构经历；LLM 产物在交付
  generation_context 中标注 external_model_used（由 artifact 管线记录）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.advisor import LLMMessage
from app.schemas.interview import StudentPortrait
from app.schemas.qxd import SodaAttachment
from app.services.artifact_delivery import assert_qxd_delivery_ready
from app.services.dialogue_intent import (
    RESUME_CANCEL_TERMS,
    RESUME_DONE_TERMS,
)
from app.services.dialogue_state_store import (
    clear_dialogue_state,
    get_dialogue_mode,
    get_dialogue_state,
    upsert_dialogue_state,
)
from app.services.identity import Principal
from app.services.llm import _llm_complete_result
from app.services.recruitment_dialogue import resolve_recruitment_target

logger = logging.getLogger(__name__)

MODE_RESUME_BUILD = "resume_build"
MODE_RESUME_POLISH = "resume_polish"
MODE_RESUME_TARGETED = "resume_targeted"

# 投递确认口令（与报告交付确认同一交互风格）
RESUME_DELIVERY_CONFIRMATION = "确认生成简历文件"

MAX_POLISH_TEXT = 6000
MAX_POLISH_OUTPUT = 6000

# 分步采集序列：(字段键, 引导语)。对齐 ResumeArtifactRequest 字段口径。
FIELD_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("student_name", "第一步：你的姓名是？"),
    ("dept", "你所在的院系和专业是？（如：计算机科学与技术系 · 软件工程）"),
    (
        "education",
        "教育背景：请告诉我年级、GPA（可选）和核心课程（如：大三 · 3.8/4.0 · 数据结构、机器学习）。",
    ),
    (
        "projects",
        "科研 / 项目经历：项目名称、你担任的角色、用到的技术、核心成果各是什么？（没有可回复“无”）",
    ),
    (
        "awards_positions",
        "荣誉奖项、任职或社会实践（每行一条，没有可回复“无”）：",
    ),
    (
        "extras",
        "最后一步：技能证书、语言能力与联系方式（邮箱 / 电话，可选填）。",
    ),
)

# 字段 → 简历章节标题
SECTION_LABELS: dict[str, str] = {
    "student_name": "基本信息",
    "dept": "院系专业",
    "education": "教育背景",
    "projects": "科研 / 项目经历",
    "awards_positions": "荣誉与任职",
    "extras": "技能与补充",
}

# 空答案 / 宽泛回答：视为该字段留空并跳过（不追问、不虚构）
_EMPTY_ANSWERS = {
    "无",
    "暂无",
    "没有",
    "跳过",
    "",
    "随便",
    "都行",
    "都可以",
    "你看着办",
    "你决定",
    "不知道",
}


def _field_keys() -> list[str]:
    return [key for key, _ in FIELD_SEQUENCE]


def render_resume_markdown(fields: dict[str, str]) -> str:
    """把采集字段渲染为结构化 Markdown 简历（确定性，不调用 LLM）。"""
    name = (fields.get("student_name") or "").strip()
    dept = (fields.get("dept") or "").strip()
    title = f"# {name} 个人简历" + (f" · {dept}" if dept else "")
    lines: list[str] = [title, ""]
    for key, _ in FIELD_SEQUENCE:
        value = (fields.get(key) or "").strip()
        if not value or value in _EMPTY_ANSWERS:
            continue
        lines.append(f"## {SECTION_LABELS[key]}")
        if key in {"awards_positions", "projects"}:
            for piece in re.split(r"[\n;；]+", value):
                piece = piece.strip(" 　-·")
                if piece:
                    lines.append(f"- {piece}")
        else:
            lines.append(value)
        lines.append("")
    lines.append(
        "> 注：以上内容由你提供，未经真实性核验；建议投递前自查联系方式与细节。"
    )
    return "\n".join(lines)


def build_resume_request(fields: dict[str, str]) -> dict[str, Any]:
    """把采集字段映射为 ResumeArtifactRequest 兼容 dict（供 PDF 交付）。"""
    projects: list[dict[str, str]] = []
    raw_projects = (fields.get("projects") or "").strip()
    if raw_projects and raw_projects not in _EMPTY_ANSWERS:
        projects.append({"name": "科研 / 项目经历", "detail": raw_projects})
    awards: list[str] = []
    positions: list[str] = []
    raw_awards = (fields.get("awards_positions") or "").strip()
    for piece in re.split(r"[\n;；]+", raw_awards):
        piece = piece.strip(" 　-·")
        if not piece:
            continue
        # 含"担任/负责/组织"等任职语义的行归入任职，其余按奖项处理
        if any(marker in piece for marker in ("担任", "负责", "组织", "任职", "志愿者")):
            positions.append(piece)
        else:
            awards.append(piece)
    return {
        "student_name": (fields.get("student_name") or "").strip(),
        "dept": (fields.get("dept") or "").strip(),
        "email": "",
        "phone": "",
        "education": (fields.get("education") or "").strip(),
        "research_interests": [],
        "projects": projects,
        "awards": awards,
        "positions": positions,
        "target_advisor": None,
        "format": "pdf",
        "confirm_generation": True,
    }


def _extract_interest_prefill(portrait: StudentPortrait | None) -> list[str]:
    """从访谈画像复用研究兴趣（不重复提问）。"""
    if portrait is None:
        return []
    return list(getattr(portrait, "research_interests", None) or [])[:12]


# ---------------------------------------------------------------- 智能预填

_PREFILL_LLM_SYSTEM_PROMPT = (
    "你是简历信息抽取助手。从用户一句话中抽取以下 JSON 字段，只抽取用户"
    "明确提供的信息，不得推断或虚构，没有就留空字符串：\n"
    '{"student_name": "姓名", "dept": "院系专业", '
    '"education": "教育背景（年级/GPA/核心课程）", '
    '"projects": "科研项目经历", '
    '"awards_positions": "荣誉奖项与任职", '
    '"extras": "技能证书/语言/联系方式"}'
)

_PREFILL_LLM_PROMPT = "请从下面这句话中抽取简历信息：\n{text}"

# 确定性锚点：子串命中即把整句（或提取片段）归入对应字段。顺序即优先级，
# 按"结构词越具体越靠前"排列，避免"计算机系大三"被教育锚点抢走院系。
_PREFILL_ANCHORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dept", ("系", "学院", "书院")),
    ("education", ("大一", "大二", "大三", "大四", "研一", "研二", "研三", "GPA", "绩点")),
    ("projects", ("项目", "做过", "负责", "参与", "开发", "课题", "实验")),
    ("awards_positions", ("奖", "荣誉", "担任", "奖学金")),
    ("extras", ("邮箱", "英语", "六级", "雅思", "托福", "技能", "电话", "证书")),
)

# 姓名提取后候选若含结构词（说明不是纯名字），放弃该句的姓名归类
_NAME_FORBIDDEN = ("系", "学院", "书院", "项目", "奖", "大", "研", "博", "课题", "课程")


def _prefill_deterministic(text: str) -> dict[str, str]:
    """无 LLM 时的确定性抽取：按标点拆句，逐句归类到字段。

    只抽取用户明确提供的信息（锚点命中），不做推断；每字段取首个命中句。
    """
    fields: dict[str, str] = {}
    clauses = [
        clause.strip(" 　，。；、,.!?！？")
        for clause in re.split(r"[，。；;、,\n]+", text)
        if clause.strip()
    ]
    for clause in clauses:
        # 姓名：从"我叫/我是/本人/姓名是/名字叫"前缀提取，候选须为纯名字
        name_match = re.search(
            r"(?:我叫|我是|本人(?:是|为)?|姓名(?:是|为)?|名字(?:是|叫)?)"
            r"([^\s，。；、]{1,10})",
            clause,
        )
        if name_match:
            candidate = name_match.group(1).strip()
            if candidate and not any(word in candidate for word in _NAME_FORBIDDEN):
                fields.setdefault("student_name", candidate)
                continue
        for key, anchors in _PREFILL_ANCHORS:
            if not any(anchor in clause for anchor in anchors):
                continue
            # 剥离开口"我是/在/就读于"等口语引导后整句归入
            cleaned = re.sub(
                r"^(我)?(现在|目前)?(是|在|就读于|来自|学的是|学)?(在)?",
                "",
                clause,
            ).strip(" ：:：")
            if cleaned and cleaned not in _EMPTY_ANSWERS:
                fields.setdefault(key, cleaned)
            break
    return {key: value for key, value in fields.items() if value}


async def _prefill_llm(text: str) -> dict[str, str] | None:
    """LLM 抽取（fail-closed）：无凭据 / 异常 / 非 JSON / 字段过少 → None。

    采用门槛：至少 2 个非空字段，避免单字段幻觉收益倒挂。
    """
    if not settings.llm_credentials or len(text) > 800:
        return None
    result = await _llm_complete_result(
        [
            LLMMessage(role="system", content=_PREFILL_LLM_SYSTEM_PROMPT),
            LLMMessage(role="user", content=_PREFILL_LLM_PROMPT.format(text=text[:4000])),
        ],
        timeout_seconds=settings.LLM_TIMEOUT,
    )
    if result is None:
        return None
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.text.strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    fields: dict[str, str] = {}
    for key in _field_keys():
        value = str(payload.get(key) or "").strip()[:200]
        if value and value not in _EMPTY_ANSWERS:
            fields[key] = value
    if len(fields) < 2:
        return None
    return fields


async def _try_prefill_fields(text: str) -> dict[str, str]:
    """从一条消息中尽力抽取简历字段：LLM 优先，确定性锚点兜底。

    只抽取用户明确提供的信息，不推断、不虚构；无把握时返回空 dict
    （退回逐轮询问）。可被触发消息与采集轮共用。
    """
    if not text:
        return {}
    llm_fields = await _prefill_llm(text)
    if llm_fields is not None:
        return llm_fields
    return _prefill_deterministic(text)


def _next_missing_step(fields: dict[str, str]) -> int | None:
    """第一个从未回答过的字段下标；全部回答过（含明确空）返回 None。

    与空答案语义兼容：字段已在 fields 中（值为空串）视为已答并跳过，
    只有从未回答过的字段才会被继续追问。
    """
    for index, (key, _) in enumerate(FIELD_SEQUENCE):
        if key not in fields:
            return index
    return None


def _start_or_resume_build(
    db: Session,
    *,
    session_id: str,
    student_id: str,
) -> str:
    """新开分步采集：返回第一步引导语。"""
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_RESUME_BUILD,
        state={"step": 0, "fields": {}},
    )
    return (
        "好的，我们开始为你从零生成学术简历（只整理你提供的信息，"
        "不会虚构经历）。\n\n"
        f"{FIELD_SEQUENCE[0][1]}\n\n"
        "如果你想一次说完，也可以直接把 姓名、院系、教育背景、科研项目、"
        "荣誉任职、联系方式 等信息一起发给我，我帮你自动整理成简历。\n\n"
        "随时可以回复「取消」退出简历模式。"
    )


def _completeness_tips(fields: dict[str, str]) -> list[str]:
    """简历完整性体检：关键缺失项给出诚实提示（不虚构、不补写）。"""
    tips: list[str] = []
    if not (fields.get("projects") or "").strip():
        tips.append(
            "简历中暂无科研/项目经历，建议补充课程设计、开源贡献或参赛作品，"
            "能提升与导师方向的匹配度。"
        )
    if not (fields.get("extras") or "").strip():
        tips.append(
            "简历中暂无联系方式（邮箱/电话），投递前记得补充，便于导师联系你。"
        )
    if not (fields.get("education") or "").strip():
        tips.append("简历中暂无教育背景（年级/GPA/课程），建议补充。")
    return tips


def _finalize_build(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    fields: dict[str, str],
) -> str:
    """采集完成：输出 Markdown 简历 + 完整性体检 + 后续选项。"""
    markdown = render_resume_markdown(fields)
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_RESUME_BUILD,
        state={"step": len(FIELD_SEQUENCE), "fields": fields, "phase": "awaiting_delivery"},
    )
    parts = ["简历初稿已生成：\n", markdown]
    tips = _completeness_tips(fields)
    if tips:
        parts.append("\n📋 简历体检：")
        parts.extend(f"- {tip}" for tip in tips)
        parts.append("")
    parts.append(
        "下一步（可选）：\n"
        "1. 回复「生成」或「完成」结束简历流程；\n"
        "2. 告诉我目标导师或岗位，我帮你做定向优化；\n"
        "3. 如需 PDF 文件，可登录 Web 端简历中心生成下载"
        "（聊天内暂不支持附件交付）。"
    )
    return "\n".join(parts)


def _deliver_resume_pdf(
    db: Session,
    *,
    fields: dict[str, str],
    session_id: str,
    student_id: str,
    principal: Principal,
    portrait: StudentPortrait | None,
) -> tuple[str, SodaAttachment | None]:
    """确认后生成 PDF 简历并签发短时附件交付（对齐报告交付链路）。"""
    if not settings.QXD_ATTACHMENTS_ENABLED:
        return "清小搭附件交付当前未启用；简历文本已在上方给出。", None
    if not principal.persistent:
        return (
            "当前请求没有可验证、稳定的终端用户身份，不能生成可下载简历"
            "文件；简历文本已在上方给出。",
            None,
        )
    try:
        assert_qxd_delivery_ready()
    except Exception:  # noqa: BLE001 —— 交付配置缺失时诚实提示，不阻断
        logger.exception("resume_delivery_not_ready")
        return (
            "简历文件交付尚未配置公网地址；简历文本已在上方给出。",
            None,
        )
    # 平台安全策略：清小搭短时公开转存（issue_delivery_grant qxd_platform）
    # 仅允许已确认生成的匹配报告。简历 PDF 无法通过聊天附件交付，诚实告知
    # 而非尝试越权签发（Web 端简历中心仍可生成下载）。
    return (
        "已为你整理出完整简历文本（见上）。清小搭平台的短时公开转存目前"
        "仅支持匹配报告，简历 PDF 暂不支持通过聊天附件交付；如需 PDF 文件，"
        "可登录 Web 端简历中心生成下载。",
        None,
    )


async def handle_resume_build(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
    portrait: StudentPortrait | None = None,
    principal: Principal | None = None,
) -> tuple[str, SodaAttachment | None]:
    """从零生成简历的多轮入口（含投递确认交付）。"""
    text = (latest_user or "").strip()
    mode = get_dialogue_mode(db, session_id=session_id, student_id=student_id)
    if mode != MODE_RESUME_BUILD:
        # 触发消息可能已含简历信息：智能预填 → 只问缺失字段
        prefill = await _try_prefill_fields(text)
        if prefill:
            missing_index = _next_missing_step(prefill)
            if missing_index is None:
                return (
                    _finalize_build(
                        db,
                        session_id=session_id,
                        student_id=student_id,
                        fields=prefill,
                    ),
                    None,
                )
            upsert_dialogue_state(
                db,
                session_id=session_id,
                student_id=student_id,
                mode=MODE_RESUME_BUILD,
                state={"step": missing_index, "fields": prefill},
            )
            return (
                "好的，我根据你提供的信息已经整理出大部分简历内容，"
                f"还差最后一项：\n\n{FIELD_SEQUENCE[missing_index][1]}\n\n"
                "随时可以回复「取消」退出简历模式。"
            ), None
        return _start_or_resume_build(
            db, session_id=session_id, student_id=student_id
        ), None

    state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
    fields: dict[str, str] = dict((state or {}).get("fields") or {})
    phase = (state or {}).get("phase")

    if any(term in text for term in RESUME_CANCEL_TERMS):
        clear_dialogue_state(db, session_id=session_id, student_id=student_id)
        return "已退出简历模式，可以继续聊导师匹配或其他服务。", None

    if phase == "awaiting_delivery":
        if text == RESUME_DELIVERY_CONFIRMATION:
            if principal is None:
                principal = Principal(
                    subject_id=student_id,
                    channel="qxd",
                    auth_session_id=None,
                    persistent=False,
                )
            message, attachment = _deliver_resume_pdf(
                db,
                fields=fields,
                session_id=session_id,
                student_id=student_id,
                principal=principal,
                portrait=portrait,
            )
            # 投递确认是终局动作：交付成功或诚实拒绝后都退出交付等待态
            clear_dialogue_state(db, session_id=session_id, student_id=student_id)
            return message, attachment
        if any(term in text for term in RESUME_DONE_TERMS):
            clear_dialogue_state(db, session_id=session_id, student_id=student_id)
            return (
                "简历流程已完成。需要的话我可以帮你：\n"
                "1. 匹配契合导师；\n"
                "2. 查询招募机会；\n"
                "3. 针对目标导师 / 岗位定向优化简历。"
            ), None
        return (
            "简历初稿已生成。可以回复「生成」完成，或告诉我目标导师 / "
            "岗位做定向优化；回复「取消」退出简历模式。"
        ), None

    # 普通采集轮：保存答案并推进
    step = int((state or {}).get("step", 0))
    if step >= len(FIELD_SEQUENCE):
        return (
            _finalize_build(
                db, session_id=session_id, student_id=student_id, fields=fields
            ),
            None,
        )

    key, _ = FIELD_SEQUENCE[step]
    # 采集轮收到完成语 → 直接结束流程（与交付等待态行为一致；整句精确
    # 匹配，避免把「负责项目完成度评估」这类答案误判为结束语）
    if text in RESUME_DONE_TERMS:
        clear_dialogue_state(db, session_id=session_id, student_id=student_id)
        return (
            "简历流程已完成。需要的话我可以帮你：\n"
            "1. 匹配契合导师；\n"
            "2. 查询招募机会；\n"
            "3. 针对目标导师 / 岗位定向优化简历。"
        ), None
    if not text or text in _EMPTY_ANSWERS:
        fields[key] = ""
    else:
        fields[key] = text
    # 智能预填：本条消息里顺带提到的其他字段，补到缺失项（不覆盖已填）
    prefill = await _try_prefill_fields(text)
    for pkey, pvalue in prefill.items():
        if pkey != key and not fields.get(pkey):
            fields[pkey] = pvalue
    # 推进到下一个从未回答过的字段（预填可能已跳过多轮）
    next_missing = _next_missing_step(fields)
    if next_missing is None:
        return (
            _finalize_build(
                db, session_id=session_id, student_id=student_id, fields=fields
            ),
            None,
        )
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_RESUME_BUILD,
        state={"step": next_missing, "fields": fields},
    )
    return FIELD_SEQUENCE[next_missing][1], None


# ---------------------------------------------------------------- 优化已有

_POLISH_SYSTEM_PROMPT = (
    "你是清华大学学术简历润色助手。只改写用户提供的真实内容，不得虚构"
    "任何经历、奖项或数据。请从三个维度润色：\n"
    "1. 学术表述：把口语化描述改为专业、简洁的书面表达；\n"
    "2. 经历量化：把模糊表述改写为可量化、可验证的陈述（只可标注"
    "『建议补充』，不得自行编造数字）；\n"
    "3. 逻辑结构：按 教育背景→科研/项目→荣誉与任职→技能 重排章节。\n"
    "输出 JSON：{\"polished\": \"润色后的完整简历文本\", "
    "\"notes\": [\"3-5 条修改说明，每条一句话\"]}"
)

_POLISH_PROMPT = "请润色下面的简历：\n{text}"


def _polish_user_content(
    resume_text: str,
    *,
    target: str | None,
    job_req: str | None,
) -> str:
    """构造润色用户消息：目标 + 目标岗位公开要求（如有）+ 简历原文。"""
    if not target:
        return _POLISH_PROMPT.format(text=resume_text)
    parts = [f"请针对目标「{target}」优化，突出与该目标相关的经历表述权重"]
    if job_req:
        parts.append(f"\n目标岗位公开核心要求（供你匹配表述，不得虚构经历）：\n{job_req}")
    parts.append(f"\n简历原文：\n{resume_text}")
    return "\n".join(parts)


async def _llm_polish(
    resume_text: str,
    *,
    target: str | None = None,
    job_req: str | None = None,
) -> dict | None:
    """调用 LLM 润色；任何失败返回 None（调用方降级确定性处理）。"""
    if not settings.llm_credentials:
        return None
    result = await _llm_complete_result(
        [
            LLMMessage(role="system", content=_POLISH_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=_polish_user_content(
                    resume_text, target=target, job_req=job_req
                )[:4000],
            ),
        ],
        timeout_seconds=settings.LLM_TIMEOUT,
    )
    if result is None:
        return None
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.text.strip(), flags=re.MULTILINE)
    raw = raw.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    polished = str(payload.get("polished") or "").strip()
    notes = payload.get("notes") or []
    if (
        not polished
        or len(polished) > MAX_POLISH_OUTPUT
        or not isinstance(notes, list)
    ):
        return None
    note_lines = [str(note).strip() for note in notes if str(note).strip()][:5]
    return {"polished": polished, "notes": note_lines}


def _deterministic_normalize(resume_text: str) -> tuple[str, list[str]]:
    """无 LLM 时的确定性降级：分点整理 + 量化提示（不虚构）。"""
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    cleaned = "\n".join(lines)
    notes: list[str] = []
    if not re.search(r"\d", cleaned):
        notes.append(
            "建议为经历补充可量化的成果（如参与项目数、数据规模、排名），"
            "让表达更有说服力。"
        )
    if len(lines) <= 2:
        notes.append(
            "建议按 教育背景 → 科研/项目 → 荣誉与任职 → 技能 分章节展开。"
        )
    if not notes:
        notes.append("原文结构完整，已做去空行与格式整理。")
    notes.append("（当前未配置文本润色模型，以上为确定性整理）")
    return cleaned, notes


def _format_polish_output(
    polished: str,
    notes: list[str],
    *,
    llm_used: bool,
) -> str:
    header = "润色后的简历：" if llm_used else "整理后的简历："
    parts = [header, "", polished, ""]
    if notes:
        parts.append("核心修改说明：")
        parts.extend(f"- {note}" for note in notes[:5])
        parts.append("")
    if not llm_used:
        parts.append("提示：以上为确定性整理，未使用生成式润色。")
    parts.append("如需针对特定导师或招募岗位做定向优化，直接把目标告诉我。")
    return "\n".join(parts)


async def handle_resume_polish(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
    target: str | None = None,
    portrait: StudentPortrait | None = None,
) -> tuple[str, SodaAttachment | None]:
    """优化已有简历：等待粘贴 → 润色（LLM 或确定性降级）。

    定向目标解析为岗位时（序号/标题），附加该岗位公开核心要求给润色
    模型；无 LLM 或解析失败时按普通目标名处理，绝不编造岗位信息。
    """
    text = (latest_user or "").strip()
    mode = get_dialogue_mode(db, session_id=session_id, student_id=student_id)
    target_mode = MODE_RESUME_TARGETED if target else MODE_RESUME_POLISH

    if any(term in text for term in RESUME_CANCEL_TERMS):
        clear_dialogue_state(db, session_id=session_id, student_id=student_id)
        return "已退出简历优化，可以继续其他服务。", None

    waiting = mode == target_mode and bool(
        (get_dialogue_state(db, session_id=session_id, student_id=student_id) or {}).get(
            "awaiting_text"
        )
    )
    # 命令式触发词（请求润色而非内容）；其余消息直接视为简历原文
    _POLISH_TRIGGER_TERMS = (
        "优化简历",
        "简历优化",
        "润色",
        "打磨",
        "改简历",
        "完善简历",
        "定向优化",
        "投递优化",
        "适配",
        "针对",
    )
    if not waiting:
        if text and not any(term in text for term in _POLISH_TRIGGER_TERMS):
            resume_text = text
        else:
            upsert_dialogue_state(
                db,
                session_id=session_id,
                student_id=student_id,
                mode=target_mode,
                state={"awaiting_text": True, "target": target},
            )
            if target:
                return (
                    f"好的，将针对「{target}」做定向优化。请把你的简历原文"
                    "粘贴给我（或分条描述核心内容）；回复「取消」退出。"
                ), None
            return (
                "好的，我来帮你打磨简历。请把你的简历原文粘贴给我"
                "（或分条描述核心内容）；回复「取消」退出。"
            ), None
    else:
        resume_text = text

    if len(resume_text) > MAX_POLISH_TEXT:
        return (
            f"简历原文过长（{len(resume_text)} 字），请控制在 {MAX_POLISH_TEXT}"
            " 字以内分段提供。"
        ), None

    stored = get_dialogue_state(db, session_id=session_id, student_id=student_id) or {}
    effective_target = target or stored.get("target")
    # 岗位联动：目标解析为公开招募岗位 → 附加其核心要求给润色模型
    job_req: str | None = None
    if effective_target:
        interests = list(getattr(portrait, "research_interests", None) or [])
        resolved = resolve_recruitment_target(
            db, effective_target, interests=interests
        )
        if resolved is not None:
            effective_target = resolved.get("title") or effective_target
            job_req = (
                resolved.get("req") or resolved.get("major") or None
            )
    llm_result = await _llm_polish(
        resume_text, target=effective_target, job_req=job_req
    )
    clear_dialogue_state(db, session_id=session_id, student_id=student_id)
    if llm_result is not None:
        return (
            _format_polish_output(llm_result["polished"], llm_result["notes"], llm_used=True),
            None,
        )
    polished, notes = _deterministic_normalize(resume_text)
    return _format_polish_output(polished, notes, llm_used=False), None


def parse_target_from_message(latest_user: str) -> str | None:
    """从定向优化消息中提取目标（导师/岗位/方向）。

    支持：针对「X」/ 面向 X / 适配 X / 投递 X 岗位（导师）。
    """
    text = latest_user or ""
    for marker in ("针对", "面向", "适配", "投递"):
        if marker not in text:
            continue
        remainder = text.split(marker, 1)[1]
        remainder = re.split(r"[，。！？\n]|优化|润色|打磨|改|简历", remainder, 1)[0]
        remainder = remainder.strip(" “”\"'《》（）()的")
        # 导师式目标：裁剪「XX 老师的课题组 / 实验室」这类结构，只留姓名
        remainder = re.sub(
            r"(老师|教授|导师)?的?(课题组|实验室|研究组|团队|组)$",
            "",
            remainder,
        )
        remainder = re.sub(r"(老师|教授|导师)$", "", remainder)
        if remainder and len(remainder) <= 60:
            return remainder
    return None


async def handle_resume_targeted(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
    portrait: StudentPortrait | None = None,
) -> tuple[str, SodaAttachment | None]:
    """针对目标导师 / 岗位的定向优化。"""
    target = parse_target_from_message(latest_user)
    if not target:
        return (
            "请告诉我要针对哪位导师或哪个岗位优化，例如："
            "「针对张三老师的课题组优化简历」或「针对这个科研助理岗位优化简历」。"
        ), None
    return await handle_resume_polish(
        db,
        latest_user=latest_user,
        session_id=session_id,
        student_id=student_id,
        target=target,
        portrait=portrait,
    )
