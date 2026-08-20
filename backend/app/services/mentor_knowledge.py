"""v4.0.0 任务1 A-1：导师公开评价知识库（综述级词法索引，确定性等价物）。

知识本体由 scripts/build_mentor_knowledge.py 从《清华导师评价综述》构建：
只含综述级聚合事实（评价统计 / 判档 / 四维结构化均分 / 综述摘要），
无任何原始引文；knowledge_manifest.json 记录来源 SHA256 供溯源。

治理边界（红线，逐字）：
- 只作咨询参考输出，绝不混入雷达/匹配客观管线；
- 回复必须带「匿名主观评价聚合，仅作参考」声明；
- 未收录 → 诚实拒答（"该信息暂未收录，建议通过官方邮箱联系导师确认"）；
- 知识文件缺失/损坏 → 全链路降级为空索引（行为等同未收录）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.dialogue_intent import extract_mentor_query_name

logger = logging.getLogger(__name__)

_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "knowledge"
    / "mentors.knowledge.json"
)

_DECLARATION = "公开存档匿名主观评价聚合，仅作参考，不构成对导师能力的客观评判"
_NOT_FOUND_TEMPLATE = (
    "该信息暂未收录：暂无「{name}」的公开评价综述，"
    "建议通过官方邮箱联系导师确认。"
)
_QUOTE_DISCLAIMER = (
    "匿名主观评价存在偏差与情绪化内容，存档时间跨度较大，"
    "仅供选导师参考，请通过官方渠道进一步核实。"
)

_index: dict[str, dict[str, Any]] | None = None


def _read_index() -> dict[str, dict[str, Any]]:
    """读取知识本体；缺失/损坏 → 空索引（降级，等同未收录）。"""
    try:
        payload = json.loads(_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except OSError:
        logger.warning(
            "综述级知识库文件缺失或不可读：%s（按未收录降级，不阻断服务）",
            _KNOWLEDGE_PATH,
        )
        return {}
    except ValueError:
        logger.warning(
            "综述级知识库文件损坏（JSON 解析失败）：%s（按未收录降级，不阻断服务）",
            _KNOWLEDGE_PATH,
        )
        return {}
    mentors = payload.get("mentors") or []
    index: dict[str, dict[str, Any]] = {}
    for mentor in mentors:
        name = str(mentor.get("name") or "").strip()
        # 同名章节（如"李宇根"与"李宇根(WoogeunRhee)"为同一导师两条）：
        # 首次出现者优先，后续同名不覆盖（避免索引静默丢失信息）。
        if name and name not in index:
            index[name] = mentor
    return index


def _load_index() -> dict[str, dict[str, Any]]:
    global _index
    if _index is None:
        _index = _read_index()
    return _index


def reset_knowledge_cache() -> None:
    """清空模块级索引缓存（测试用）。"""
    global _index
    _index = None


def query_mentor_knowledge(name: str) -> dict[str, Any] | None:
    """姓名精确 / 子串匹配；未收录返回 None（不编造）。"""
    key = (name or "").strip()
    if not key:
        return None
    index = _load_index()
    if key in index:
        return index[key]
    for stored, record in index.items():
        if key in stored or stored in key:
            return record
    return None


def _render_four_dim(four_dim: dict[str, Any] | None) -> str | None:
    if not four_dim:
        return None
    labels = (
        ("academic", "学术"),
        ("funding", "经费"),
        ("relationship", "师生关系"),
        ("prospects", "学生前途"),
    )
    parts = []
    for key, label in labels:
        value = four_dim.get(key)
        parts.append(f"{label} {value if value is not None else '—'}")
    return "｜".join(parts) + f"（{four_dim.get('sample', '?')} 条带评分）"


def render_mentor_knowledge(record: dict[str, Any]) -> str:
    """渲染知识块（确定性文本，不经 LLM）。仅引用记录内聚合事实。"""
    name = str(record.get("name") or "").strip()
    dept = str(record.get("department_header") or "院系未收录").strip()
    stats = record.get("stats") or {}
    lines = [f"【{name} · {dept}】{_DECLARATION}", ""]

    if stats:
        pos = stats.get("positive", 0)
        neu = stats.get("neutral", 0)
        neg = stats.get("negative", 0)
        review_count = record.get("review_count", pos + neu + neg)
        lines.append(
            f"· 评价概况：{review_count} 条（正面 {pos} / 中性 {neu} / 负面 {neg}）"
            f"，推荐率 {stats.get('recommend_rate', '?')}%"
            f"，情感均值 {stats.get('sentiment_mean', '?')}"
        )
        lines.append(
            f"· 判档：{stats.get('band', '?')}"
            f" ｜ tolerance {stats.get('tolerance', '?')}"
            f"（{stats.get('tolerance_method', '?')}）"
            f" ｜ 置信 {stats.get('confidence', '?')}"
        )

    four_dim_line = _render_four_dim(record.get("four_dim"))
    if four_dim_line:
        lines.append(f"· 四维评分（导师评价网结构化均分 /5）：{four_dim_line}")

    summary = str(record.get("summary") or "").strip()
    if summary:
        lines.append(f"· 综述：{summary}")

    if record.get("in_current_db"):
        authority_parts = []
        if record.get("authority"):
            authority_parts.append(str(record["authority"]))
        recruitment = record.get("recruitment_2027") or []
        if recruitment:
            authority_parts.append("2027 招生：" + "、".join(recruitment))
        if record.get("homepage"):
            authority_parts.append("官方主页：" + str(record["homepage"]))
        if authority_parts:
            lines.append("· 权威信息：" + "｜".join(authority_parts))
    else:
        lines.append("· 说明：不在当前导师库（可能已调离/退休/未招生），权威信息缺省。")

    if stats and (stats.get("sources") or stats.get("date_range")):
        source_note = "｜".join(
            part
            for part in (
                f"来源 {stats.get('sources')}" if stats.get("sources") else "",
                stats.get("date_range") or "",
            )
            if part
        )
        lines.append(f"· 数据说明：{source_note}。{_QUOTE_DISCLAIMER}")
    return "\n".join(lines)


def render_mentor_not_found(name: str) -> str:
    """未收录的诚实拒答（逐字红线：不编造联系方式、名额、项目细节）。"""
    return _NOT_FOUND_TEMPLATE.format(name=name)


def handle_mentor_knowledge(latest_user: str) -> tuple[str, None] | None:
    """对话模式 handler：确定性知识块，不经 LLM。

    未提取到姓名返回 None（调用方放行走主流程，不吞消息）。
    """
    name = extract_mentor_query_name(latest_user)
    if not name:
        return None
    record = query_mentor_knowledge(name)
    if record is None:
        return render_mentor_not_found(name), None
    return render_mentor_knowledge(record), None
