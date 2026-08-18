"""公开招募列表的共用查询与清小搭摘要格式化。

从 /api/recruitments 路由提取的查询逻辑（行为等价），供路由与清小搭
对话摘要共用；摘要只读公开数据，附网站深链，不在聊天内收集任何信息。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.recruitment import Recruitment
from app.schemas.interview import StudentPortrait
from app.services.data_loader import load_mentors

PROJECT_TIMEZONE = ZoneInfo("Asia/Shanghai")

RECRUITMENT_SITE_URL = "https://www.tsingradar.com.cn/recruitment"


def _deadline_is_past(value: object, *, today: date) -> bool:
    try:
        deadline = value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return deadline < today


def _db_public_record(record: Recruitment) -> dict:
    """数据库投稿只有审核发布后才调用；不暴露内部主体或 provenance。"""
    data = {
        "recruit_id": record.recruit_id,
        "publisher_name": "经审核发布者",
        "publisher_type": record.publisher_type,
        "type": record.type,
        "title": record.title,
        "req": record.req,
        "major": record.major,
        "deadline": record.deadline,
        "is_urgent": record.is_urgent,
        "dept": "",
        "review_status": record.review_status,
        "publication_status": record.publication_status,
    }
    # 立体化扩展字段：缺省（None）时不输出对应键，旧客户端响应形态不变
    for field in (
        "location",
        "quota",
        "compensation",
        "duration",
        "apply_method",
        "tags",
        "advisor_id",
    ):
        value = getattr(record, field, None)
        if value is not None:
            data[field] = value
    return data


def list_public_recruitments(
    db: Session, *, urgent_only: bool = False
) -> tuple[list[dict[str, Any]], int]:
    """已过审、已发布、未下架且未过期的公开招募（静态数据集 + 数据库投稿）。

    返回 (records, withheld_submissions)；行为与 /api/recruitments 原实现一致。
    """
    result: list[dict[str, Any]] = []
    now = datetime.now(PROJECT_TIMEZONE)
    for mentor in load_mentors():
        for recruitment in mentor.get("recruitments", []) or []:
            if _deadline_is_past(recruitment.get("deadline"), today=now.date()):
                continue
            if urgent_only and not recruitment.get("is_urgent", False):
                continue
            result.append(recruitment)
    published_db = (
        db.query(Recruitment)
        .filter(
            Recruitment.review_status == "verified",
            Recruitment.publication_status == "published",
            Recruitment.takedown_at.is_(None),
        )
        .all()
    )
    for record in published_db:
        if _deadline_is_past(record.deadline, today=now.date()):
            continue
        if urgent_only and not record.is_urgent:
            continue
        result.append(_db_public_record(record))
    withheld = (
        db.query(Recruitment)
        .filter(Recruitment.publication_status != "published")
        .count()
    )
    return result, withheld


def get_public_recruitment(
    db: Session, recruit_id: str
) -> dict[str, Any] | None:
    """与公开列表同一过滤口径的单帖查询（详情页用）；不命中返回 None。

    过滤语义与 list_public_recruitments 完全一致：verified + published +
    未下架 + 未过期；详情页不得放宽。数据库帖附带创建/过审时间线字段。
    """
    now = datetime.now(PROJECT_TIMEZONE)
    record = db.get(Recruitment, recruit_id)
    if record is not None:
        if (
            record.review_status == "verified"
            and record.publication_status == "published"
            and record.takedown_at is None
            and not _deadline_is_past(record.deadline, today=now.date())
        ):
            data = _db_public_record(record)
            data["created_at"] = (
                record.created_at.isoformat() if record.created_at else None
            )
            data["verified_at"] = (
                record.verified_at.isoformat() if record.verified_at else None
            )
            return data
        return None
    for mentor in load_mentors():
        for recruitment in mentor.get("recruitments", []) or []:
            if recruitment.get("recruit_id") != recruit_id:
                continue
            if _deadline_is_past(recruitment.get("deadline"), today=now.date()):
                return None
            return recruitment
    return None


def advisor_brief(advisor_id: str) -> dict[str, Any] | None:
    """按 advisor_id 联查公开导师概要（姓名/院系），查不到返回 None。"""
    for mentor in load_mentors():
        if str(mentor.get("advisor_id") or "") == str(advisor_id):
            return {
                "advisor_id": advisor_id,
                "name": mentor.get("name") or "",
                "dept": mentor.get("dept") or "",
            }
    return None


def _deadline_text(record: dict[str, Any]) -> str:
    deadline = record.get("deadline")
    if isinstance(deadline, datetime):
        return deadline.date().isoformat()
    if isinstance(deadline, date):
        return deadline.isoformat()
    if deadline:
        return str(deadline)
    return "长期有效"


def _relevance_score(record: dict[str, Any], interests: list[str]) -> int:
    haystack = f"{record.get('major') or ''} {record.get('title') or ''}"
    return sum(1 for tag in interests if tag and tag in haystack)


def _deadline_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    deadline = record.get("deadline")
    if isinstance(deadline, datetime):
        return (0, deadline.date().isoformat())
    if isinstance(deadline, date):
        return (0, deadline.isoformat())
    return (1, str(deadline or ""))


def format_recruitment_digest(
    records: list[dict[str, Any]],
    *,
    profile: StudentPortrait | None = None,
    limit: int = 3,
) -> str:
    """把公开招募列表格式化为清小搭摘要文本（诚实空态 + 网站深链）。"""
    if not records:
        return (
            "暂无通过审核且仍在招期内的招募信息。投稿在审核通过后会出现在"
            f"这里；你也可以在网站查看与投递 👉 {RECRUITMENT_SITE_URL}"
        )
    interests = list(getattr(profile, "research_interests", None) or [])
    ranked = sorted(
        records,
        key=lambda record: (
            -_relevance_score(record, interests),
            *_deadline_sort_key(record),
        ),
    )
    selected = ranked[: max(1, limit)]
    personalized = bool(interests) and _relevance_score(selected[0], interests) > 0
    header = (
        f"📢 当前有 {len(records)} 条通过审核且在招的招募信息"
        + ("，按与你的画像相关度取前"
          f" {len(selected)} 条：" if personalized else f"，取前 {len(selected)} 条：")
    )
    lines: list[str] = [header]
    for index, record in enumerate(selected, start=1):
        urgent = "[急招] " if record.get("is_urgent") else ""
        type_label = record.get("type") or "招募"
        lines.append(
            f"\n{index}. {urgent}{record.get('title') or '未命名招募'} · "
            f"{type_label} · 截止 {_deadline_text(record)}"
        )
        matched_tags = [
            tag for tag in interests if tag and tag in f"{record.get('major') or ''} {record.get('title') or ''}"
        ]
        if matched_tags:
            lines.append(
                f"   匹配点：{'、'.join(matched_tags)} 与你的研究兴趣重合"
            )
    lines.append("")
    lines.append(f"浏览全部、查看详情与站内投递 👉 {RECRUITMENT_SITE_URL}")
    lines.append("提示：发布与投递记录只在网站内管理，聊天内不收集简历。")
    return "\n".join(lines)
