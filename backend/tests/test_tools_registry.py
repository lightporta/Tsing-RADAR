"""v4.0.0 任务1 阶段B：确定性工具注册表测试（Schema + 路由 + fail-closed）。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.db.session import SessionLocal
from app.models.recruitment import Recruitment
from app.services.memory_service import remember_confirmed_portrait
from app.services.tools_registry import (
    TOOL_GET_RECRUITMENTS,
    TOOL_QUERY_MENTOR_KNOWLEDGE,
    TOOL_RECALL_MEMORY,
    TOOL_SCHEMAS,
    build_tool_runtime,
    dispatch_tool_call,
)

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


def _seed_recruitment(**overrides) -> str:
    fields = {
        "publisher_id": f"reviewer_{uuid4().hex}",
        "publisher_type": "advisor",
        "type": "科研助理",
        "title": "自然语言处理课题组招募",
        "req": "仅用于 v4.0.0 工具注册表回归",
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


class TestToolSchemas:
    """OpenAI function-calling 对齐的 Schema 契约。"""

    def test_exactly_three_tools(self):
        names = [
            schema["function"]["name"] for schema in TOOL_SCHEMAS
        ]
        assert names == [
            TOOL_QUERY_MENTOR_KNOWLEDGE,
            TOOL_GET_RECRUITMENTS,
            TOOL_RECALL_MEMORY,
        ]

    def test_schema_shape(self):
        for schema in TOOL_SCHEMAS:
            assert schema["type"] == "function"
            fn = schema["function"]
            assert fn["name"] and fn["description"]
            params = fn["parameters"]
            assert params["type"] == "object"
            assert params["additionalProperties"] is False

    def test_required_fields(self):
        by_name = {
            schema["function"]["name"]: schema["function"]["parameters"]
            for schema in TOOL_SCHEMAS
        }
        assert by_name[TOOL_QUERY_MENTOR_KNOWLEDGE]["required"] == ["name"]
        assert by_name[TOOL_GET_RECRUITMENTS]["required"] == []
        assert by_name[TOOL_RECALL_MEMORY]["required"] == []
        # limit 工具声明了 1..5 的取值范围
        limit = by_name[TOOL_GET_RECRUITMENTS]["properties"]["limit"]
        assert limit["minimum"] == 1 and limit["maximum"] == 5


class TestDispatchMentorKnowledge:
    def test_hit_renders_block_with_declaration(self):
        student = f"tool-mk-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_QUERY_MENTOR_KNOWLEDGE,
                arguments={"name": "李琦"},
            )
        assert "【李琦" in text
        assert "公开存档匿名主观评价聚合，仅作参考" in text
        assert "判档：90-100" in text

    def test_miss_returns_honest_not_found(self):
        student = f"tool-miss-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_QUERY_MENTOR_KNOWLEDGE,
                arguments={"name": "张三丰"},
            )
        assert "该信息暂未收录" in text

    def test_deterministic_same_input_same_output(self):
        student = f"tool-det-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            first = dispatch_tool_call(
                runtime,
                name=TOOL_QUERY_MENTOR_KNOWLEDGE,
                arguments={"name": "李琦"},
            )
            second = dispatch_tool_call(
                runtime,
                name=TOOL_QUERY_MENTOR_KNOWLEDGE,
                arguments={"name": "李琦"},
            )
        assert first == second


class TestDispatchRecruitments:
    def test_honest_empty(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.recruitment_public.load_mentors", lambda: []
        )
        student = f"tool-rec-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_GET_RECRUITMENTS,
                arguments={},
            )
        assert "暂无通过审核且仍在招期内的招募信息" in text

    def test_seeded_recruitment_appears(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.recruitment_public.load_mentors", lambda: []
        )
        _seed_recruitment()
        student = f"tool-rec-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_GET_RECRUITMENTS,
                arguments={"limit": 2},
            )
        assert "自然语言处理课题组招募" in text
        assert "截止 2027-01-01" in text

    def test_urgent_only_filters(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.recruitment_public.load_mentors", lambda: []
        )
        _seed_recruitment(is_urgent=True)
        _seed_recruitment(title="非急招岗位", is_urgent=False)
        student = f"tool-urgent-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_GET_RECRUITMENTS,
                arguments={"urgent_only": True},
            )
        assert "[急招] " in text
        assert "非急招岗位" not in text


class TestDispatchRecallMemory:
    def test_empty_memory_honest(self):
        student = f"tool-mem-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_RECALL_MEMORY,
                arguments={},
            )
        assert "暂无已确认的长期记忆" in text

    def test_confirmed_portrait_recalled(self):
        student = f"tool-mem-{uuid4()}"
        with SessionLocal() as db:
            remember_confirmed_portrait(
                db, student_id=student, portrait=CONFIRMED_PORTRAIT
            )
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_RECALL_MEMORY,
                arguments={},
            )
        assert "自然语言处理" in text
        assert "只能北京" in text


class TestFailClosed:
    def test_unknown_tool(self):
        student = f"tool-unk-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(runtime, name="no_such_tool", arguments={})
        assert "未知工具" in text

    def test_missing_required_argument(self):
        student = f"tool-arg-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_QUERY_MENTOR_KNOWLEDGE,
                arguments={},
            )
        assert "参数无效" in text
        assert "缺少必填参数" in text

    def test_wrong_type_argument(self):
        student = f"tool-type-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_QUERY_MENTOR_KNOWLEDGE,
                arguments={"name": 42},
            )
        assert "参数无效" in text

    def test_undeclared_argument_rejected(self):
        student = f"tool-extra-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            text = dispatch_tool_call(
                runtime,
                name=TOOL_RECALL_MEMORY,
                arguments={"hack": "x"},
            )
        assert "参数无效" in text
        assert "未知参数" in text

    def test_unregistered_executor(self):
        student = f"tool-rt-{uuid4()}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(db=db, student_id=student)
            del runtime[TOOL_RECALL_MEMORY]
            text = dispatch_tool_call(
                runtime,
                name=TOOL_RECALL_MEMORY,
                arguments={},
            )
        assert "未在当前会话注册" in text
