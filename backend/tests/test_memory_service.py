"""v4.0.0 长期记忆（user_memories）：白名单写入 + 召回 + 跨会话注入测试。"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.services.interview import answer_session, create_session
from app.services.memory_service import (
    clear_memories,
    format_memory_summary,
    list_memories,
    recall_memories,
    remember_confirmed_portrait,
)

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"

CONFIRMED_PORTRAIT = {
    "research_interests": ["自然语言处理", "对话系统"],
    "research_mode": "engineering",
    "mentorship_style": "high_guidance",
    "career_orientation": "industry",
    "innovation_risk": "mature",
    "hard_constraints": [
        {
            "field": "location",
            "operator": "one_of",
            "value": ["北京"],
            "source_text": "只能北京",
        }
    ],
}


def _qxd_headers(claim: str) -> dict[str, str]:
    signature = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        claim.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        **AUTH,
        "X-QXD-End-User-Id": claim,
        "X-QXD-End-User-Signature": signature,
    }


class TestMemoryService:
    def test_remember_writes_whitelist_rows(self):
        student = f"mem-w-{uuid.uuid4()}"
        with SessionLocal() as db:
            count = remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            assert count == 7  # 兴趣+四维+硬条件+确认标记
            memories = recall_memories(db, student)
        assert memories["research_interests"] == "自然语言处理、对话系统"
        assert memories["research_mode"] == "工程与落地"
        assert memories["mentorship_style"] == "高频具体指导"
        assert memories["career_orientation"] == "产业就业"
        assert memories["innovation_risk"] == "成熟路径"
        assert memories["hard_constraints"] == "只能北京"
        assert "portrait_confirmed" in memories

    def test_remember_ignores_non_whitelisted_keys(self):
        student = f"mem-g-{uuid.uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db,
                student_id=student,
                portrait={
                    **CONFIRMED_PORTRAIT,
                    "llm_guess": "用户可能喜欢量子计算",  # 未确认猜测绝不写入
                },
            )
            memories = recall_memories(db, student)
        assert "llm_guess" not in memories
        assert "quantum" not in " ".join(memories.values())

    def test_remember_upserts_on_reconfirm(self):
        student = f"mem-u-{uuid.uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            updated = {
                **CONFIRMED_PORTRAIT,
                "research_interests": ["计算机视觉"],
            }
            remember_confirmed_portrait(db, student_id=student, portrait=updated)
            memories = recall_memories(db, student)
            assert len(memories) == 7  # 覆盖而非新增
        assert memories["research_interests"] == "计算机视觉"
        assert memories["research_mode"] == "工程与落地"

    def test_unknown_student_is_empty(self):
        student = f"mem-empty-{uuid.uuid4()}"
        with SessionLocal() as db:
            assert recall_memories(db, student) == {}
            assert format_memory_summary(db, student) == ""
            assert list_memories(db, student) == []
            assert clear_memories(db, student) == 0

    def test_format_memory_summary_fact_only(self):
        student = f"mem-f-{uuid.uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            summary = format_memory_summary(db, student)
        assert "自然语言处理" in summary
        assert "工程与落地" in summary
        assert "产业就业" in summary
        # 无框架词：不含"已确认""记得"等表达层包装
        assert "已确认" not in summary

    def test_list_and_clear_memories(self):
        student = f"mem-c-{uuid.uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            entries = list_memories(db, student)
            assert len(entries) == 7
            assert all(
                {"memory_key", "memory_value", "source", "updated_at"}
                <= set(entry)
                for entry in entries
            )
            assert clear_memories(db, student) == 7
            assert recall_memories(db, student) == {}

    def test_confirmed_through_answer_session_writes_memories(self):
        """确认门通过（对话流程）即触发白名单写入，无需额外调用。"""
        student = f"mem-ai-{uuid.uuid4()}"
        session_id = str(uuid.uuid4())
        with SessionLocal() as db:
            create_session(db, student_id=student, session_id=session_id)
            for turn in [
                "自然语言处理、对话系统",
                "工程落地",
                "高频具体指导",
                "产业就业",
                "成熟稳妥路线",
                "只能北京、每周至少3天",
                "确认",
                "确认",
                "确认画像",
            ]:
                answer_session(
                    db, session_id=session_id, answer=turn, student_id=student
                )
            memories = recall_memories(db, student)
        assert memories.get("research_interests") == "自然语言处理、对话系统"
        assert memories.get("research_mode") == "工程与落地"
        assert memories.get("hard_constraints") == "只能北京、每周至少3天"
        assert "portrait_confirmed" in memories


def test_cross_session_memory_injected_into_fact_pack(monkeypatch):
    """会话 A 确认画像 → 会话 B（同主体）访谈回复注入已确认事实。"""
    from app.api.v1 import chat as qxd_chat
    from app.services.chat_expression import InterviewFactPack
    from app.services.llm import InterviewEnhancement

    claim = f"mem-x-{uuid.uuid4()}"
    headers = _qxd_headers(claim)

    def _post(conversation: str, messages: list[str]):
        return client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "tsing-radar",
                "user": conversation,
                "messages": [{"role": "user", "content": c} for c in messages],
                "stream": False,
            },
        )

    # 会话 A：完成访谈并确认（确认门通过 → 写入记忆）
    turns_a = [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
        "只能北京、每周至少3天",
        "确认",
        "确认",
        "确认画像",
    ]
    confirmed = _post("conv-a", turns_a)
    assert confirmed.status_code == 200
    # 确认后即进入匹配：诚实空态回复证明确认门已通过
    assert "暂无通过审核的数据" in confirmed.json()["choices"][0]["message"]["content"]

    # 会话 B（同主体新会话）：捕获注入表达层的 FactPack
    captured: dict = {}

    async def fake_render(fact_pack: InterviewFactPack):
        captured["summary"] = fact_pack.memory_summary
        return InterviewEnhancement(
            text="收到，我们继续。", provider="test", status="available"
        )

    monkeypatch.setattr(qxd_chat, "render_interview_reply", fake_render)
    started_b = _post("conv-b", ["自然语言处理"])
    assert started_b.status_code == 200
    assert started_b.json()["choices"][0]["message"]["content"] == "收到，我们继续。"
    summary = captured["summary"]
    assert "自然语言处理" in summary
    assert "工程与落地" in summary
    assert "只能北京" in summary
