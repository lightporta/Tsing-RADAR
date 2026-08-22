"""《访谈引擎修复方案》8 项修复的验收测试（v4.2.1）。

验收口径（与修复方案一致，见 docs/访谈引擎修复方案验收记录）：
- P0-1 幽灵硬约束：澄清环发「确认画像」后 constraints 为空，不再生成
  "确认画像"类草案；匹配前第三层消毒丢弃幽灵值；>3 条视为污染整批忽略。
- P0-2 边界澄清死循环：一次「无」→ 下一轮出画像卡；负向整句不入档；
  「确认」无结构化草案 → 放弃不循环；同一澄清提问连续 3 次无进展 → 强制闭合。
- P1-3 回声环：澄清环「确认画像」短路闭合边界，下一轮出画像卡。
- P1-4 SSE 收尾：finish_reason + data: [DONE] 必达。
- P1-5 延迟：单选作答不调用 LLM 增强。
- P2-6 画像字段污染：开场白/命令/疑问整句清洗后再入档。
- P2-7 发问去重：全流程每维度恰好问一次、顺序固定。
- P2-8 无候选兜底：空结果给「放宽 / 换方向：XXX / 目录」引导（每会话一次）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.questionnaire_session import QuestionnaireSession

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


def _reach_boundary() -> dict:
    """前五维完成，停在硬约束题（修复方案中"边界澄清环节"的起点）。"""
    state = _start()
    for answer in (
        "自然语言处理、对话系统",
        "理论与原理",
        "给方向后自主探索",
        "学术深造，计划读博",
        "愿意探索少有人做的高风险新方向",
    ):
        state = _answer(state["session_id"], answer)
    assert state["current_question"]["dimension"] == "hard_constraints"
    return state


def _chat_flow(claim: str, user_contents: list[str]) -> list[str]:
    """同一 claim（持久主体）逐轮发消息到 QXD 会话，返回每轮回复文本。"""
    messages: list[dict] = []
    replies: list[str] = []
    for content in user_contents:
        messages.append({"role": "user", "content": content})
        response = client.post(
            "/v1/chat/completions",
            headers=_qxd_headers(claim),
            json={"messages": messages, "stream": False},
        )
        assert response.status_code == 200
        reply = response.json()["choices"][0]["message"]["content"]
        replies.append(reply)
        messages.append({"role": "assistant", "content": reply})
    return replies


# —— P0-1 / P0-2 / P1-3：硬约束边界 ——


def test_boundary_single_no_lands_on_profile_card_next_turn():
    """P0-2 验收：边界澄清环节回复一次「无」→ 下一轮直接出画像卡。"""
    state = _reach_boundary()
    closed = _answer(state["session_id"], "无")
    assert closed["status"] == "awaiting_confirmation"
    assert closed["needs_clarification"] is False
    assert closed["profile"]["hard_constraints"] == []
    assert closed["profile"]["draft_hard_constraints"] == []
    assert closed["profile"]["unresolved_hard_constraints"] == []
    assert "可编辑画像" in closed["assistant_message"]


@pytest.mark.parametrize(
    "negative",
    (
        "没有硬约束，所有条件都只是一般偏好",
        "没有不可妥协条件",
        "无硬约束",
    ),
)
def test_negative_sentence_never_creates_drafts(negative: str):
    """P0-1/P0-2：负向整句不再生成"幽灵草案"，边界直接闭合。"""
    state = _reach_boundary()
    closed = _answer(state["session_id"], negative)
    assert closed["profile"]["hard_constraints"] == []
    assert closed["profile"]["draft_hard_constraints"] == []
    assert closed["profile"]["unresolved_hard_constraints"] == []
    assert closed["needs_clarification"] is False
    assert closed["status"] == "awaiting_confirmation"


def test_confirm_signal_during_clarification_closes_boundary():
    """P1-3 验收：澄清环发「确认画像」→ 草案清空、边界闭合，下一轮画像卡。

    同时是 P0-1 的来源白名单：确认指令绝不变成幽灵约束。
    """
    state = _reach_boundary()
    state = _answer(state["session_id"], "只能北京")
    assert state["profile"]["draft_hard_constraints"]
    assert state["needs_clarification"] is True

    closed = _answer(state["session_id"], "确认画像")
    assert closed["profile"]["hard_constraints"] == []
    assert closed["profile"]["draft_hard_constraints"] == []
    assert closed["profile"]["unresolved_hard_constraints"] == []
    assert closed["needs_clarification"] is False
    assert closed["status"] == "awaiting_confirmation"
    assert "可编辑画像" in closed["assistant_message"]

    confirmed = _answer(state["session_id"], "确认画像")
    assert confirmed["status"] == "confirmed"
    assert confirmed["recommend_ready"] is True


def test_confirm_signal_during_clarification_keeps_confirmed_constraints():
    """P0-1 来源白名单：已确认的硬约束在「确认画像」短路时保留，不误清。"""
    state = _reach_boundary()
    state = _answer(state["session_id"], "只能北京；每周至少三天")
    state = _answer(state["session_id"], "确认")
    assert state["profile"]["hard_constraints"][0]["field"] == "location"
    assert state["profile"]["hard_constraints"][0]["value"] == ["北京"]

    closed = _answer(state["session_id"], "确认画像")
    assert len(closed["profile"]["hard_constraints"]) == 1
    assert closed["profile"]["draft_hard_constraints"] == []
    assert closed["status"] == "awaiting_confirmation"


def test_junk_during_clarification_drops_current_draft():
    """P0-2：澄清环内态度词（随便/不知道）放弃当前草案，不反复追问。"""
    state = _reach_boundary()
    state = _answer(state["session_id"], "只能北京")
    assert state["profile"]["draft_hard_constraints"]

    dropped = _answer(state["session_id"], "随便")
    assert dropped["profile"]["draft_hard_constraints"] == []
    assert dropped["profile"]["unresolved_hard_constraints"] == []
    assert dropped["status"] == "awaiting_confirmation"


def test_confirm_on_unstructured_draft_drops_instead_of_looping():
    """P0-2：对无结构化形态的草案说「确认」→ 放弃该草案，不再死循环。"""
    state = _reach_boundary()
    state = _answer(state["session_id"], "希望研究自然语言处理")
    assert state["profile"]["unresolved_hard_constraints"]

    dropped = _answer(state["session_id"], "确认")
    assert dropped["profile"]["draft_hard_constraints"] == []
    assert dropped["profile"]["unresolved_hard_constraints"] == []
    assert dropped["status"] == "awaiting_confirmation"


def test_clarification_stall_cap_force_closes_boundary():
    """P0-2 轮次硬限制：同一澄清提问连续 3 次无进展 → 强制闭合边界。"""
    state = _reach_boundary()
    state = _answer(state["session_id"], "只能北京")
    assert state["needs_clarification"] is True

    first = _answer(state["session_id"], "今天天气怎么样")
    assert first["needs_clarification"] is True
    second = _answer(state["session_id"], "今天天气怎么样")
    assert second["needs_clarification"] is True

    stalled = _answer(state["session_id"], "今天天气怎么样")
    assert stalled["profile"]["draft_hard_constraints"] == []
    assert stalled["needs_clarification"] is False
    assert stalled["status"] == "awaiting_confirmation"
    assert "不再追问" in stalled["assistant_message"]


# —— P0-1 第三层：匹配前消毒 ——


def test_parse_hard_constraints_drops_junk_values():
    """P0-1 第三层：幽灵值在匹配前被直接丢弃，绝不参与硬过滤。"""
    from app.services.matching import parse_hard_constraints

    parsed = parse_hard_constraints(
        {
            "hard_constraints": [
                {"field": "location", "operator": "one_of", "value": ["北京"]},
                {"field": "location", "operator": "one_of", "value": ["确认画像"]},
            ],
            "draft_hard_constraints": [],
            "unresolved_hard_constraints": [],
        }
    )
    assert len(parsed.constraints) == 1
    assert parsed.constraints[0].value == ["北京"]


def _confirmed_with_constraint() -> str:
    """走完访谈并确认一条硬约束（地点=北京），返回 session_id。"""
    state = _reach_boundary()
    state = _answer(state["session_id"], "只能北京")
    state = _answer(state["session_id"], "确认")
    assert state["status"] == "awaiting_confirmation"
    state = _answer(state["session_id"], "确认画像")
    assert state["status"] == "confirmed"
    assert state["recommend_ready"] is True
    return state["session_id"]


def test_run_confirmed_match_relax_and_topic_override(monkeypatch):
    """P2-8：放宽/换方向参数按预期改本次匹配口径（画像本身不改写）。"""
    from app.services import match_application as match_app

    session_id = _confirmed_with_constraint()
    captured: dict = {}

    def fake_match(mentors, portrait, config=None):
        captured["portrait"] = portrait
        return SimpleNamespace(items=[], meta={"status": "ok"})

    monkeypatch.setattr(match_app, "match_mentors", fake_match)
    with SessionLocal() as db:
        session = db.get(QuestionnaireSession, session_id)
        match_app.run_confirmed_match(
            db,
            session_id=session_id,
            student_id=session.student_id,
            relax_hard_constraints=True,
            extra_topic_tags=["大模型"],
        )
    assert captured["portrait"]["hard_constraints"] == []
    assert "大模型" in captured["portrait"]["research_interests"]


def test_run_confirmed_match_overload_guard(monkeypatch):
    """P0-1 第二层：已确认硬约束 >3 条视为污染，匹配前整批忽略。"""
    from app.services import match_application as match_app

    state = _reach_boundary()
    edited = client.patch(
        f"/api/interviews/{state['session_id']}/profile",
        headers=STUDENT_HEADERS,
        json={
            "expected_version": state["profile_version"],
            "hard_constraints": [
                {"field": "location", "operator": "one_of", "value": ["北京"]},
                {
                    "field": "weekly_commitment_days",
                    "operator": "minimum",
                    "value": ["3"],
                },
                {"field": "degree_stage", "operator": "one_of", "value": ["博士"]},
                {"field": "language", "operator": "one_of", "value": ["英语"]},
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
    ).json()
    assert confirmed["status"] == "confirmed"

    captured: dict = {}

    def fake_match(mentors, portrait, config=None):
        captured["portrait"] = portrait
        return SimpleNamespace(items=[], meta={"status": "ok"})

    monkeypatch.setattr(match_app, "match_mentors", fake_match)
    with SessionLocal() as db:
        session = db.get(QuestionnaireSession, state["session_id"])
        match_app.run_confirmed_match(
            db,
            session_id=session.session_id,
            student_id=session.student_id,
        )
    assert captured["portrait"]["hard_constraints"] == []


# —— P2-6 画像字段污染 / P2-7 发问去重 ——


def test_interest_openers_are_cleaned_not_stored_verbatim():
    """P2-6：开场白整句不再整句入档（命令句式剔除、前缀后缀剥离）。"""
    state = _start()
    state = _answer(state["session_id"], "我是计算机系的、AI、帮我推荐导师")
    assert state["profile"]["research_interests"] == ["计算机系", "AI"]
    assert state["current_question"]["dimension"] == "research_mode"


def test_question_form_interest_is_not_stored():
    """P2-6：疑问句式不入档，回到同一题（不吸收为研究兴趣）。"""
    state = _start()
    state = _answer(state["session_id"], "机器学习怎么入门")
    assert state["profile"]["research_interests"] == []
    assert state["current_question"]["dimension"] == "research_interests"


def test_interview_asks_each_dimension_once_no_repeats():
    """P2-7：确定性状态机发问不重复、不跳问（全流程 6 题各一次）。"""
    state = _start()
    asked: list[str] = []
    answers = {
        "research_interests": "自然语言处理、对话系统",
        "research_mode": "理论与原理",
        "mentorship_style": "给方向后自主探索",
        "career_orientation": "学术深造，计划读博",
        "innovation_risk": "愿意探索少有人做的高风险新方向",
    }
    for _ in range(8):
        dimension = state["current_question"]["dimension"]
        asked.append(dimension)
        state = _answer(
            state["session_id"],
            "无" if dimension == "hard_constraints" else answers[dimension],
        )
        if state["status"] == "awaiting_confirmation":
            break
    assert state["status"] == "awaiting_confirmation"
    assert asked == [
        "research_interests",
        "research_mode",
        "mentorship_style",
        "career_orientation",
        "innovation_risk",
        "hard_constraints",
    ]


# —— P1-4 SSE 收尾 / P1-5 单选跳过增强 / P2-8 无候选兜底 ——

_CONFIRMED_FLOW_ANSWERS = (
    "自然语言处理、对话系统",
    "理论与原理",
    "给方向后自主探索",
    "学术深造，计划读博",
    "愿意探索少有人做的高风险新方向",
    "无",
    "确认画像",
)


def test_sse_stream_always_terminates_with_done():
    """P1-4 验收：SSE 流始终以 finish_reason=stop + data: [DONE] 收尾。"""
    claim = f"fixplan-sse-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    data_lines = [
        line for line in response.text.splitlines() if line.startswith("data:")
    ]
    assert data_lines[-1] == "data: [DONE]"
    finish = json.loads(data_lines[-2][len("data:"):].strip())
    assert finish["choices"][0]["finish_reason"] == "stop"


def test_single_choice_turn_skips_llm_enhancement(monkeypatch):
    """P1-5：单选作答绝不调用 LLM 增强（消除串行等待，≤10s 验收）。"""
    from app.api.v1 import chat as chat_module

    calls: list[str] = []
    real_render = chat_module.render_interview_reply

    async def spy(*args, **kwargs):
        calls.append("render")
        return await real_render(*args, **kwargs)

    monkeypatch.setattr(chat_module, "render_interview_reply", spy)

    claim = f"fixplan-skip-{uuid.uuid4()}"
    replies = _chat_flow(claim, list(_CONFIRMED_FLOW_ANSWERS[:-1]))
    # 增强只允许出现在硬约束文本题那一轮（第 6 轮）：前 4 轮单选、第 1 轮
    # 自由文本但下一题是单选（按下一题判定）→ 全部跳过；第 6 轮「无」后
    # 进入画像卡（needs_confirmation）也不再增强。全程恰好 1 次调用。
    assert len(calls) == 1, "仅硬约束文本轮允许调用 LLM 增强"
    assert "可编辑画像" in replies[5]


def test_no_candidate_fallback_card_shown_once_after_confirmation():
    """P2-8 验收：无候选时给兜底引导（放宽/换方向/目录），每会话仅一次。"""
    claim = f"fixplan-card-{uuid.uuid4()}"
    replies = _chat_flow(claim, list(_CONFIRMED_FLOW_ANSWERS))
    # 第 6 轮「无」→ 画像卡
    assert "可编辑画像" in replies[5]
    # 第 7 轮「确认画像」→ 空候选 + 兜底引导
    card = replies[6]
    assert "暂无通过审核的数据" in card
    assert "「放宽」" in card
    assert "「换方向" in card
    assert "https://www.tsingradar.com.cn" in card
    # 卡片只出现一次：随后的跑题消息给能力引导，不再重复卡片
    off_topic = _chat_flow(claim, ["今天天气怎么样"])[-1]
    assert "当前没有同时通过硬约束与召回阈值" not in off_topic


def test_relax_and_topic_override_rerun_labeled():
    """P2-8：放宽/换方向重跑按本次口径标注，且兜底卡不重复刷屏。"""
    claim = f"fixplan-relax-{uuid.uuid4()}"
    replies = _chat_flow(claim, list(_CONFIRMED_FLOW_ANSWERS))
    assert "「放宽」" in replies[6]

    relax = _chat_flow(claim, ["放宽"])[-1]
    assert "已按「放宽」忽略硬性条件重新匹配" in relax
    assert "当前没有同时通过硬约束与召回阈值" not in relax

    override = _chat_flow(claim, ["换方向：大模型"])[-1]
    assert "已按「大模型」方向重新匹配" in override
