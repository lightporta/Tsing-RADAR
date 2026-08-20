"""v4.0.0 招募增强：确认后主动触达 + 表达层事实包逐字校验测试。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.db.session import SessionLocal
from app.models.recruitment import Recruitment
from app.schemas.interview import StudentPortrait
from app.services import recruitment_public
from app.services.chat_expression import (
    InterviewFactPack,
    _validate_expression,
    build_interview_fact_pack,
)
from app.services.recruitment_public import proactive_recruitment_hint


def _seed_recruitment(**overrides) -> str:
    fields = {
        "publisher_id": f"reviewer_{uuid4().hex}",
        "publisher_type": "advisor",
        "type": "科研助理",
        "title": "自然语言处理课题组招募",
        "req": "仅用于 v4.0.0 主动触达回归",
        "major": "自然语言处理",
        "deadline": date(2027, 1, 1),
        "is_urgent": False,
        "review_status": "verified",
        "publication_status": "published",
        "authorization_basis": "explicit_consent",
        "provenance": {},
        "governance": {},
        "quarantined_fields": {},
    }
    fields.update(overrides)
    with SessionLocal() as db:
        record = Recruitment(**fields)
        db.add(record)
        db.commit()
        db.refresh(record)
        return record.recruit_id


class TestProactiveRecruitmentHint:
    def test_relevant_open_recruitment_yields_hint(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        _seed_recruitment()
        profile = StudentPortrait(research_interests=["自然语言处理"])
        with SessionLocal() as db:
            hint = proactive_recruitment_hint(db, profile)
        assert hint is not None
        assert "自然语言处理课题组招募" in hint
        assert "截止 2027-01-01" in hint
        assert "回复「招募信息」" in hint

    def test_urgent_marked_in_hint(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        _seed_recruitment(is_urgent=True)
        profile = StudentPortrait(research_interests=["自然语言处理"])
        with SessionLocal() as db:
            hint = proactive_recruitment_hint(db, profile)
        assert hint is not None
        assert "[急招]" in hint

    def test_no_relevance_silent(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        _seed_recruitment()
        profile = StudentPortrait(research_interests=["量子计算"])
        with SessionLocal() as db:
            assert proactive_recruitment_hint(db, profile) is None

    def test_no_interests_silent(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        _seed_recruitment()
        with SessionLocal() as db:
            assert proactive_recruitment_hint(db, None) is None

    def test_expired_recruitment_excluded(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        _seed_recruitment(deadline=date(2020, 1, 1))
        profile = StudentPortrait(research_interests=["自然语言处理"])
        with SessionLocal() as db:
            assert proactive_recruitment_hint(db, profile) is None


def _base_fact_pack(**overrides) -> InterviewFactPack:
    # 题目故意取短句：_core_fragments 只取 >=6 字片段，
    # 让本文件专注校验事实段逐字规则而非题面覆盖。
    return InterviewFactPack(
        user_message="答",
        question_prompt="喜欢什么？",
        options=(),
        completed_dimensions=(),
        missing_dimensions=("研究兴趣",),
        hard_constraint_status="尚未确认硬性条件",
        **overrides,
    )


class TestFactPackSummaries:
    def test_defaults_empty(self):
        pack = _base_fact_pack()
        assert pack.recruitment_summary == ""
        assert pack.memory_summary == ""

    def test_build_interview_fact_pack_carries_summaries(self):
        from app.schemas.interview import (
            InterviewDimension,
            InterviewStateResponse,
            InterviewStatus,
            StudentPortrait,
        )

        state = InterviewStateResponse(
            session_id="s",
            status=InterviewStatus.IN_PROGRESS,
            profile=StudentPortrait(research_interests=["自然语言处理"]),
            profile_version=1,
            current_question=None,
            completed_dimensions=[InterviewDimension.RESEARCH_INTERESTS],
            missing_dimensions=[InterviewDimension.RESEARCH_MODE],
            needs_confirmation=False,
            needs_clarification=False,
            clarification_questions=[],
            recommend_ready=False,
            assistant_message="你更偏好理论还是工程？",
            messages=[],
        )
        pack = build_interview_fact_pack(
            state,
            "工程落地",
            recruitment_summary="自然语言处理课题组招募，截止 2027-01-01",
            memory_summary="工程落地",
        )
        assert pack.recruitment_summary == "自然语言处理课题组招募，截止 2027-01-01"
        assert pack.memory_summary == "工程落地"
        assert pack.hard_constraint_status == "尚未确认硬性条件"


class TestValidateExpressionVerbatim:
    """逐字校验守住「不增强」红线：改写硬事实 → 拒绝 → 降级固定模板。"""

    def test_recruitment_facts_verbatim_pass(self):
        pack = _base_fact_pack(
            recruitment_summary=(
                "自然语言处理课题组招募，截止 2027-01-01，招 2 名，邮箱投递"
            )
        )
        text = (
            "顺便说一句：自然语言处理课题组招募（科研助理，"
            "截止 2027-01-01，招 2 名），邮箱投递即可。"
        )
        assert _validate_expression(text, pack) is True

    def test_altered_deadline_rejected(self):
        pack = _base_fact_pack(recruitment_summary="截止 2027-01-01")
        # 日期被篡改 → 拒绝
        assert (
            _validate_expression("截止 2026-12-31 的招募正在开放。", pack) is False
        )

    def test_invented_quota_rejected(self):
        pack = _base_fact_pack(recruitment_summary="招 2 名")
        # 名额被改成 5 名 → 拒绝
        assert _validate_expression("拟招 5 名，欢迎报名。", pack) is False
        # 逐字保留则通过（空白差异容忍）
        assert _validate_expression("课题组招2名科研助理。", pack) is True

    def test_memory_paraphrase_rejected(self):
        pack = _base_fact_pack(memory_summary="工程落地")
        assert _validate_expression("我记得你更爱动手实践。", pack) is False

    def test_memory_fact_verbatim_pass(self):
        pack = _base_fact_pack(memory_summary="工程落地")
        assert _validate_expression("还记得你确认过：工程落地。", pack) is True

    def test_no_summaries_behavior_unchanged(self):
        pack = _base_fact_pack()
        assert _validate_expression("随便一句自然的话。", pack) is True
