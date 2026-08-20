"""v2.5 招募对话模块测试：语义筛选解析、v2.5 输出格式、诚实空态、
岗位联动详情、筛选偏好跨轮记忆。"""

from __future__ import annotations

from datetime import date

import pytest

from app.db.session import SessionLocal
from app.models.dialogue_state import DialogueSession
from app.schemas.interview import StudentPortrait
from app.services.recruitment_dialogue import (
    _interest_matches,
    _is_detail_query,
    _parse_ordinal,
    apply_recruitment_filters,
    format_recruitment_digest_v25,
    handle_recruitment_query,
    parse_recruitment_filters,
    resolve_recruitment_target,
)
from app.services.recruitment_public import RECRUITMENT_SITE_URL


@pytest.fixture(autouse=True)
def isolate_dialogue_sessions():
    """清理跨测试的招募偏好记忆（dialogue_sessions）。"""
    yield
    with SessionLocal() as db:
        db.query(DialogueSession).delete(synchronize_session=False)
        db.commit()


_SAMPLE_RECORDS = [
    {
        "recruit_id": "R001",
        "title": "计算机系 NLP 课题组招募科研助理",
        "type": "科研助理",
        "dept": "计算机科学与技术系",
        "publisher_name": "某导师",
        "major": "计算机视觉、自然语言处理",
        "req": "熟悉 PyTorch，有 NLP 项目经验者优先",
        "deadline": date(2026, 9, 30),
        "is_urgent": True,
        "apply_method": "发送简历至 lab@example.edu",
    },    {
        "recruit_id": "R002",
        "title": "自动化系机器人方向招聘博士后",
        "type": "博士后",
        "dept": "自动化系",
        "publisher_name": "某导师",
        "major": "机器人、控制",
        "req": "具有机器人或控制相关研究背景",
        "deadline": date(2026, 12, 31),
        "is_urgent": False,
        "apply_method": None,
    },
]


def test_parse_recruitment_filters_natural_language():
    filters = parse_recruitment_filters("计算机系最近的急招科研助理")
    assert filters["dept"] == "计算机科学与技术系"
    assert filters["type"] == "科研助理"
    assert filters["urgent"] is True
    assert filters["direction"] == []

    filters = parse_recruitment_filters("有没有大模型方向的实习")
    assert filters["type"] == "实习"
    assert "大模型" in filters["direction"]
    assert filters["dept"] is None
    assert filters["urgent"] is None

    filters = parse_recruitment_filters("随便看看")
    assert filters == {
        "dept": None,
        "type": None,
        "urgent": None,
        "direction": [],
    }


def test_apply_recruitment_filters_combines_conditions():
    result = apply_recruitment_filters(
        _SAMPLE_RECORDS,
        {"dept": "计算机科学与技术系", "type": "科研助理", "urgent": True, "direction": []},
    )
    assert len(result) == 1
    assert result[0]["recruit_id"] == "R001"

    # 方向关键词进一步收窄
    narrowed = apply_recruitment_filters(
        _SAMPLE_RECORDS,
        {"dept": None, "type": None, "urgent": None, "direction": ["机器人"]},
    )
    assert [record["recruit_id"] for record in narrowed] == ["R002"]

    # 无条件过滤返回全部
    assert len(apply_recruitment_filters(_SAMPLE_RECORDS, parse_recruitment_filters(""))) == 2


def test_format_recruitment_digest_v25_structured_output():
    profile = StudentPortrait(research_interests=["自然语言处理", "大模型"])
    text = format_recruitment_digest_v25(
        _SAMPLE_RECORDS,
        profile=profile,
        filters=parse_recruitment_filters(""),
    )
    assert "共 2 条通过审核且在招的招募信息" in text
    assert "[急招] " in text
    assert "计算机系 NLP 课题组招募科研助理" in text
    assert "某导师" in text  # 发布方
    assert "科研助理 | 截止 2026-09-30" in text  # 类型 | 截止
    assert "核心要求：熟悉 PyTorch" in text  # 核心要求摘要
    assert "投递说明：发送简历至 lab@example.edu" in text
    assert "推荐理由：与你的研究方向「自然语言处理」重合" in text
    assert "★" in text  # 推荐指数
    assert RECRUITMENT_SITE_URL in text


def test_format_recruitment_digest_v25_missing_apply_method_is_honest():
    text = format_recruitment_digest_v25(
        [_SAMPLE_RECORDS[1]],
        profile=None,
        filters=parse_recruitment_filters(""),
    )
    assert "该信息暂未收录" in text
    assert "投递方式" in text


def test_format_recruitment_digest_v25_empty_state():
    text = format_recruitment_digest_v25([], profile=None, filters=parse_recruitment_filters(""))
    assert "暂无通过审核且仍在招期内的招募信息" in text
    assert RECRUITMENT_SITE_URL in text


def test_format_recruitment_digest_v25_no_overlap_is_honest():
    profile = StudentPortrait(research_interests=["量子计算"])
    text = format_recruitment_digest_v25(
        _SAMPLE_RECORDS,
        profile=profile,
        filters=parse_recruitment_filters(""),
    )
    assert "无与你的研究兴趣直接重合的在招岗位" in text
    assert "★" not in text


@pytest.mark.asyncio
async def test_recruitment_query_handler_runs_async():
    from app.db.session import SessionLocal

    from app.services.recruitment_dialogue import handle_recruitment_query

    with SessionLocal() as db:
        reply, attachment = await handle_recruitment_query(
            db, latest_user="有招募信息吗", portrait=None
        )
    # 本地数据为 0 记录占位 → 诚实空态
    assert "暂无通过审核且仍在招期内的招募信息" in reply
    assert attachment is None


def test_parse_recruitment_filters_normalizes_direction_aliases():
    """方向别名归一化：NLP→自然语言处理、LLM→大模型，并去重。"""
    filters = parse_recruitment_filters("NLP 方向的实习")
    assert filters["direction"] == ["自然语言处理"]
    assert parse_recruitment_filters("找 LLM 相关岗位")["direction"] == ["大模型"]
    # 同一规范方向的不同写法只保留一次
    assert parse_recruitment_filters("NLP 和自然语言处理")["direction"] == [
        "自然语言处理"
    ]
    # 规范词本身不被重复归一化
    assert parse_recruitment_filters("自然语言处理")["direction"] == ["自然语言处理"]


def test_interest_matches_direction_alias_equivalence():
    """兴趣与岗位文本双向同义匹配：NLP ↔ 自然语言处理；AI 词边界。"""
    nlp_record = {
        "recruit_id": "R101",
        "title": "NLP 课题组招募科研助理",
        "type": "科研助理",
        "dept": "计算机科学与技术系",
        "publisher_name": "某导师",
        "major": "自然语言处理",
        "req": "熟悉 PyTorch",
        "deadline": date(2026, 9, 30),
        "is_urgent": False,
        "apply_method": None,
        "tags": [],
    }
    # 兴趣写 NLP → 命中含"自然语言处理"的岗位，输出归一化规范词
    assert _interest_matches(nlp_record, ["NLP"]) == ["自然语言处理"]
    # 兴趣写自然语言处理 → 命中标题含 NLP 的岗位
    assert _interest_matches(nlp_record, ["自然语言处理"]) == ["自然语言处理"]
    # AI 是词边界匹配：不误命中 "training"（子串含 ai）
    training_record = {
        "recruit_id": "R102",
        "title": "training 数据标注",
        "type": "实习",
        "dept": "计算机科学与技术系",
        "publisher_name": "某导师",
        "major": "",
        "req": "",
        "deadline": date(2026, 12, 31),
        "is_urgent": False,
        "apply_method": None,
        "tags": [],
    }
    assert _interest_matches(training_record, ["人工智能"]) == []
    # 筛选也走同义匹配：direction=自然语言处理 命中标题含 NLP 的记录
    filtered = apply_recruitment_filters(
        [nlp_record],
        {"dept": None, "type": None, "urgent": None, "direction": ["自然语言处理"]},
    )
    assert [record["recruit_id"] for record in filtered] == ["R101"]


@pytest.mark.asyncio
async def test_handle_recruitment_query_vague_guidance_with_portrait(monkeypatch):
    """宽泛查询 + 有画像：按研究兴趣推荐 + 给出进一步筛选引导。"""
    from app.db.session import SessionLocal

    from app.services.recruitment_dialogue import handle_recruitment_query

    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    profile = StudentPortrait(research_interests=["自然语言处理"])
    with SessionLocal() as db:
        reply, _ = await handle_recruitment_query(
            db, latest_user="有什么在招的吗", portrait=profile
        )
    assert "你还没有指定" in reply
    assert "自然语言处理" in reply  # 画像兴趣出现在引导与推荐理由
    assert "推荐理由" in reply
    assert "科研助理 | 截止 2026-09-30" in reply


@pytest.mark.asyncio
async def test_handle_recruitment_query_vague_guidance_without_portrait(monkeypatch):
    """宽泛查询 + 无画像：给出筛选引导后展示最新在招概览。"""
    from app.db.session import SessionLocal

    from app.services.recruitment_dialogue import handle_recruitment_query

    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    with SessionLocal() as db:
        reply, _ = await handle_recruitment_query(
            db, latest_user="随便看看", portrait=None
        )
    assert "你还没有指定筛选条件" in reply
    assert "告诉我你的研究兴趣" in reply
    assert "计算机系 NLP 课题组招募科研助理" in reply


@pytest.mark.asyncio
async def test_handle_recruitment_query_vague_with_empty_data_is_honest(monkeypatch):
    """宽泛查询 + 无在招记录：保持诚实空态，不伪造热门推荐。"""
    from app.db.session import SessionLocal

    from app.services.recruitment_dialogue import handle_recruitment_query

    def fake_list_public(db):
        return [], None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    with SessionLocal() as db:
        reply, _ = await handle_recruitment_query(
            db, latest_user="随便看看", portrait=None
        )
    assert "暂无通过审核且仍在招期内的招募信息" in reply
    assert "你还没有指定" not in reply


def test_parse_ordinal_and_detail_detection():
    """「第 N 个」序号解析（阿拉伯/中文数字）与详情追问判定。"""
    assert _parse_ordinal("第1个") == 1
    assert _parse_ordinal("第 3 个怎么样") == 3
    assert _parse_ordinal("第一个") == 1
    assert _parse_ordinal("第十二个") == 12
    assert _parse_ordinal("第十个") == 10
    assert _parse_ordinal("随便看看") is None
    # 详情追问：序号本身或序号+语气词；优化/投递语义不属于详情
    assert _is_detail_query("第1个怎么样") is True
    assert _is_detail_query("第1个") is True
    assert _is_detail_query("第一个岗位详情") is True
    assert _is_detail_query("针对第1个优化简历") is False


@pytest.mark.asyncio
async def test_handle_recruitment_query_ordinal_shows_detail(monkeypatch):
    """回复「第 1 个」→ 单条完整详情（含距截止天数与投递说明）。"""
    from app.services.recruitment_dialogue import list_public_recruitments

    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    with SessionLocal() as db:
        reply, _ = await handle_recruitment_query(
            db,
            latest_user="第1个",
            portrait=StudentPortrait(research_interests=["自然语言处理"]),
        )
    assert "计算机系 NLP 课题组招募科研助理" in reply
    assert "距截止还有" in reply
    assert "[急招]" in reply
    assert "投递说明：发送简历至 lab@example.edu" in reply
    assert "针对第 1 个优化简历" in reply


@pytest.mark.asyncio
async def test_handle_recruitment_query_ordinal_out_of_range_is_honest(monkeypatch):
    """序号超出在招岗位数 → 诚实提示，不编造岗位。"""
    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    with SessionLocal() as db:
        reply, _ = await handle_recruitment_query(
            db, latest_user="第9个", portrait=None
        )
    assert "没找到对应的在招岗位" in reply


@pytest.mark.asyncio
async def test_handle_recruitment_query_remembers_and_reuses_filters(monkeypatch):
    """明确条件被记住；宽泛查询自动沿用，并说明沿用的条件。"""
    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    session_id = "recruit-memo-session"
    student_id = "student-memo-1"
    with SessionLocal() as db:
        first, _ = await handle_recruitment_query(
            db,
            latest_user="计算机系的实习",
            portrait=None,
            session_id=session_id,
            student_id=student_id,
        )
        assert first  # 条件筛选路径正常返回
        # 宽泛查询 → 沿用上次条件
        second, _ = await handle_recruitment_query(
            db,
            latest_user="还有吗",
            portrait=None,
            session_id=session_id,
            student_id=student_id,
        )
    assert "沿用你之前提到的筛选条件" in second
    assert "计算机科学与技术系" in second
    assert "类型 实习" in second


@pytest.mark.asyncio
async def test_handle_recruitment_query_new_conditions_replace_memo(monkeypatch):
    """新条件覆盖旧记忆；宽泛查询沿用最新条件。"""
    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    session_id = "recruit-memo-replace"
    student_id = "student-memo-2"
    with SessionLocal() as db:
        await handle_recruitment_query(
            db,
            latest_user="计算机系的实习",
            portrait=None,
            session_id=session_id,
            student_id=student_id,
        )
        await handle_recruitment_query(
            db,
            latest_user="博士后",
            portrait=None,
            session_id=session_id,
            student_id=student_id,
        )
        reply, _ = await handle_recruitment_query(
            db,
            latest_user="还有吗",
            portrait=None,
            session_id=session_id,
            student_id=student_id,
        )
    assert "沿用你之前提到的筛选条件" in reply
    assert "类型 博士后" in reply
    assert "计算机" not in reply  # 旧条件已被新条件替换


def test_resolve_recruitment_target_by_ordinal_and_title(monkeypatch):
    """岗位解析：序号（按 digest 排序口径）与标题子串。"""
    def fake_list_public(db):
        return _SAMPLE_RECORDS, None

    monkeypatch.setattr(
        "app.services.recruitment_dialogue.list_public_recruitments",
        fake_list_public,
    )
    with SessionLocal() as db:
        by_ordinal = resolve_recruitment_target(
            db, "第1个", interests=["自然语言处理"]
        )
        assert by_ordinal is not None
        assert by_ordinal["recruit_id"] == "R001"  # 兴趣命中 R001 排第一
        by_title = resolve_recruitment_target(db, "自动化系机器人")
        assert by_title is not None
        assert by_title["recruit_id"] == "R002"
        by_id = resolve_recruitment_target(db, "R001")
        assert by_id["recruit_id"] == "R001"
        assert resolve_recruitment_target(db, "不存在的东西") is None
