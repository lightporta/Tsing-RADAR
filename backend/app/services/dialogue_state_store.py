"""对话模式状态的读写（dialogue_sessions 表）。

同一通对话（session_id）内只能处于一种对话模式；模式切换时旧状态
整体覆盖（版本号递增）。与访谈共用会话键，但不与访谈状态互相影响。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.dialogue_state import DialogueSession

# v4.2.2（回归问题4）：会话级 KV（一次性标记 / 上一轮话术 / 兜底卡去重）与
# 对话模式状态混存在同一 state JSON。模式状态写入（persist_shown_batch 等）
# 若整体覆盖会把 KV 冲掉——典型后果：匹配成功（persist 批次）后再次归零时
# "无候选兜底卡"重复弹出（flag 丢失）。约定：模式状态写入时合并保留这些键。
_SESSION_KV_KEYS: frozenset[str] = frozenset({
    "no_candidate_card_shown",
    "interview_last_expression",
    "interview_recruitment_noted",
})


def _preserve_kv(old_state: dict[str, Any] | None) -> dict[str, Any]:
    """取出旧 state 中的会话级 KV 键（供模式状态写入时合并保留）。"""
    return {
        key: value
        for key, value in (old_state or {}).items()
        if key in _SESSION_KV_KEYS
    }


def get_dialogue_state(
    db: Session,
    *,
    session_id: str,
    student_id: str,
) -> dict[str, Any] | None:
    """按会话键读取状态；主体不匹配视为不存在（不跨主体串扰）。"""
    record = (
        db.query(DialogueSession)
        .filter(
            DialogueSession.session_id == session_id,
            DialogueSession.student_id == student_id,
        )
        .first()
    )
    if record is None:
        return None
    return dict(record.state)


def get_dialogue_mode(
    db: Session,
    *,
    session_id: str,
    student_id: str,
) -> str | None:
    """只读当前对话模式名（无记录/无活动模式返回 None）。

    "none" 是会话级 KV（一次性标记 / 表达层上一轮话术）落库时的占位
    mode，不代表活动对话模式——必须归一化为 None，否则会把后续轮次
    的意图分类短路成 NONE（v4.2.0 修复：表达层话术每轮写入激活了该
    潜在缺陷）。
    """
    record = (
        db.query(DialogueSession.mode)
        .filter(
            DialogueSession.session_id == session_id,
            DialogueSession.student_id == student_id,
        )
        .first()
    )
    if record is None:
        return None
    mode = record[0]
    return mode if mode and mode != "none" else None


def upsert_dialogue_state(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    mode: str,
    state: dict[str, Any],
) -> None:
    """写入或整体覆盖指定模式的对话状态；版本号每次 +1。

    v4.2.2：合并保留会话级 KV 键（_SESSION_KV_KEYS），避免模式状态
    （匹配批次等）写入时把一次性标记/上一轮话术/兜底卡去重冲掉。
    """
    record = (
        db.query(DialogueSession)
        .filter(
            DialogueSession.session_id == session_id,
            DialogueSession.student_id == student_id,
        )
        .first()
    )
    if record is None:
        record = DialogueSession(
            session_id=session_id,
            student_id=student_id,
            mode=mode,
            state=state,
            version=1,
        )
        db.add(record)
    else:
        merged = {**_preserve_kv(record.state), **dict(state)}
        record.mode = mode
        record.state = merged
        record.version = record.version + 1
    # 状态机服务惯例：状态写入后立即提交（与 interview.py 一致）；
    # 会话键跨请求复用依赖此提交。
    db.commit()


def clear_dialogue_state(
    db: Session,
    *,
    session_id: str,
    student_id: str,
) -> None:
    """清除该会话键的对话模式状态（退出/取消时调用）。

    v4.2.2：保留会话级 KV 键（兜底卡去重等），只清模式状态；mode 归位
    "none"（get_dialogue_mode 视其为无活动模式）。
    """
    record = (
        db.query(DialogueSession)
        .filter(
            DialogueSession.session_id == session_id,
            DialogueSession.student_id == student_id,
        )
        .first()
    )
    if record is None:
        return
    preserved = _preserve_kv(record.state)
    if preserved:
        record.mode = "none"
        record.state = preserved
        record.version = (record.version or 0) + 1
        db.commit()
    else:
        db.delete(record)
        db.commit()


def has_session_flag(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    key: str,
) -> bool:
    """只读会话级一次性标记（如"访谈期招募提示已注入"）。"""
    state = get_dialogue_state(
        db, session_id=session_id, student_id=student_id
    )
    return bool(state and state.get(key))


def mark_session_flag(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    key: str,
) -> None:
    """写入会话级一次性标记；合并进既有 state，不改写当前对话模式。"""
    record = (
        db.query(DialogueSession)
        .filter(
            DialogueSession.session_id == session_id,
            DialogueSession.student_id == student_id,
        )
        .first()
    )
    if record is None:
        record = DialogueSession(
            session_id=session_id,
            student_id=student_id,
            mode="none",
            state={key: True},
            version=1,
        )
        db.add(record)
    else:
        merged = dict(record.state or {})
        merged[key] = True
        record.state = merged
        record.version = (record.version or 0) + 1
    db.commit()


def get_session_value(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    key: str,
) -> str | None:
    """只读会话级字符串值（如「上一轮表达层实际展示话术」）。

    v4.2.0 多轮自然度：与一次性标记同一存储约定；值非字符串（被对话
    模式整体覆盖等）视为不存在，调用方回退到底稿推导。
    """
    state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
    if not state:
        return None
    value = state.get(key)
    return value if isinstance(value, str) else None


def set_session_value(
    db: Session,
    *,
    session_id: str,
    student_id: str,
    key: str,
    value: str,
) -> None:
    """写入会话级字符串值；合并进既有 state，不改写当前对话模式。"""
    record = (
        db.query(DialogueSession)
        .filter(
            DialogueSession.session_id == session_id,
            DialogueSession.student_id == student_id,
        )
        .first()
    )
    if record is None:
        record = DialogueSession(
            session_id=session_id,
            student_id=student_id,
            mode="none",
            state={key: value},
            version=1,
        )
        db.add(record)
    else:
        merged = dict(record.state or {})
        merged[key] = value
        record.state = merged
        record.version = (record.version or 0) + 1
    db.commit()
