"""v4.1.0 长期记忆隐私入口：对话意图路由 + 查看/清除（两段式确认）。

红线：查看/清除均为确定性输出（不经 LLM）；只作用于本人
user_memories，不触碰访谈与匹配记录。
"""

from __future__ import annotations

import asyncio

from uuid import uuid4

from app.api.v1.chat import _dispatch_dialogue_mode
from app.db.session import SessionLocal
from app.services.dialogue_intent import (
    MEMORY_CLEAR_CONFIRMATION,
    DialogueMode,
    classify_dialogue_intent,
)
from app.services.identity import Principal
from app.services.memory_service import (
    clear_memories,
    format_memory_listing,
    remember_confirmed_portrait,
)


def _principal() -> Principal:
    return Principal(
        subject_id=f"stu_{uuid4().hex}",
        channel="qxd",
        auth_session_id=None,
        persistent=True,
    )


def _portrait_dict() -> dict:
    return {
        "research_interests": ["自然语言处理"],
        "research_mode": "engineering",
        "hard_constraints": [
            {"field": "location", "operator": "one_of", "value": ["北京"],
             "source_text": "必须在北京"}
        ],
    }


class TestMemoryIntentClassification:
    def test_view_terms_route_to_memory_view(self):
        for text in ("查看记忆", "我的记忆", "你记住了什么", "看看记忆"):
            assert (
                classify_dialogue_intent(text, user_messages=[text])
                is DialogueMode.MEMORY_VIEW
            )

    def test_clear_terms_route_to_memory_clear(self):
        for text in ("清除记忆", "删除记忆", "忘掉我", "确认清除记忆"):
            assert (
                classify_dialogue_intent(text, user_messages=[text])
                is DialogueMode.MEMORY_CLEAR
            )

    def test_natural_mentions_of_memory_do_not_intercept(self):
        # 访谈中的自然表达含"记忆"一词但不含完整触发词组 → 不拦截
        for text in (
            "我对这个方向没什么记忆了",
            "高中记忆里的实验室",
            "记忆方法对科研有用吗",
        ):
            assert (
                classify_dialogue_intent(text, user_messages=[text])
                is DialogueMode.NONE
            )


class TestFormatMemoryListing:
    def test_empty_listing_is_honest(self):
        with SessionLocal() as db:
            text = format_memory_listing(db, f"nobody_{uuid4().hex}")
        assert "没有保存任何长期记忆" in text
        assert "未确认的内容不会写入" in text

    def test_listing_shows_whitelisted_rows_with_labels(self):
        student_id = f"stu_{uuid4().hex}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student_id, portrait=_portrait_dict()
            )
            text = format_memory_listing(db, student_id)
        assert "共 4 条" in text  # 研究兴趣 + 研究方式 + 硬性条件 + 确认标记
        assert "研究兴趣：自然语言处理" in text
        assert "硬性条件：必须在北京" in text
        assert "回复「清除记忆」" in text


class TestMemoryDialogueDispatch:
    def test_view_returns_listing(self):
        principal = _principal()
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db,
                student_id=principal.subject_id,
                portrait=_portrait_dict(),
            )
            dispatched = asyncio.run(_dispatch_dialogue_mode(
                db,
                intent=DialogueMode.MEMORY_VIEW,
                latest_user="查看记忆",
                session_id=f"s_{uuid4().hex}",
                student_id=principal.subject_id,
                portrait=None,
                principal=principal,
            ))
        assert dispatched is not None
        content, attachments = dispatched
        assert attachments == ()
        assert "研究兴趣：自然语言处理" in content

    def test_clear_requires_explicit_confirmation(self):
        principal = _principal()
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db,
                student_id=principal.subject_id,
                portrait=_portrait_dict(),
            )
            dispatched = asyncio.run(_dispatch_dialogue_mode(
                db,
                intent=DialogueMode.MEMORY_CLEAR,
                latest_user="清除记忆",
                session_id=f"s_{uuid4().hex}",
                student_id=principal.subject_id,
                portrait=None,
                principal=principal,
            ))
        assert dispatched is not None
        # 未确认 → 只提示范围与确认指令，不删除
        assert MEMORY_CLEAR_CONFIRMATION in dispatched[0]
        with SessionLocal() as db:
            listing = format_memory_listing(db, principal.subject_id)
        assert "共 4 条" in listing

    def test_confirmed_clear_deletes_and_reports_count(self):
        principal = _principal()
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db,
                student_id=principal.subject_id,
                portrait=_portrait_dict(),
            )
            dispatched = asyncio.run(_dispatch_dialogue_mode(
                db,
                intent=DialogueMode.MEMORY_CLEAR,
                latest_user=MEMORY_CLEAR_CONFIRMATION,
                session_id=f"s_{uuid4().hex}",
                student_id=principal.subject_id,
                portrait=None,
                principal=principal,
            ))
        assert dispatched is not None
        assert "已清除 4 条长期记忆" in dispatched[0]
        assert "访谈与匹配记录不受影响" in dispatched[0]
        with SessionLocal() as db:
            assert clear_memories(db, principal.subject_id) == 0  # 已删净

    def test_clear_on_empty_memory_is_honest(self):
        principal = _principal()
        with SessionLocal() as db:
            dispatched = asyncio.run(_dispatch_dialogue_mode(
                db,
                intent=DialogueMode.MEMORY_CLEAR,
                latest_user=MEMORY_CLEAR_CONFIRMATION,
                session_id=f"s_{uuid4().hex}",
                student_id=principal.subject_id,
                portrait=None,
                principal=principal,
            ))
        assert dispatched is not None
        assert "没有需要清除的长期记忆" in dispatched[0]
