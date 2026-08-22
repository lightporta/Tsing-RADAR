"""v4.0.0 长期记忆（user_memories）：白名单写入 + 召回 + 跨会话注入测试。

v4.3.0 阶段二追加：沟通阶段键（communication_stage）——枚举写入口、
只前进不回退、确定性事件触发（套磁邮件/匹配展示/站内投递）、
表达层无写路径、隐私查看带标签。
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.identity import ExternalIdentity
from app.models.private_document import PrivateDocument
from app.models.recruitment import Recruitment
from app.services.interview import answer_session, create_session
from app.services.memory_service import (
    STAGE_CONTACTING,
    STAGE_INITIAL,
    STAGE_INTERVIEWED,
    clear_memories,
    format_memory_listing,
    format_memory_summary,
    list_memories,
    recall_memories,
    remember_communication_stage,
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


# —— v4.3.0 阶段二：沟通阶段（communication_stage）——


class TestCommunicationStage:
    def test_forward_only_progression(self):
        """验收②-①：只前进不回退，同级幂等。"""
        student = f"stage-p-{uuid.uuid4()}"
        with SessionLocal() as db:
            assert (
                remember_communication_stage(
                    db, student_id=student, stage=STAGE_INITIAL
                )
                is True
            )
            # 同级幂等
            assert (
                remember_communication_stage(
                    db, student_id=student, stage=STAGE_INITIAL
                )
                is False
            )
            # 前进
            assert (
                remember_communication_stage(
                    db, student_id=student, stage=STAGE_CONTACTING
                )
                is True
            )
            # 回退拒绝
            assert (
                remember_communication_stage(
                    db, student_id=student, stage=STAGE_INITIAL
                )
                is False
            )
            assert (
                remember_communication_stage(
                    db, student_id=student, stage=STAGE_INTERVIEWED
                )
                is True
            )
            assert (
                remember_communication_stage(
                    db, student_id=student, stage=STAGE_CONTACTING
                )
                is False
            )
            assert recall_memories(db, student)["communication_stage"] == "已约谈"

    def test_rejects_non_enum_values(self):
        """验收②-①（写入口封闭）：LLM/用户自由文本无法经本函数写库。"""
        student = f"stage-r-{uuid.uuid4()}"
        with SessionLocal() as db:
            for bad in ("用户说随便写", "", "已约谈（大概）", "联系中 "):
                with pytest.raises(ValueError):
                    remember_communication_stage(
                        db, student_id=student, stage=bad
                    )
            assert recall_memories(db, student) == {}

    def test_stage_flows_into_summary_and_listing(self):
        """验收②-①：摘要缀在画像事实后；隐私查看带「沟通阶段」标签。"""
        student = f"stage-s-{uuid.uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            remember_communication_stage(
                db, student_id=student, stage=STAGE_INTERVIEWED
            )
            summary = format_memory_summary(db, student)
            listing = format_memory_listing(db, student)
        assert summary.endswith("已约谈")
        assert "只能北京、已约谈" in summary
        assert "沟通阶段：已约谈" in listing
        entries = list(
            e for e in _entries(student) if e["memory_key"] == "communication_stage"
        )
        assert len(entries) == 1
        assert entries[0]["source"] == "communication_event"

    def test_portrait_confirm_never_touches_stage(self):
        """画像确认写入不产生/不重置沟通阶段；重新确认不覆盖阶段。"""
        student = f"stage-t-{uuid.uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            assert "communication_stage" not in recall_memories(db, student)
            remember_communication_stage(
                db, student_id=student, stage=STAGE_CONTACTING
            )
            # 画像重新确认（覆盖画像行）——阶段行不受影响
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            memories = recall_memories(db, student)
        assert memories["communication_stage"] == "联系中"
        assert memories["research_interests"] == "自然语言处理、对话系统"

    def test_expression_layer_has_no_stage_write_path(self):
        """验收②-①（架构护栏）：表达层模块不存在任何记忆写路径。"""
        import app.services.chat_expression as chat_expression
        import app.services.tools_registry as tools_registry

        source = inspect.getsource(chat_expression)
        assert "remember_communication_stage" not in source
        assert "UserMemory" not in source
        assert "remember_confirmed_portrait" not in source
        # 工具注册表（LLM 可调用面）无任何阶段写工具
        for name in tools_registry._TOOL_DEFINITIONS:
            assert "stage" not in name
            assert "remember" not in name


def _entries(student: str) -> list[dict[str, str]]:
    with SessionLocal() as db:
        return list_memories(db, student)


def _subject_id_for(claim: str) -> str:
    fingerprint = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        f"identity-map:{claim}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with SessionLocal() as db:
        mapping = (
            db.query(ExternalIdentity)
            .filter(ExternalIdentity.claim_fingerprint == fingerprint)
            .one()
        )
        return mapping.subject_id


def _qxd_post(claim: str, conversation: str, messages: list[str]):
    return client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "model": "tsing-radar",
            "user": conversation,
            "messages": [{"role": "user", "content": c} for c in messages],
            "stream": False,
        },
    )


def test_chat_email_event_writes_contacting_stage():
    """验收②-① 黑盒：套磁邮件生成成功 → 沟通阶段「联系中」，查看可见。"""
    claim = f"stage-mail-{uuid.uuid4().hex[:8]}"
    response = _qxd_post(claim, "conv-1", ["帮我写一封套磁邮件给李琦老师"])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "套磁信初稿" in content
    subject_id = _subject_id_for(claim)
    with SessionLocal() as db:
        assert recall_memories(db, subject_id)["communication_stage"] == "联系中"
    # 隐私查看可见标签
    view = _qxd_post(claim, "conv-1", ["查看记忆"])
    assert view.status_code == 200
    assert "沟通阶段：联系中" in view.json()["choices"][0]["message"]["content"]


def test_chat_match_event_sets_initial_stage(monkeypatch):
    """验收②-① 黑盒：匹配候选展示 → 沟通阶段「初选」（确定性事件）。"""
    from app.api.v1 import chat as qxd_chat

    def fake_run(db, *, session_id, student_id, **_kwargs):
        return SimpleNamespace(
            status="matched",
            items=[{"advisor_id": f"adv-{uuid.uuid4().hex[:6]}", "name": "测试导师"}],
            meta={"match_candidate_records": 1},
            message="ok",
            questions=[],
        )

    def fake_format(outcome, *, profile, advisor_ratings=None, user_dimension_scores=None):
        return "测试匹配结果"

    monkeypatch.setattr(qxd_chat, "run_confirmed_match", fake_run)
    monkeypatch.setattr(qxd_chat, "format_match_outcome", fake_format)

    claim = f"stage-match-{uuid.uuid4().hex[:8]}"
    turns = [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
        "无",
        "确认画像",
    ]
    response = _qxd_post(claim, "conv-1", turns)
    assert response.status_code == 200
    assert "测试匹配结果" in response.json()["choices"][0]["message"]["content"]
    subject_id = _subject_id_for(claim)
    with SessionLocal() as db:
        memories = recall_memories(db, subject_id)
    assert memories["communication_stage"] == "初选"
    # 画像白名单事实照常写入
    assert memories["research_interests"] == "自然语言处理、对话系统"


def test_in_app_application_event_advances_to_interviewed(monkeypatch):
    """验收②-①：站内投递成功 → 沟通阶段「已约谈」（Web 链路确定性事件）。"""
    import app.services.applications as applications_service

    monkeypatch.setattr(applications_service, "load_mentors", lambda: [])
    subject = f"stage-app-{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        recruitment = Recruitment(
            recruit_id=f"rec-{uuid.uuid4().hex[:8]}",
            publisher_id="reviewer_stage_test",
            publisher_type="advisor",
            type="科研助理",
            title="阶段测试招募",
            req="仅用于沟通阶段测试",
            major="自然语言处理",
            deadline=date(2027, 1, 1),
            is_urgent=False,
            review_status="verified",
            publication_status="published",
            authorization_basis="explicit_consent",
            provenance={},
            governance={},
            quarantined_fields={},
        )
        document = PrivateDocument(
            document_id=f"doc-{uuid.uuid4().hex[:8]}",
            owner_subject_id=subject,
            original_name="resume.pdf",
            stored_name=f"stage-{uuid.uuid4().hex}.pdf",
            extension="pdf",
            media_type="application/pdf",
            size_bytes=100,
            sha256="0" * 64,
            status="ready",
            scan_status="clean",
        )
        db.add_all([recruitment, document])
        db.commit()
        recruit_id = recruitment.recruit_id
        document_id = document.document_id

        idempotency_key = f"stage-app-{uuid.uuid4()}"
        application = applications_service.create_in_app_application(
            db,
            subject_id=subject,
            recruit_id=recruit_id,
            document_id=document_id,
            confirmed=True,
            idempotency_key=idempotency_key,
        )
        assert application.status == "submitted_in_app"
        assert recall_memories(db, subject)["communication_stage"] == "已约谈"

        # 重放同一 idempotency key：返回原投递，阶段保持「已约谈」（幂等不回退）
        replayed = applications_service.create_in_app_application(
            db,
            subject_id=subject,
            recruit_id=recruit_id,
            document_id=document_id,
            confirmed=True,
            idempotency_key=idempotency_key,
        )
        assert replayed.app_id == application.app_id
        assert recall_memories(db, subject)["communication_stage"] == "已约谈"


def test_stage_survives_until_clear(monkeypatch):
    """阶段与其他记忆同生共灭：清除记忆后阶段一并删除（隐私语义）。"""
    student = f"stage-c-{uuid.uuid4()}"
    with SessionLocal() as db:
        remember_confirmed_portrait(
            db, student_id=student, portrait=CONFIRMED_PORTRAIT
        )
        remember_communication_stage(
            db, student_id=student, stage=STAGE_CONTACTING
        )
        assert len(list_memories(db, student)) == 8  # 7 画像行 + 阶段行
        assert clear_memories(db, student) == 8
        assert recall_memories(db, student) == {}
