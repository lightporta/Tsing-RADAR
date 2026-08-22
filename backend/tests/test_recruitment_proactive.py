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


# —— v4.1.0 任务3 接线：访谈期一次性注入 + 导师咨询附带在招 ——


class TestInterviewRecruitmentSummary:
    def test_relevant_db_recruitment_yields_fact_sentence(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        # 更早的截止日期保证本条在相关度并列时排最前（此前用例可能已
        # 种入同题记录，稳定排序取最早截止者）
        _seed_recruitment(quota=2, deadline=date(2026, 12, 1))
        with SessionLocal() as db:
            summary = recruitment_public.interview_recruitment_summary(
                db, ["自然语言处理"]
            )
        # 数据库投稿帖发布者为脱敏口径：不带"XX老师组"前缀
        assert summary is not None
        assert summary.startswith("当前正在招科研助理：")
        assert "自然语言处理课题组招募" in summary
        assert "截止 2026-12-01" in summary
        assert "招 2 名" in summary

    def test_static_mentor_post_carries_mentor_prefix(self, monkeypatch):
        monkeypatch.setattr(
            recruitment_public,
            "load_mentors",
            lambda: [
                {
                    "advisor_id": "T00001",
                    "name": "李琦",
                    "dept": "计算机系",
                    "recruitments": [
                        {
                            "recruit_id": "r-static-1",
                            "title": "大模型方向科研助理",
                            "type": "科研助理",
                            "major": "自然语言处理",
                            "deadline": date(2027, 2, 1),
                        }
                    ],
                }
            ],
        )
        with SessionLocal() as db:
            summary = recruitment_public.interview_recruitment_summary(
                db, ["自然语言处理"]
            )
        assert summary is not None
        assert summary.startswith("李琦老师组正在招科研助理：")
        assert "大模型方向科研助理" in summary
        assert "截止 2027-02-01" in summary

    def test_no_relevance_returns_none(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        _seed_recruitment()
        with SessionLocal() as db:
            assert (
                recruitment_public.interview_recruitment_summary(
                    db, ["量子计算"]
                )
                is None
            )

    def test_empty_interests_returns_none(self, monkeypatch):
        monkeypatch.setattr(recruitment_public, "load_mentors", lambda: [])
        with SessionLocal() as db:
            assert recruitment_public.interview_recruitment_summary(db, []) is None


class TestMentorRecruitmentBrief:
    def test_static_mentor_name_match(self, monkeypatch):
        monkeypatch.setattr(
            recruitment_public,
            "load_mentors",
            lambda: [
                {
                    "advisor_id": "T00001",
                    "name": "李琦",
                    "dept": "计算机系",
                    "recruitments": [
                        {
                            "recruit_id": "r-static-1",
                            "title": "大模型方向科研助理",
                            "type": "科研助理",
                            "deadline": date(2027, 2, 1),
                            "is_urgent": True,
                        }
                    ],
                }
            ],
        )
        with SessionLocal() as db:
            matched = recruitment_public.mentor_open_recruitments(db, "李琦")
        assert len(matched) == 1
        brief = recruitment_public.format_mentor_recruitment_brief(matched)
        assert brief is not None
        assert "该导师当前在招的公开招募" in brief
        assert "[急招] 大模型方向科研助理" in brief
        assert "截止 2027-02-01" in brief

    def test_expired_or_other_name_excluded(self, monkeypatch):
        monkeypatch.setattr(
            recruitment_public,
            "load_mentors",
            lambda: [
                {
                    "advisor_id": "T00001",
                    "name": "李琦",
                    "dept": "计算机系",
                    "recruitments": [
                        {
                            "recruit_id": "r-static-1",
                            "title": "已过期招募",
                            "type": "科研助理",
                            "deadline": date(2020, 1, 1),
                        }
                    ],
                }
            ],
        )
        with SessionLocal() as db:
            assert recruitment_public.mentor_open_recruitments(db, "李琦") == []
            assert (
                recruitment_public.format_mentor_recruitment_brief([]) is None
            )

    def test_db_post_matched_via_advisor_brief(self, monkeypatch):
        monkeypatch.setattr(
            recruitment_public, "load_mentors", lambda: []
        )
        _seed_recruitment(advisor_id="T00009")
        monkeypatch.setattr(
            recruitment_public,
            "advisor_brief",
            lambda advisor_id: (
                {"advisor_id": advisor_id, "name": "王五", "dept": "自动化系"}
                if advisor_id == "T00009"
                else None
            ),
        )
        with SessionLocal() as db:
            matched = recruitment_public.mentor_open_recruitments(db, "王五")
        assert len(matched) == 1
        assert matched[0]["recruit_id"]


class TestSessionFlagHelpers:
    """访谈期一次性注入的会话标记：合并写入不破坏既有对话模式。"""

    def test_flag_roundtrip_and_mode_preserved(self):
        from app.services.dialogue_state_store import (
            get_dialogue_mode,
            has_session_flag,
            mark_session_flag,
            upsert_dialogue_state,
        )

        session_id = f"flag_{uuid4().hex}"
        student_id = f"stu_{uuid4().hex}"
        with SessionLocal() as db:
            assert not has_session_flag(
                db, session_id=session_id, student_id=student_id,
                key="interview_recruitment_noted",
            )
            upsert_dialogue_state(
                db, session_id=session_id, student_id=student_id,
                mode="resume_build", state={"step": 2},
            )
            mark_session_flag(
                db, session_id=session_id, student_id=student_id,
                key="interview_recruitment_noted",
            )
            assert has_session_flag(
                db, session_id=session_id, student_id=student_id,
                key="interview_recruitment_noted",
            )
            # 合并写入不覆盖当前对话模式与既有状态键
            assert (
                get_dialogue_mode(
                    db, session_id=session_id, student_id=student_id
                )
                == "resume_build"
            )
