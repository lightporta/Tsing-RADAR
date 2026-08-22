"""A3 持久化动态访谈、画像编辑与确认门测试。"""

from __future__ import annotations

import json
import hashlib
import hmac
import uuid
from datetime import datetime, timezone

import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.questionnaire_session import QuestionnaireSession
from app.models.identity import ExternalIdentity, IdentitySession
from app.services.interview import (
    create_session,
    answer_session,
    state_response,
    upsert_portrait_field,
)
from app.schemas.interview import InterviewStatus
from app.api.v1 import interview as interview_api

client = TestClient(app)
STUDENT_HEADERS: dict[str, str] = {}
QXD_AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"


def _qxd_headers(claim: str) -> dict[str, str]:
    signature = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        claim.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        **QXD_AUTH,
        "X-QXD-End-User-Id": claim,
        "X-QXD-End-User-Signature": signature,
    }


def _qxd_session_id(claim: str, conversation: str) -> str:
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
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tsing-radar:qxd-interview:{mapping.subject_id}:{conversation}",
        )
    )


@pytest.fixture(autouse=True)
def _web_session_headers():
    response = client.get("/api/session")
    assert response.status_code == 200
    STUDENT_HEADERS.clear()
    STUDENT_HEADERS["X-CSRF-Token"] = client.cookies["tsing_radar_csrf"]


def _start() -> dict:
    response = client.post("/api/interviews", headers=STUDENT_HEADERS, json={})
    assert response.status_code == 200
    return response.json()


def _answer(session_id: str, answer: str) -> dict:
    response = client.post(
        f"/api/interviews/{session_id}/answers",
        headers=STUDENT_HEADERS,
        json={"answer": answer},
    )
    assert response.status_code == 200
    return response.json()


def test_glm_enhancement_retry_is_owner_bound_and_state_preserving(monkeypatch):
    started = _start()
    answered = _answer(started["session_id"], "我关注自然语言处理")
    with SessionLocal() as db:
        before = db.get(QuestionnaireSession, started["session_id"])
        before_messages = json.loads(json.dumps(before.messages, ensure_ascii=False))
        before_version = before.profile_version

    async def available(**kwargs):
        assert kwargs["user_message"] == "我关注自然语言处理"
        assert kwargs["fixed_reply"]
        return SimpleNamespace(status="available", text="收到，我们继续。", provider="glm")

    monkeypatch.setattr(interview_api, "enhance_interview_reply", available)
    response = client.post(
        f'/api/interviews/{answered["session_id"]}/enhancement-retry',
        headers=STUDENT_HEADERS,
        json={},
    )
    assert response.status_code == 200
    assert response.json() == {
        "session_id": answered["session_id"],
        "text": "收到，我们继续。",
        "provider": "glm",
        "status": "available",
    }
    with SessionLocal() as db:
        after = db.get(QuestionnaireSession, started["session_id"])
        assert after.messages == before_messages
        assert after.profile_version == before_version

    async def unavailable(**_kwargs):
        return SimpleNamespace(status="unavailable", text=None, provider="glm")

    monkeypatch.setattr(interview_api, "enhance_interview_reply", unavailable)
    failed = client.post(
        f'/api/interviews/{answered["session_id"]}/enhancement-retry',
        headers=STUDENT_HEADERS,
        json={},
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "code": "glm_unavailable",
        "message": "GLM 暂不可用，访谈状态未改变，请稍后重试。",
        "retryable": True,
        "provider": "glm",
    }


def _complete_interview() -> dict:
    state = _start()
    session_id = state["session_id"]
    for answer in (
        "自然语言处理、对话系统",
        "理论与原理",
        "给方向后自主探索",
        "学术深造，计划读博",
        "愿意探索少有人做的高风险新方向",
        "无",
    ):
        state = _answer(session_id, answer)
    assert state["status"] == "awaiting_confirmation"
    assert state["recommend_ready"] is False
    assert state["missing_dimensions"] == []
    return state


def test_interview_asks_exactly_one_question_at_a_time():
    state = _start()
    assert state["status"] == "in_progress"
    assert state["current_question"]["dimension"] == "research_interests"
    assert state["current_question"]["prompt"].count("？") == 1

    for answer in (
        "自然语言处理",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
    ):
        state = _answer(state["session_id"], answer)
        assert state["current_question"] is not None
        assert state["current_question"]["prompt"].count("？") == 1

    state = _answer(state["session_id"], "无")
    assert state["current_question"] is None
    assert state["assistant_message"].count("？") == 1


def test_high_information_answer_skips_dimensions_already_learned():
    state = client.post(
        "/api/interviews",
        headers=STUDENT_HEADERS,
        json={
            "initial_answer": (
                "我想研究机器人控制，偏工程落地，希望自主探索，"
                "计划进大厂就业，也喜欢成熟稳妥路线"
            )
        },
    ).json()
    assert state["profile"]["research_interests"]
    assert state["profile"]["research_mode"] == "engineering"
    assert state["profile"]["mentorship_style"] == "autonomous"
    assert state["profile"]["career_orientation"] == "industry"
    assert state["profile"]["innovation_risk"] == "mature"
    assert state["current_question"]["dimension"] == "hard_constraints"


def test_balanced_mentorship_does_not_fill_innovation_risk():
    state = _start()
    for answer in (
        "自然语言处理",
        "理论与原理",
        "平衡指导",
    ):
        state = _answer(state["session_id"], answer)

    assert state["profile"]["mentorship_style"] == "balanced"
    assert state["profile"]["innovation_risk"] is None

    state = _answer(state["session_id"], "计划继续学术深造")
    assert state["current_question"]["dimension"] == "innovation_risk"


def test_profile_persists_can_be_edited_and_requires_reconfirmation():
    state = _complete_interview()
    session_id = state["session_id"]

    persisted = client.get(
        f"/api/interviews/{session_id}",
        headers=STUDENT_HEADERS,
    )
    assert persisted.status_code == 200
    assert persisted.json()["profile"] == state["profile"]

    stale_version = state["profile_version"]
    edited = client.patch(
        f"/api/interviews/{session_id}/profile",
        headers=STUDENT_HEADERS,
        json={
            "expected_version": stale_version,
            "career_orientation": "industry",
        },
    )
    assert edited.status_code == 200
    edited_state = edited.json()
    assert edited_state["profile"]["career_orientation"] == "industry"
    assert edited_state["status"] == "awaiting_confirmation"
    assert edited_state["recommend_ready"] is False

    conflict = client.patch(
        f"/api/interviews/{session_id}/profile",
        headers=STUDENT_HEADERS,
        json={
            "expected_version": stale_version,
            "career_orientation": "academic",
        },
    )
    assert conflict.status_code == 409

    confirmed = client.post(
        f"/api/interviews/{session_id}/confirm",
        headers=STUDENT_HEADERS,
        json={"expected_version": edited_state["profile_version"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["recommend_ready"] is True


def test_natural_language_constraints_require_explicit_structured_confirmation():
    state = _start()
    for answer in (
        "自然语言处理",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
        "只能北京；每周至少三天",
    ):
        state = _answer(state["session_id"], answer)
    assert state["needs_clarification"] is True
    assert state["recommend_ready"] is False
    assert state["profile"]["hard_constraints"] == []
    assert len(state["profile"]["draft_hard_constraints"]) == 2
    assert state["profile"]["unresolved_hard_constraints"] == []
    assert len(state["clarification_questions"]) == 2
    assert "地点必须在“北京”" in state["assistant_message"]
    assert "field|" not in state["assistant_message"]

    blocked = client.post(
        f"/api/interviews/{state['session_id']}/confirm",
        headers=STUDENT_HEADERS,
        json={"expected_version": state["profile_version"]},
    )
    assert blocked.status_code == 409
    assert "硬约束仍需澄清" in blocked.json()["detail"]

    edited = client.patch(
        f"/api/interviews/{state['session_id']}/profile",
        headers=STUDENT_HEADERS,
        json={
            "expected_version": state["profile_version"],
            "hard_constraints": [
                {
                    "field": "location",
                    "operator": "one_of",
                    "value": ["北京"],
                    "source_text": "只能北京",
                },
                {
                    "field": "weekly_commitment_days",
                    "operator": "minimum",
                    "value": ["3"],
                    "source_text": "每周至少三天",
                },
            ],
            "draft_hard_constraints": [],
            "unresolved_hard_constraints": [],
        },
    ).json()
    assert edited["needs_clarification"] is False
    confirmed = client.post(
        f"/api/interviews/{state['session_id']}/confirm",
        headers=STUDENT_HEADERS,
        json={"expected_version": edited["profile_version"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["recommend_ready"] is True


@pytest.mark.parametrize(
    "rejection",
    (
        "无",
        "以上均为一般偏好，不作为硬约束；没有不可妥协条件",
    ),
)
def test_constraint_clarification_accepts_explicit_rejection(rejection: str):
    state = _start()
    for answer in (
        "自然语言处理",
        "理论与原理",
        "平衡指导",
        "学术深造",
        "成熟稳妥路线",
        "希望研究自然语言处理",
    ):
        state = _answer(state["session_id"], answer)

    assert state["needs_clarification"] is True
    assert state["profile"]["draft_hard_constraints"]

    rejected = _answer(state["session_id"], rejection)

    assert rejected["profile"]["hard_constraints"] == []
    assert rejected["profile"]["draft_hard_constraints"] == []
    assert rejected["profile"]["unresolved_hard_constraints"] == []
    assert rejected["needs_clarification"] is False
    assert rejected["status"] == "awaiting_confirmation"


def test_chat_correction_updates_complete_profile_before_confirmation():
    state = _complete_interview()
    revised = _answer(state["session_id"], "指导偏好改为高频具体指导")
    assert revised["profile"]["mentorship_style"] == "high_guidance"
    assert revised["status"] == "awaiting_confirmation"
    assert revised["recommend_ready"] is False

    generic = _answer(state["session_id"], "可以了")
    assert generic["status"] == "awaiting_confirmation"

    confirmed = _answer(state["session_id"], "确认画像")
    assert confirmed["status"] == "confirmed"
    assert confirmed["recommend_ready"] is True


def test_match_is_blocked_until_confirmed_then_uses_server_profile():
    state = _complete_interview()
    session_id = state["session_id"]

    blocked = client.post(
        "/api/match",
        headers=STUDENT_HEADERS,
        json={
            "interest": "客户端试图绕过",
            "session_id": session_id,
            "portrait": {"research_interests": ["未确认覆盖值"]},
        },
    )
    assert blocked.status_code == 409

    confirmed = client.post(
        f"/api/interviews/{session_id}/confirm",
        headers=STUDENT_HEADERS,
        json={"expected_version": state["profile_version"]},
    ).json()
    matched = client.post(
        "/api/match",
        headers=STUDENT_HEADERS,
        json={
            "interest": "客户端试图绕过",
            "session_id": session_id,
            "portrait": {"research_interests": ["未确认覆盖值"]},
        },
    )
    assert matched.status_code == 200
    assert matched.json()["data"] == []
    assert matched.json()["status"] == "no_published_data"
    assert "暂无通过审核的数据" in matched.json()["message"]
    assert matched.json()["meta"]["interview_status"] == "confirmed"
    assert confirmed["profile"]["research_interests"] == [
        "自然语言处理",
        "对话系统",
    ]


def test_legacy_confirmed_natural_constraints_return_needs_clarification():
    owner_session = _start()
    session_id = str(uuid.uuid4())
    with SessionLocal() as db:
        owner = db.get(QuestionnaireSession, owner_session["session_id"])
        assert owner is not None
        session = QuestionnaireSession(
            session_id=session_id,
            student_id=owner.student_id,
            messages=[],
            portrait={
                "research_interests": ["自然语言处理"],
                "interest_statement": "自然语言处理",
                "research_mode": "engineering",
                "mentorship_style": "balanced",
                "career_orientation": "academic",
                "innovation_risk": "balanced",
                "hard_constraints": ["只能北京"],
            },
            status="confirmed",
            current_question_id=None,
            answered_dimensions=[],
            profile_version=1,
            confirmed_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.commit()

    response = client.post(
        "/api/match",
        headers=STUDENT_HEADERS,
        json={"session_id": session_id},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "needs_clarification"
    assert detail["questions"]


def test_interview_session_access_is_scoped_to_student():
    state = _start()
    other = TestClient(app)
    assert other.get("/api/session").status_code == 200
    response = other.get(
        f"/api/interviews/{state['session_id']}",
    )
    assert response.status_code == 403


def test_incomplete_profile_cannot_be_confirmed():
    state = _start()
    response = client.post(
        f"/api/interviews/{state['session_id']}/confirm",
        headers=STUDENT_HEADERS,
        json={"expected_version": state["profile_version"]},
    )
    assert response.status_code == 409
    assert "尚未完成" in response.json()["detail"]


def test_internal_sse_returns_persisted_structured_state():
    response = client.post(
        "/api/v1/llm/chat",
        headers=STUDENT_HEADERS,
        json={
            "messages": [
                {"role": "user", "content": "自然语言处理、知识图谱"}
            ]
        },
    )
    assert response.status_code == 200
    frames = [
        json.loads(line.removeprefix("data:").strip())
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]
    finish = next(frame for frame in frames if frame.get("finish"))
    assert finish["status"] == "in_progress"
    assert finish["profile"]["research_interests"] == [
        "自然语言处理",
        "知识图谱",
    ]
    assert finish["current_question"]["dimension"] == "research_mode"
    assert finish["recommend_ready"] is False

    persisted = client.get(
        f"/api/interviews/{finish['session_id']}",
        headers=STUDENT_HEADERS,
    )
    assert persisted.status_code == 200
    assert persisted.json()["profile"] == finish["profile"]


def test_qxd_conversation_uses_persistent_interview_core():
    external_user = f"qxd-test-{uuid.uuid4()}"
    headers = _qxd_headers(external_user)
    first = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": external_user,
            "messages": [{"role": "user", "content": "你好"}],
            "stream": False,
        },
    )
    assert first.status_code == 200
    first_content = first.json()["choices"][0]["message"]["content"]
    assert "研究主题" in first_content

    second = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": external_user,
            "messages": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": first_content},
                {"role": "user", "content": "自然语言处理"},
            ],
            "stream": False,
        },
    )
    assert second.status_code == 200
    assert "理论与原理" in second.json()["choices"][0]["message"]["content"]

    expected_session_id = _qxd_session_id(external_user, external_user)
    db = SessionLocal()
    try:
        persisted = db.get(QuestionnaireSession, expected_session_id)
        assert persisted is not None
        assert persisted.portrait["research_interests"] == ["自然语言处理"]
        assert sum(
            1 for message in persisted.messages if message["role"] == "user"
        ) == 2
    finally:
        db.close()


def test_qxd_without_stable_user_never_reuses_same_opening_session():
    db = SessionLocal()
    try:
        before = (
            db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.student_id.like("qreq_%"))
            .count()
        )
    finally:
        db.close()

    request = {
        "messages": [{"role": "user", "content": "你好"}],
        "stream": False,
    }
    assert client.post(
        "/v1/chat/completions",
        headers=QXD_AUTH,
        json=request,
    ).status_code == 200
    assert client.post(
        "/v1/chat/completions",
        headers=QXD_AUTH,
        json=request,
    ).status_code == 200

    db = SessionLocal()
    try:
        after = (
            db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.student_id.like("qreq_%"))
            .count()
        )
        assert after == before + 2
    finally:
        db.close()


@pytest.mark.parametrize(
    ("answer", "field", "expected"),
    [
        ("我偏理论证明", "research_mode", "theory"),
        ("我偏工程落地", "research_mode", "engineering"),
        ("希望导师手把手具体指导", "mentorship_style", "high_guidance"),
        ("希望自主自由探索", "mentorship_style", "autonomous"),
        ("以后计划读博做学术", "career_orientation", "academic"),
        ("以后想进大厂就业", "career_orientation", "industry"),
        ("想参与航天大国重器", "career_orientation", "national_mission"),
        ("愿意做少有人探索的高风险方向", "innovation_risk", "pioneering"),
        ("更喜欢成熟稳妥路线", "innovation_risk", "mature"),
        ("风险与确定性希望平衡", "innovation_risk", "balanced"),
    ],
)
def test_dialogue_signal_regressions(answer: str, field: str, expected: str):
    db = SessionLocal()
    try:
        session = create_session(db, student_id="regression")
        session = answer_session(
            db,
            session_id=session.session_id,
            answer=answer,
            student_id="regression",
        )
        assert state_response(session).profile.model_dump()[field] == expected
    finally:
        db.close()


def test_upsert_portrait_field_after_confirm_requires_reconfirmation():
    """v3.1.6 对话端口回填：已确认画像被改动 → 回落 awaiting_confirmation。"""
    state = _complete_interview()
    session_id = state["session_id"]
    confirmed = client.post(
        f"/api/interviews/{session_id}/confirm",
        headers=STUDENT_HEADERS,
        json={"expected_version": state["profile_version"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    with SessionLocal() as db:
        before = db.get(QuestionnaireSession, session_id)
        assert state_response(before).recommend_ready is True
        before_version = before.profile_version

        upsert_portrait_field(
            db,
            session_id=session_id,
            student_id=before.student_id,
            changes={"research_mode": "engineering"},
        )
        after = db.get(QuestionnaireSession, session_id)
        after_state = state_response(after)
        assert after_state.profile.research_mode == "engineering"
        assert after_state.status == InterviewStatus.AWAITING_CONFIRMATION
        assert after_state.recommend_ready is False
        assert after.profile_version == before_version + 1


def test_upsert_portrait_field_merges_interests_dedup_and_fills_statement():
    """v3.1.6 对话端口回填：research_interests 合并去重 + 自动补兴趣陈述。"""
    db = SessionLocal()
    try:
        session = create_session(db, student_id="upsert-merge")
        sid = session.session_id
        upsert_portrait_field(
            db,
            session_id=sid,
            student_id="upsert-merge",
            changes={"research_interests": ["大模型 / 大语言模型", "自然语言处理"]},
        )
        upsert_portrait_field(
            db,
            session_id=sid,
            student_id="upsert-merge",
            changes={"research_interests": ["自然语言处理", "芯片 / 集成电路"]},
        )
        profile = state_response(
            db.get(QuestionnaireSession, sid)
        ).profile
        # 合并去重且保持既有顺序
        assert profile.research_interests == [
            "大模型 / 大语言模型",
            "自然语言处理",
            "芯片 / 集成电路",
        ]
        # 兴趣陈述只在为空时自动补一次（忠实于首次所选方向）
        assert profile.interest_statement == (
            "我对大模型 / 大语言模型、自然语言处理方向感兴趣。"
        )

        # 上限 8：追加到 9 个时截断（保留既有值）
        overflow = [f"追加方向{i}" for i in range(1, 10)]
        upsert_portrait_field(
            db,
            session_id=sid,
            student_id="upsert-merge",
            changes={"research_interests": overflow},
        )
        assert len(state_response(db.get(QuestionnaireSession, sid)).profile.research_interests) == 8
    finally:
        db.close()


def test_upsert_portrait_field_creates_session_when_missing():
    """v3.1.6 对话端口回填：会话不存在时创建（不要求先做访谈）。"""
    db = SessionLocal()
    try:
        session = upsert_portrait_field(
            db,
            session_id="s-upsert-new",
            student_id="upsert-new",
            changes={"research_mode": "theory"},
        )
        assert session.status == InterviewStatus.IN_PROGRESS.value
        profile = state_response(session).profile
        assert profile.research_mode == "theory"
        assert profile.research_interests == []
    finally:
        db.close()
