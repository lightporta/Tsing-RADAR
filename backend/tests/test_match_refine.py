"""v3.1.7 匹配结果二次筛选测试：
换一批 / 缩小范围两问状态机 / 恢复完整结果 / 归零诚实 / 状态持久化。

真 SQLite DB（与 test_research_style 同模式）；run_confirmed_match 打桩
（match_refine 模块引用），专注断言状态机与约束构建行为。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.session import SessionLocal
from app.models.dialogue_state import DialogueSession
from app.schemas.interview import HardConstraint, StudentPortrait
from app.services import match_refine as refine
from app.services.dialogue_state_store import (
    get_dialogue_mode,
    get_dialogue_state,
    upsert_dialogue_state,
)
from app.services.match_application import MatchApplicationOutcome

_SESSION = {"session_id": "s-refine-test", "student_id": "stu-refine-test"}


@pytest.fixture(autouse=True)
def isolate_dialogue_sessions():
    """清理跨测试的二次筛选模式状态（dialogue_sessions）。"""
    yield
    with SessionLocal() as db:
        db.query(DialogueSession).delete(synchronize_session=False)
        db.commit()


def _item(advisor_id: str, name: str, **overrides) -> dict:
    """构造可渲染的匹配候选（format_match_item 所需字段齐全）。"""
    item = {
        "advisor_id": advisor_id,
        "name": name,
        "dept": "自动化系",
        "score": 80.0,
        "fit_score": 85.0,
        "evidence_coverage": 0.8,
        "evidence_confidence": 0.9,
        "explanation": {
            "supporting_evidence": [
                {
                    "statement": f"{name} 在相关方向有公开积累",
                    "citations": [{"citation": "主页·2025", "source": "public"}],
                }
            ],
            "counter_evidence": [],
            "uncertainties": [],
            "questions_to_verify": [],
        },
    }
    item.update(overrides)
    return item


def _outcome(*items: dict) -> MatchApplicationOutcome:
    return MatchApplicationOutcome(
        status="matched",
        items=list(items),
        meta={},
        message="找到证据化候选。",
        questions=[],
    )


def _patch_run(monkeypatch, calls: list):
    """把 match_refine.run_confirmed_match 桩成记录 extra_constraints 的假实现。"""

    def fake_run(_db, *, extra_constraints=None, **_kwargs):
        calls.append(list(extra_constraints or []))
        return _outcome(_item("T90001", "新批次导师"))

    monkeypatch.setattr(refine, "run_confirmed_match", fake_run)


# —— 纯函数 ——


def test_parse_topic_answer():
    assert refine.parse_topic_answer("大模型、多模态") == ["大模型", "多模态"]
    assert refine.parse_topic_answer("大模型, 多模态；机器人") == [
        "大模型",
        "多模态",
        "机器人",
    ]
    assert refine.parse_topic_answer("无") == []
    assert refine.parse_topic_answer("没有") == []
    assert refine.parse_topic_answer("") == []
    assert refine.parse_topic_answer("大模型、大模型") == ["大模型"]


def test_build_refine_constraints():
    constraints = refine.build_refine_constraints(
        ["T00001", "T00001", ""], ["大模型"], ["生物"]
    )
    assert constraints[0] == {
        "field": "advisor_id",
        "operator": "excludes",
        "value": ["T00001"],
        "source_text": "二次筛选：换一批（排除已展示候选）",
    }
    assert constraints[1]["operator"] == "contains"
    assert constraints[1]["value"] == ["大模型"]
    assert constraints[2]["operator"] == "excludes"
    assert constraints[2]["value"] == ["生物"]
    # 无条件不出约束（确定性空态）
    assert refine.build_refine_constraints([], [], []) == []


def test_persisted_refine_constraints_round_trip():
    with SessionLocal() as db:
        upsert_dialogue_state(
            db,
            mode=refine.MODE_MATCH_REFINE,
            state={
                "excluded_advisor_ids": ["T00001", "T00002"],
                "topic_include": ["大模型"],
                "topic_exclude": ["生物"],
            },
            **_SESSION,
        )
        constraints = refine.persisted_refine_constraints(db, **_SESSION)
        assert len(constraints) == 3
        fields = [(c["field"], c["operator"]) for c in constraints]
        assert ("advisor_id", "excludes") in fields
        assert ("research_topic", "contains") in fields
        assert ("research_topic", "excludes") in fields
        # 无状态 → 无附加约束
        assert refine.persisted_refine_constraints(
            db, session_id="s-other", student_id=_SESSION["student_id"]
        ) == []


# —— 状态持久化守卫 ——


def test_persist_shown_batch_records_and_keeps_filters():
    with SessionLocal() as db:
        upsert_dialogue_state(
            db,
            mode=refine.MODE_MATCH_REFINE,
            state={"excluded_advisor_ids": ["T00001"]},
            **_SESSION,
        )
        refine.persist_shown_batch(
            db, items=[_item("T00002", "导师二")], **_SESSION
        )
        state = get_dialogue_state(db, **_SESSION)
        assert state["last_shown_advisor_ids"] == ["T00002"]
        assert state["excluded_advisor_ids"] == ["T00001"]  # 保留既有过滤
    # 无状态行时创建（首次基础匹配即记录批次）
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00003", "导师三")], session_id="s-fresh",
            student_id=_SESSION["student_id"],
        )
        assert get_dialogue_mode(db, session_id="s-fresh",
                                 student_id=_SESSION["student_id"]) == refine.MODE_MATCH_REFINE


def test_persist_shown_batch_does_not_override_other_mode():
    from app.services.research_style import MODE_RESEARCH_STYLE

    with SessionLocal() as db:
        upsert_dialogue_state(
            db, mode=MODE_RESEARCH_STYLE, state={"step": 2}, **_SESSION
        )
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        state = get_dialogue_state(db, **_SESSION)
        assert state["step"] == 2  # 未被覆盖
        assert "last_shown_advisor_ids" not in state


# —— 换一批 ——


def test_change_batch_excludes_shown(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师"), _item("T00002", "旧导师二")],
            **_SESSION,
        )
        text = refine.handle_match_refine(db, latest_user="换一批", **_SESSION)
        assert text is not None
        assert "已排除已展示的 2 位候选" in text
        assert "新批次导师" in text
        # 排除集 = 已展示批次（一次换一批的会话内新增）
        assert calls[-1][0]["field"] == "advisor_id"
        assert calls[-1][0]["operator"] == "excludes"
        assert calls[-1][0]["value"] == ["T00001", "T00002"]
        # 本批已记录，供下一次换一批继续排除
        state = get_dialogue_state(db, **_SESSION)
        assert state["last_shown_advisor_ids"] == ["T90001"]
        assert state["excluded_advisor_ids"] == ["T00001", "T00002"]


def test_change_batch_accumulates_across_rounds(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        refine.handle_match_refine(db, latest_user="换一批", **_SESSION)
        refine.handle_match_refine(db, latest_user="换一批", **_SESSION)
        # 第二轮排除集 = 旧排除 + 上一批展示
        assert calls[-1][0]["value"] == ["T00001", "T90001"]


def test_change_batch_without_shown_batch_honest():
    with SessionLocal() as db:
        text = refine.handle_match_refine(db, latest_user="换一批", **_SESSION)
        assert text is not None
        assert "还没有已展示的候选可排除" in text
        assert "缩小范围" in text


# —— 缩小范围两问状态机 ——


def test_narrow_scope_two_questions_then_rerun(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        q1 = refine.handle_match_refine(db, latest_user="缩小范围", **_SESSION)
        assert q1 is not None and "集中在哪些方向" in q1
        q2 = refine.handle_match_refine(db, latest_user="大模型、多模态", **_SESSION)
        assert q2 is not None and "排除" in q2
        text = refine.handle_match_refine(db, latest_user="无", **_SESSION)
        assert text is not None
        assert "已按你的筛选条件重新匹配" in text
        # 排除集含已展示；CONTAINS 聚焦生效；Q2 答"无"不生成 EXCLUDES
        assert calls[-1][0]["field"] == "advisor_id"
        assert calls[-1][0]["value"] == ["T00001"]
        assert calls[-1][1]["field"] == "research_topic"
        assert calls[-1][1]["operator"] == "contains"
        assert calls[-1][1]["value"] == ["大模型", "多模态"]
        assert not any(
            c["field"] == "research_topic" and c["operator"] == "excludes"
            for c in calls[-1]
        )
        # 答题态已清、过滤态保留
        state = get_dialogue_state(db, **_SESSION)
        assert state["step"] is None
        assert state["topic_include"] == ["大模型", "多模态"]
        assert state["excluded_advisor_ids"] == ["T00001"]


def test_narrow_scope_include_and_exclude_topics(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        refine.handle_match_refine(db, latest_user="缩小范围", **_SESSION)
        refine.handle_match_refine(db, latest_user="无", **_SESSION)  # Q1 跳过
        refine.handle_match_refine(db, latest_user="生物、化学", **_SESSION)  # Q2
        assert calls[-1][1]["operator"] == "excludes"
        assert calls[-1][1]["value"] == ["生物", "化学"]
        assert len(calls[-1]) == 2  # 无 CONTAINS（Q1 答无）


# —— 取消 / 恢复 / 释放 ——


def test_cancel_keeps_filters(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        refine.handle_match_refine(db, latest_user="缩小范围", **_SESSION)
        cancel_text = refine.handle_match_refine(db, latest_user="取消", **_SESSION)
        assert cancel_text is not None
        assert "已退出二次筛选设置" in cancel_text
        state = get_dialogue_state(db, **_SESSION)
        assert state["step"] is None
        assert state["excluded_advisor_ids"] == ["T00001"]  # 排除集保留
        assert not calls  # 取消不触发重跑


def test_reset_clears_state_and_reruns_full(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        refine.handle_match_refine(db, latest_user="缩小范围", **_SESSION)
        refine.handle_match_refine(db, latest_user="大模型", **_SESSION)
        refine.handle_match_refine(db, latest_user="无", **_SESSION)
        text = refine.handle_match_refine(db, latest_user="恢复完整结果", **_SESSION)
        assert text is not None
        assert "已恢复完整结果" in text
        assert calls[-1] == []  # 无附加约束重跑全量
        state = get_dialogue_state(db, **_SESSION)
        assert not state.get("excluded_advisor_ids")
        assert not state.get("topic_include")
        assert not state.get("topic_exclude")


def test_zero_result_honest_text(monkeypatch):
    def fake_run(_db, *, extra_constraints=None, **_kwargs):
        return MatchApplicationOutcome(
            status="no_match",
            items=[],
            meta={},
            message="硬约束组合下没有候选通过全部过滤（zero result）。",
            questions=[],
        )

    monkeypatch.setattr(refine, "run_confirmed_match", fake_run)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        text = refine.handle_match_refine(db, latest_user="换一批", **_SESSION)
        assert text is not None
        assert "硬约束组合下没有候选通过全部过滤" in text
        assert "恢复完整结果" in text


def test_structural_intent_releases_answer_phase(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, calls)
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        refine.handle_match_refine(db, latest_user="缩小范围", **_SESSION)
        # 答题期收到「第 2 个」→ 释放回主流程（None），答题态清空
        assert (
            refine.handle_match_refine(
                db, latest_user="第 2 个", structural_match=True, **_SESSION
            )
            is None
        )
        state = get_dialogue_state(db, **_SESSION)
        assert state["step"] is None


def test_normal_message_released_when_not_answering():
    with SessionLocal() as db:
        refine.persist_shown_batch(
            db, items=[_item("T00001", "旧导师")], **_SESSION
        )
        assert refine.handle_match_refine(db, latest_user="谢谢", **_SESSION) is None


# —— run_confirmed_match extra_constraints 合并 ——


def test_run_confirmed_match_merges_extra_constraints(monkeypatch):
    from app.services import match_application as ma_module

    captured: dict = {}

    def fake_match_mentors(*, mentors, portrait, config=None):
        captured["portrait"] = portrait
        return SimpleNamespace(meta={"status": "matched"}, items=[{"advisor_id": "T00001"}])

    monkeypatch.setattr(
        ma_module,
        "confirmed_portrait",
        lambda *_args, **_kwargs: StudentPortrait(
            hard_constraints=[
                HardConstraint(
                    field="department", operator="one_of", value=["计算机系"]
                )
            ]
        ),
    )
    monkeypatch.setattr(ma_module, "match_mentors", fake_match_mentors)
    monkeypatch.setattr(
        ma_module,
        "mentor_data_summary",
        lambda: {"match_candidate_records": 3},
    )
    with SessionLocal() as db:
        outcome = ma_module.run_confirmed_match(
            db,
            session_id=_SESSION["session_id"],
            student_id=_SESSION["student_id"],
            extra_constraints=[
                {
                    "field": "advisor_id",
                    "operator": "excludes",
                    "value": ["T00001"],
                }
            ],
        )
        assert outcome.status == "matched"
        hard_constraints = captured["portrait"]["hard_constraints"]
        assert len(hard_constraints) == 2  # 画像既有约束 + 附加约束
        assert hard_constraints[-1]["field"] == "advisor_id"
        assert hard_constraints[-1]["operator"] == "excludes"
        # 不带附加约束 → 原样透传
        ma_module.run_confirmed_match(
            db,
            session_id=_SESSION["session_id"],
            student_id=_SESSION["student_id"],
        )
        assert len(captured["portrait"]["hard_constraints"]) == 1
