"""user_memories 长期记忆服务（v4.0.0，Ultra-Memory 的确定性等价物）。

写入门禁（诚实性红线）：
- 只写入**已确认画像**的白名单字段（六维 + 硬性条件 + 确认门标记）；
- 任何未确认猜测、LLM 推断、编辑中草案一律不写；
- 写入触发点只有两处：`interview.answer_session` 确认分支与
  `interview.confirm_profile`（Web 画像卡确认）——两者都发生在
  确认门通过之后。

v4.3.0 阶段二新增「沟通阶段」白名单键（communication_stage）：
- 值域为固定枚举（初选/联系中/已约谈），由**确定性服务端事件**触发
  （匹配候选展示 / 套磁邮件生成成功 / 站内投递成功）；
- `remember_communication_stage` 是唯一写入口，stage 实参在函数签名层
  即封闭为枚举——LLM/用户自由文本在结构上无法到达本函数；
- 只前进不回退（初选→联系中→已约谈）；画像确认写入不触碰该键；
- 阶段值 <4 字，不在表达层逐字校验范围内（软性上下文，非硬事实）；
  匹配/确认/评分等一切管线决策均不读取该键。

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
STAGE_SOURCE = "communication_event"

# v4.3.0 沟通阶段：值域封闭枚举（顺序即阶段序，只前进不回退）
_COMMUNICATION_STAGES = ("初选", "联系中", "已约谈")
_STAGE_RANK = {stage: rank for rank, stage in enumerate(_COMMUNICATION_STAGES)}
STAGE_KEY = "communication_stage"
# 触发点使用的语义常量（服务端代码专用，不接受外部文本）
STAGE_INITIAL = _COMMUNICATION_STAGES[0]
STAGE_CONTACTING = _COMMUNICATION_STAGES[1]
STAGE_INTERVIEWED = _COMMUNICATION_STAGES[2]

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
# 不包含任何框架词，表达层只能原样引用。沟通阶段缀在画像事实之后
# （软性上下文；<4 字不参与逐字校验）。
_SUMMARY_KEY_ORDER = (
    _INTEREST_KEY,
    *_DIMENSION_KEYS,
    _CONSTRAINT_KEY,
    STAGE_KEY,
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


def remember_communication_stage(
    db: Session,
    *,
    student_id: str,
    stage: str,
) -> bool:
    """确定性事件触发的沟通阶段更新（v4.3.0 阶段二）。

    红线：stage 必须是固定枚举常量（STAGE_INITIAL/CONTACTING/INTERVIEWED
    之一）——本函数是该键的唯一写入口，枚举校验使 LLM/用户自由文本在
    结构上无法写库（传入任何非枚举值直接拒绝，属编程错误）。
    只前进不回退：当前阶段序 ≥ 新阶段序时幂等跳过（返回 False）。
    """
    if stage not in _STAGE_RANK:
        raise ValueError(f"未知沟通阶段：{stage!r}")
    current = (
        db.query(UserMemory.memory_value)
        .filter(
            UserMemory.student_id == student_id,
            UserMemory.memory_key == STAGE_KEY,
        )
        .scalar()
    )
    if current in _STAGE_RANK and _STAGE_RANK[stage] <= _STAGE_RANK[current]:
        return False
    record = (
        db.query(UserMemory)
        .filter(
            UserMemory.student_id == student_id,
            UserMemory.memory_key == STAGE_KEY,
        )
        .one_or_none()
    )
    if record is None:
        db.add(
            UserMemory(
                student_id=student_id,
                memory_key=STAGE_KEY,
                memory_value=stage,
                source=STAGE_SOURCE,
            )
        )
    else:
        record.memory_value = stage
        record.source = STAGE_SOURCE
        record.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


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
    STAGE_KEY: "沟通阶段",
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
