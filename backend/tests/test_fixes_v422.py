"""v4.2.2 回归验收测试（《问题清单_统一文档》+《v4.2.1线上回归报告》）。

覆盖清单：
- 回归问题1：单选问题的句子回答 → 选项关键词降级（不再回声环/画像损坏）
- 回归问题2：画像方向与导师目录重合不足 → 召回归零 reason（不再误报硬约束）
- 回归问题3：放宽重跑后空态文案区分归零类型（不再显示"硬约束"误导文案）
- 回归问题4：会话级 KV（no_candidate_card_shown）在模式状态写入后保留
- 回归问题5：QXD_CHAT_STREAM_ENABLED=false 时 stream=true 也返回非流式 JSON
- P0-J：推荐后路由黑洞（复合指令拆分 / 导师知识 / 平台 FAQ / 告别 / 能力引导）
- P0-B 残留：硬约束重复确认不重复入档；软性子句不生成低置信草案
- P1-N：多子句边界答案不把操作指令引用成约束值
- P1-K①：off_topic 误杀（"放手探索"→autonomous）
- P1-K②：研究兴趣题"无"→ 熔断推进（interest_statement=暂无明确方向）
- P1-O：套磁邮件误触发（"去联系导师了"不生成邮件；"怎么联系导师"走 FAQ）
- P1-D：推荐后闲聊不编造（"今天挺热的呢"→能力引导）
- P2-Q：维度权重输入（"很在意经费和产出效率"→funding+efficiency）
- P2-E：英文输入解析（"I'm interested in NLP and machine learning"）
- P1-H/P1-I：长句/承接词残留清洗（"顺便我也想研究推荐系统"→推荐系统）
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.schemas.interview import InterviewDimension, StudentPortrait
from app.schemas.matching import RankingConfig
from app.services import dialogue_intent, off_topic
from app.services.interview import (
    _MENTORSHIP_STYLE_KEYWORDS,
    _apply_target_answer,
    _draft_constraints,
    _interest_tags,
    _is_interest_decline,
)
from app.services.match_application import run_confirmed_match
from app.services.matching import match_mentors

client = TestClient(app)
STUDENT_HEADERS: dict[str, str] = {}
QXD_AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"

_CAPTURED_AT = "2026-08-01T00:00:00+08:00"


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


# —— 证据化候选 fixture（带 verified public_fact provenance，匹配流水线可用） ——


def _candidate(
    advisor_id: str,
    name: str,
    dept: str,
    keywords: list[str],
    *,
    field: str = "",
) -> dict:
    """构造通过 _source_backed_value 校验的最小候选。"""
    provenance: dict[str, list[dict]] = {}
    for field_name in ("research_keywords", "field", "tags", "research_summary"):
        provenance[field_name] = [
            {
                "evidence_id": str(uuid.uuid4()),
                "source_type": "public_fact",
                "source_ref": f"https://example.edu/{advisor_id}",
                "captured_at": _CAPTURED_AT,
                "verification_status": "verified",
                "confidence": 1.0,
                "method": "test",
                "method_version": "1.0",
            }
        ]
    return {
        "advisor_id": advisor_id,
        "name": name,
        "dept": dept,
        "resource_type": "verified_mentor_profile",
        "identity_status": "verified",
        "recommendation_eligibility": "eligible",
        "research_keywords": keywords,
        "field": field or keywords[0],
        "tags": keywords,
        "research_summary": f"{name}的研究方向包括{'、'.join(keywords)}",
        "provenance": provenance,
    }


# —— 回归问题1：单选问题的句子回答 → 关键词降级 ——


def test_single_choice_sentence_answer_maps_to_option():
    """"倾向先深造读研，之后看情况"→academic（句子级关键词，不再整体作废）。"""
    profile: dict = {}
    _apply_target_answer(
        profile, InterviewDimension.CAREER_ORIENTATION, "倾向先深造读研，之后看情况"
    )
    assert profile["career_orientation"] == "academic"
    _apply_target_answer(
        profile, InterviewDimension.MENTORSHIP_STYLE, "平衡，导师给方向我执行"
    )
    assert profile["mentorship_style"] == "balanced"


def test_free_explore_is_not_killed_as_off_topic():
    """P1-K①："放手探索"→autonomous，且不被 off_topic 误杀。"""
    profile: dict = {}
    _apply_target_answer(profile, InterviewDimension.MENTORSHIP_STYLE, "放手探索")
    assert profile["mentorship_style"] == "autonomous"
    # 选择题检测不把它当跑题（关键词表里直接有"放手"）
    assert not off_topic.detect_off_topic_choice(
        "放手探索",
        tuple(
            keyword
            for _, keywords in _MENTORSHIP_STYLE_KEYWORDS
            for keyword in keywords
        ),
    )


# —— P1-K②：研究兴趣题"无"→ 熔断推进（不回声环） ——


def test_no_answer_melts_down_research_interests():
    assert _is_interest_decline("无")
    assert _is_interest_decline("没想好")
    assert not _is_interest_decline("不确定在 AI 还是 CV")
    profile: dict = {}
    _apply_target_answer(profile, InterviewDimension.RESEARCH_INTERESTS, "无")
    assert profile["research_interests"] == []
    assert profile["interest_statement"] == "暂无明确方向"


def test_no_answer_advances_interview_state_machine():
    """端到端：研究兴趣题回"无"→ 状态机推进到下一题，不再复读同题。"""
    state = _start()
    state = _answer(state["session_id"], "无")
    assert state["profile"]["interest_statement"] == "暂无明确方向"
    assert state["current_question"]["dimension"] != "research_interests"


# —— P2-E：英文输入解析（不再被 12 字符上限整体丢弃） ——


def test_english_interest_sentence_extracts_direction_tags():
    tags = _interest_tags("I'm interested in NLP and machine learning")
    assert "NLP" in tags
    assert "machine learning" in tags
    assert len(tags) >= 2


def test_english_answer_advances_interview_state_machine():
    state = _start()
    state = _answer(
        state["session_id"], "I'm interested in NLP and machine learning"
    )
    assert any("nlp" in tag.lower() for tag in state["profile"]["research_interests"])
    assert state["current_question"]["dimension"] != "research_interests"


# —— P1-H/P1-I：长句/承接词残留清洗 ——


def test_joiner_leading_clause_cleanup():
    tags = _interest_tags("顺便我也想研究推荐系统")
    assert tags and "推荐系统" in tags


# —— P2-Q：维度权重输入 ——


def test_implicit_dimension_attention_single_message_two_dims():
    hits = dialogue_intent.detect_implicit_dimension_attention(
        ["很在意经费和产出效率"]
    )
    assert dialogue_intent.DIMENSION_FUNDING in hits
    assert dialogue_intent.DIMENSION_EFFICIENCY in hits


# —— P1-O：套磁邮件误触发 ——


def test_contacting_mentor_is_not_consult_email():
    mode = dialogue_intent.classify_dialogue_intent(
        "去联系导师了", user_messages=[]
    )
    assert mode != dialogue_intent.DialogueMode.CONSULT_EMAIL
    assert (
        dialogue_intent.classify_dialogue_intent(
            "我去问下老师", user_messages=[]
        )
        != dialogue_intent.DialogueMode.CONSULT_EMAIL
    )


def test_how_to_contact_mentor_routes_to_faq():
    mode = dialogue_intent.classify_dialogue_intent(
        "怎么联系导师", user_messages=[]
    )
    assert mode == dialogue_intent.DialogueMode.CONSULT_FAQ


# —— P1-N / P0-B：软性子句不生成草案、操作指令不被引用成约束值 ——


def test_soft_clause_and_structural_command_not_drafted():
    drafts = _draft_constraints(
        "必须在北京，工作氛围好一点，换方向：电池安全"
    )
    fields = [
        draft.proposed_constraint.field.value
        for draft in drafts
        if draft.proposed_constraint is not None
    ]
    # 只有"必须在北京"生成草案；软性/操作指令被过滤
    assert fields == ["location"]


# —— 回归问题2：召回归零 reason（matching 层） ——


def test_recall_zero_generates_recall_reason_not_constraint_reason():
    candidates = [
        _candidate("T0001", "甲导师", "自动化系", ["电池", "储能"]),
        _candidate("T0002", "乙导师", "计算机系", ["芯片设计"]),
    ]
    portrait = {
        "research_interests": ["大模型对齐"],
        "interest_statement": "对大模型对齐感兴趣",
        "hard_constraints": [],
        "draft_hard_constraints": [],
        "unresolved_hard_constraints": [],
    }
    result = match_mentors(
        candidates,
        portrait,
        RankingConfig(),
    )
    assert result.items == []
    assert result.meta["zero_result_reason"]
    assert "召回" in result.meta["zero_result_reason"]
    # 不是约束归零格式（约束归零以"约束“"开头并点名字段）
    assert "约束“" not in result.meta["zero_result_reason"]


# —— 回归问题3：放宽重跑后空态文案区分归零类型 ——


def _run_with_candidates(monkeypatch, candidates, relax_hard: bool) -> str:
    portrait = StudentPortrait(
        research_interests=["大模型对齐"],
        interest_statement="对大模型对齐感兴趣",
        hard_constraints=[],
        draft_hard_constraints=[],
        unresolved_hard_constraints=[],
    )
    monkeypatch.setattr(
        "app.services.match_application.load_match_candidates",
        lambda: candidates,
    )
    # 真实种子文件是 0 记录（no_published_data 短路），必须桩成有发布数据
    monkeypatch.setattr(
        "app.services.match_application.mentor_data_summary",
        lambda: {
            "total_records": len(candidates),
            "published_records": len(candidates),
            "withheld_records": 0,
            "catalog_records": 0,
            "verified_profile_records": len(candidates),
            "match_candidate_records": len(candidates),
            "policy": "formal_verified_profiles_only",
        },
    )
    monkeypatch.setattr(
        "app.services.match_application.confirmed_portrait",
        lambda db, **kwargs: portrait,
    )
    outcome = run_confirmed_match(
        db=object(),  # type: ignore[arg-type]  # confirmed_portrait 已桩化
        session_id="sess-v422",
        student_id=None,
        relax_hard_constraints=relax_hard,
    )
    assert outcome.status == "no_match"
    return outcome.message


def test_no_match_message_names_recall_zero(monkeypatch):
    message = _run_with_candidates(
        monkeypatch,
        [_candidate("T0001", "甲导师", "自动化系", ["电池", "储能"])],
        relax_hard=False,
    )
    assert "召回" in message
    assert "约束“" not in message  # 不是约束归零文案
    assert "换方向" in message


def test_relaxed_rerun_no_longer_blames_hard_constraints(monkeypatch):
    """回归问题3：放宽重跑仍归零 → 明确说与硬约束无关，可换方向重试。"""
    message = _run_with_candidates(
        monkeypatch,
        [_candidate("T0001", "甲导师", "自动化系", ["电池", "储能"])],
        relax_hard=True,
    )
    assert "召回" in message or "重合" in message
    assert "无关" in message  # 不再把归零归咎于硬约束
    assert "换方向" in message


def test_constraint_zero_still_names_the_constraint(monkeypatch):
    """约束归零仍给出具体约束名（与召回归零区分）。"""
    portrait = StudentPortrait(
        research_interests=["电池"],
        interest_statement="对电池储能感兴趣",
        hard_constraints=[
            {
                "field": "location",
                "operator": "one_of",
                "value": ["成都"],
                "source_text": "必须在成都",
            }
        ],
        draft_hard_constraints=[],
        unresolved_hard_constraints=[],
    )
    monkeypatch.setattr(
        "app.services.match_application.load_match_candidates",
        lambda: [_candidate("T0001", "甲导师", "自动化系", ["电池"])],
    )
    monkeypatch.setattr(
        "app.services.match_application.mentor_data_summary",
        lambda: {
            "match_candidate_records": 1,
            "total_records": 1,
            "published_records": 1,
            "withheld_records": 0,
            "catalog_records": 0,
            "verified_profile_records": 1,
            "policy": "formal_verified_profiles_only",
        },
    )
    monkeypatch.setattr(
        "app.services.match_application.confirmed_portrait",
        lambda db, **kwargs: portrait,
    )
    outcome = run_confirmed_match(
        db=object(),  # type: ignore[arg-type]
        session_id="sess-v422-loc",
        student_id=None,
    )
    assert outcome.status == "no_match"
    assert "约束“" in outcome.message
    assert "地点" in outcome.message


# —— 回归问题4：会话级 KV 在模式状态写入后保留 ——


def test_session_kv_preserved_across_mode_state_upsert():
    from app.services.dialogue_state_store import (
        clear_dialogue_state,
        get_dialogue_state,
        mark_session_flag,
        upsert_dialogue_state,
    )

    with SessionLocal() as db:
        mark_session_flag(
            db,
            session_id="sess-kv-1",
            student_id="student-v422",
            key="no_candidate_card_shown",
        )
        upsert_dialogue_state(
            db,
            session_id="sess-kv-1",
            student_id="student-v422",
            mode="match_refine",
            state={"shown_batch": ["T0001"]},
        )
        state = get_dialogue_state(
            db, session_id="sess-kv-1", student_id="student-v422"
        )
        assert state is not None
        assert state["no_candidate_card_shown"] is True
        assert state["shown_batch"] == ["T0001"]

        clear_dialogue_state(
            db, session_id="sess-kv-1", student_id="student-v422"
        )
        state = get_dialogue_state(
            db, session_id="sess-kv-1", student_id="student-v422"
        )
        assert state is not None
        assert state["no_candidate_card_shown"] is True
        assert "shown_batch" not in state


# —— 回归问题5：非流式开关（QXD_CHAT_STREAM_ENABLED=false） ——


def test_stream_disabled_returns_nonstream_json(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "QXD_CHAT_STREAM_ENABLED", False)
    claim = f"qxd-nostream-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    # 非 SSE：Content-Type 是 JSON 而非 text/event-stream
    assert "text/event-stream" not in response.headers.get("content-type", "")
    payload = response.json()
    assert payload["choices"][0]["message"]["content"]
    assert "finish_reason" in payload["choices"][0]


# —— P0-J：推荐后路由黑洞（chat 主链路桩到 recommend_ready） ——


def _patch_recommend_ready(monkeypatch, *, mentor_knowledge=None):
    """桩到 recommend_ready 状态 + 空匹配结果，专注断言通用问答回退分支。"""
    from types import SimpleNamespace

    import app.api.v1.chat as qxd_chat
    from app.services.match_application import MatchApplicationOutcome

    # 旧确定性兜底用例：关闭 v4.3.0 全 Agent 化编排（Agent 钩子会先于
    # 兜底链接管非结构化消息），本 helper 全部用例均专注旧兜底链覆盖。
    monkeypatch.setattr(qxd_chat.settings, "AGENT_ORCHESTRATION_ENABLED", False)
    monkeypatch.setattr(
        qxd_chat, "sync_user_transcript", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        qxd_chat,
        "state_response",
        lambda _session: SimpleNamespace(
            recommend_ready=True,
            assistant_message="画像已确认。",
        ),
    )
    monkeypatch.setattr(
        qxd_chat,
        "run_confirmed_match",
        lambda *_args, **_kwargs: MatchApplicationOutcome(
            status="no_match",
            items=[],
            meta={"match_candidate_records": 1, "interview_status": "confirmed"},
            message="暂无候选。",
            questions=[],
        ),
    )
    monkeypatch.setattr(
        qxd_chat, "confirmed_portrait", lambda *_args, **_kwargs: None
    )
    # 匹配结果上下文下的「第 N 个」追问短路（隔离 DB 会话依赖）
    monkeypatch.setattr(
        qxd_chat,
        "_ordinal_follows_match_results",
        lambda *_args, **_kwargs: True,
    )
    if mentor_knowledge is not None:
        monkeypatch.setattr(qxd_chat, "query_mentor_knowledge", mentor_knowledge)


def _recommend_reply(claim: str, content: str) -> str:
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    return response.json()["choices"][0]["message"]["content"]


def test_post_match_faq_question_gets_algorithm_answer(monkeypatch):
    _patch_recommend_ready(monkeypatch)
    reply = _recommend_reply(
        f"qxd-faq-{uuid.uuid4()}", "契合度分数怎么算的"
    )
    assert "满分 100" in reply
    assert "加权" in reply


def test_post_match_mentor_question_gets_knowledge_or_honest_unknown(monkeypatch):
    _patch_recommend_ready(monkeypatch, mentor_knowledge=None)
    reply = _recommend_reply(
        f"qxd-mentor-{uuid.uuid4()}", "王测试的研究方向是什么"
    )
    # 松散问法（无"老师"后缀）走推荐后回退：未收录 → 诚实拒答，绝不编造
    assert "未收录" in reply or "公开评价" in reply


def test_post_match_mentor_question_known_name_renders_knowledge(monkeypatch):
    _patch_recommend_ready(
        monkeypatch,
        mentor_knowledge=lambda name: {
            "name": "王测试",
            "department_header": "计算机系",
            "review_count": 12,
            "stats": {"positive": 8, "neutral": 3, "negative": 1},
            "summary": "公开存档匿名评价聚合测试",
        },
    )
    reply = _recommend_reply(
        f"qxd-mentor-known-{uuid.uuid4()}", "王测试的研究方向是什么"
    )
    assert "王测试" in reply
    assert "匿名" in reply or "参考" in reply


def test_post_match_farewell_gets_farewell_reply(monkeypatch):
    _patch_recommend_ready(monkeypatch)
    reply = _recommend_reply(f"qxd-bye-{uuid.uuid4()}", "谢谢，再见")
    assert "再见" in reply


def test_post_match_smalltalk_not_fabricated(monkeypatch):
    """P1-D：推荐后闲聊不编造答案，给能力引导。"""
    _patch_recommend_ready(monkeypatch)
    reply = _recommend_reply(f"qxd-chat-{uuid.uuid4()}", "今天挺热的呢")
    assert "热" not in reply or "天气" not in reply
    assert "导师" in reply or "匹配" in reply


def test_post_match_compound_command_gets_split_guide(monkeypatch):
    _patch_recommend_ready(monkeypatch)
    reply = _recommend_reply(
        f"qxd-compound-{uuid.uuid4()}", "换方向：电池安全，顺便改指导偏好"
    )
    assert "一次只发一条指令" in reply


def test_post_match_ordinal_with_thanks_is_not_compound(monkeypatch):
    """"第1个，谢谢"不算复合指令，放行走既有「第 N 个」流程。"""
    import app.api.v1.chat as qxd_chat
    from app.services.match_application import MatchApplicationOutcome

    _patch_recommend_ready(monkeypatch)
    monkeypatch.setattr(
        qxd_chat,
        "run_confirmed_match",
        lambda *_args, **_kwargs: MatchApplicationOutcome(
            status="matched",
            items=[
                {
                    "advisor_id": "T0001",
                    "name": "测试导师",
                    "dept": "计算机系",
                    "score": 85.0,
                    "fit_score": 90.0,
                    "evidence_coverage": 0.8,
                    "evidence_confidence": 0.9,
                    "research_keywords": ["大模型"],
                    "explanation": {
                        "supporting_evidence": [
                            {
                                "statement": "在 NLP 方向有公开积累",
                                "citations": [
                                    {"citation": "论文·2024", "source": "public"}
                                ],
                            }
                        ],
                        "counter_evidence": [],
                        "uncertainties": [],
                        "questions_to_verify": [],
                    },
                }
            ],
            meta={"match_candidate_records": 1, "interview_status": "confirmed"},
            message="找到 1 个证据化候选。",
            questions=[],
        ),
    )
    reply = _recommend_reply(f"qxd-ordinal-{uuid.uuid4()}", "第1个，谢谢")
    assert "一次只发一条指令" not in reply
    assert "测试导师" in reply


def test_post_match_how_to_contact_mentor_routes_faq_not_email(monkeypatch):
    _patch_recommend_ready(monkeypatch)
    reply = _recommend_reply(
        f"qxd-contact-{uuid.uuid4()}", "怎么联系导师"
    )
    # P1-O：走 FAQ 官方渠道指引，绝不生成邮件初稿
    assert "初稿" not in reply
    assert "官方" in reply


# —— 附：P0-B 残留 —— 硬约束重复确认不重复入档（经 _process_constraint_followup）


def test_duplicate_hard_constraint_confirmation_deduped():
    """P0-B：同一约束两次确认循环后只入档一条（field+operator+value 去重）。"""
    from app.services.interview import _process_constraint_followup

    def _cycle_with(profile: dict) -> None:
        # 第二轮：同一约束再次进入澄清环并确认
        profile["draft_hard_constraints"] = [
            {
                "source_text": "必须在北京",
                "proposed_constraint": {
                    "field": "location",
                    "operator": "one_of",
                    "value": ["北京"],
                    "source_text": "必须在北京",
                },
                "parsing_confidence": 0.95,
                "confirmation_prompt": "确认？",
            }
        ]
        profile["unresolved_hard_constraints"] = ["必须在北京"]
        assert _process_constraint_followup(profile, "确认")

    profile = {
        "draft_hard_constraints": [],
        "unresolved_hard_constraints": [],
        "hard_constraints": [],
    }
    _cycle_with(profile)
    assert len(profile["hard_constraints"]) == 1
    # 同一约束再次确认 → 去重，不入第二条
    _cycle_with(profile)
    assert len(profile["hard_constraints"]) == 1
    assert profile["hard_constraints"][0]["field"] == "location"
