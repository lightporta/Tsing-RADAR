"""user_memories 长期记忆服务（v4.0.0，Ultra-Memory 的确定性等价物）。

写入门禁（诚实性红线）：
- 只写入**已确认画像**的白名单字段（六维 + 硬性条件 + 确认门标记）；
- 任何未确认猜测、LLM 推断、编辑中草案一律不写；
- 写入触发点只有两处：`interview.answer_session` 确认分支与
  `interview.confirm_profile`（Web 画像卡确认）——两者都发生在
  确认门通过之后。

召回侧：`format_memory_summary` 生成"事实片段"（不含框架词），供
表达层 FactPack.memory_summary 注入；逐字校验保证表达层不得改写事实。
隐私侧：`list_memories` / `clear_memories` 供用户查看与清除。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.user_memory import UserMemory

MEMORY_SOURCE = "portrait_confirmed"

# 白名单键序（格式化摘要时也按此顺序输出）
_DIMENSION_KEYS = (
    "research_mode",
    "mentorship_style",
    "career_orientation",
    "innovation_risk",
)
_INTEREST_KEY = "research_interests"
_CONSTRAINT_KEY = "hard_constraints"
_CONFIRMED_MARKER_KEY = "portrait_confirmed"

# 注入 FactPack 的摘要只含事实片段（>=4 字片段会被逐字校验），
# 不包含任何框架词，表达层只能原样引用。
_SUMMARY_KEY_ORDER = (
    _INTEREST_KEY,
    *_DIMENSION_KEYS,
    _CONSTRAINT_KEY,
)

_VALUE_LABELS_CACHE: dict[str, str] | None = None


def _value_labels() -> dict[str, str]:
    """访谈模块的取值标签（惰性导入，避免 services 间循环导入）。"""
    global _VALUE_LABELS_CACHE
    if _VALUE_LABELS_CACHE is None:
        from app.services.interview import _VALUE_LABELS

        _VALUE_LABELS_CACHE = dict(_VALUE_LABELS)
    return _VALUE_LABELS_CACHE


def _constraint_text(constraints: list[dict[str, Any]]) -> str:
    """结构化硬约束 → 原文事实；优先用确认时的 source_text 原样拼接。"""
    texts: list[str] = []
    for item in constraints:
        source_text = (item.get("source_text") or "").strip()
        if source_text:
            texts.append(source_text)
            continue
        value = "、".join(str(v) for v in (item.get("value") or []))
        operator = item.get("operator")
        if operator == "minimum":
            texts.append(f"至少{value}")
        elif operator in ("one_of", "equals"):
            texts.append(f"必须是{value}")
        elif operator == "excludes":
            texts.append(f"排除{value}")
        else:
            texts.append(f"{item.get('field')}：{value}")
    return "、".join(texts)


def _whitelisted_rows(portrait: dict[str, Any]) -> list[tuple[str, str]]:
    """把已确认画像投影为白名单记忆行（键 → 事实文本）。"""
    rows: list[tuple[str, str]] = []
    interests = portrait.get(_INTEREST_KEY) or []
    if interests:
        rows.append((_INTEREST_KEY, "、".join(str(tag) for tag in interests)))
    labels = _value_labels()
    for key in _DIMENSION_KEYS:
        value = portrait.get(key)
        if value:
            rows.append((key, labels.get(value, str(value))))
    constraints = portrait.get(_CONSTRAINT_KEY)
    if constraints:
        rows.append((_CONSTRAINT_KEY, _constraint_text(constraints)))
    rows.append(
        (
            _CONFIRMED_MARKER_KEY,
            datetime.now(timezone.utc).isoformat(),
        )
    )
    return rows


def remember_confirmed_portrait(
    db: Session,
    *,
    student_id: str,
    portrait: dict[str, Any],
) -> int:
    """确认门通过后写入白名单记忆（幂等覆盖，返回写入行数）。"""
    rows = _whitelisted_rows(portrait)
    for key, value in rows:
        record = (
            db.query(UserMemory)
            .filter(
                UserMemory.student_id == student_id,
                UserMemory.memory_key == key,
            )
            .one_or_none()
        )
        if record is None:
            db.add(
                UserMemory(
                    student_id=student_id,
                    memory_key=key,
                    memory_value=value,
                    source=MEMORY_SOURCE,
                )
            )
        else:
            record.memory_value = value
            record.source = MEMORY_SOURCE
            record.updated_at = datetime.now(timezone.utc)
    db.commit()
    return len(rows)


def recall_memories(db: Session, student_id: str) -> dict[str, str]:
    """按 student_id 召回全部记忆（键 → 事实文本）；无记忆返回空字典。"""
    records = (
        db.query(UserMemory)
        .filter(UserMemory.student_id == student_id)
        .all()
    )
    return {record.memory_key: str(record.memory_value) for record in records}


def format_memory_summary(db: Session, student_id: str) -> str:
    """已确认事实的、可注入表达层 FactPack 的摘要（事实片段，无框架词）。"""
    memories = recall_memories(db, student_id)
    parts = [
        memories[key]
        for key in _SUMMARY_KEY_ORDER
        if memories.get(key)
    ]
    return "、".join(parts)


def list_memories(
    db: Session, student_id: str
) -> list[dict[str, str]]:
    """隐私查看：全部记忆条目（键/值/来源/更新时间）。"""
    records = (
        db.query(UserMemory)
        .filter(UserMemory.student_id == student_id)
        .order_by(UserMemory.memory_key)
        .all()
    )
    return [
        {
            "memory_key": record.memory_key,
            "memory_value": str(record.memory_value),
            "source": record.source,
            "updated_at": (
                record.updated_at.isoformat() if record.updated_at else ""
            ),
        }
        for record in records
    ]


def clear_memories(db: Session, student_id: str) -> int:
    """隐私清除：删除该主体全部记忆，返回删除条数。"""
    deleted = (
        db.query(UserMemory)
        .filter(UserMemory.student_id == student_id)
        .delete()
    )
    db.commit()
    return deleted


# 记忆键 → 用户可读标签（隐私查看用）
_MEMORY_KEY_LABELS = {
    _INTEREST_KEY: "研究兴趣",
    "research_mode": "研究方式",
    "mentorship_style": "指导偏好",
    "career_orientation": "生涯方向",
    "innovation_risk": "创新风险",
    _CONSTRAINT_KEY: "硬性条件",
    _CONFIRMED_MARKER_KEY: "画像确认时间",
}


def format_memory_listing(db: Session, student_id: str) -> str:
    """隐私查看：全部长期记忆的用户可读文本（确定性、只读）。"""
    rows = list_memories(db, student_id)
    if not rows:
        return (
            "当前没有保存任何长期记忆。完成访谈并确认画像后，才会保存"
            "已确认的研究兴趣与偏好（未确认的内容不会写入）。"
        )
    lines = ["当前保存的长期记忆（只来自你已确认的画像，共 "
             f"{len(rows)} 条）："]
    for row in rows:
        label = _MEMORY_KEY_LABELS.get(row["memory_key"], row["memory_key"])
        lines.append(f"- {label}：{row['memory_value']}")
    lines.append("如需删除，回复「清除记忆」。")
    return "\n".join(lines)
