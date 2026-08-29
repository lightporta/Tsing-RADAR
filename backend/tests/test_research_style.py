"""v3.1.4 科研风格速测与研究方向地图测试：
4 题确定性分类、诚实性措辞、多轮状态机（取消/重试）、方向地图治理边界。
v3.1.6：结果后保留 pending 态，「确认」回填画像 research_mode。"""

from __future__ import annotations

import pytest

from app.db.session import SessionLocal
from app.models.dialogue_state import DialogueSession
from app.models.questionnaire_session import QuestionnaireSession
from app.services.dialogue_state_store import get_dialogue_mode, get_dialogue_state
from app.services.direction_map import (
    DIRECTION_MAP_DATA,
    handle_direction_map,
    render_direction_map,
    resolve_direction,
)
from app.services.research_style import (
    MODE_RESEARCH_STYLE,
    accept_answer,
    classify_style,
    handle_research_style,
    question_text,
    welcome_text,
)

_SESSION = {"session_id": "s-style-test", "student_id": "stu-style-test"}


@pytest.fixture(autouse=True)
def isolate_dialogue_sessions():
    """清理跨测试的科研风格模式状态（dialogue_sessions）。"""
    yield
    with SessionLocal() as db:
        db.query(DialogueSession).delete(synchronize_session=False)
        db.commit()


def _enter(db):
    """进入科研风格速测模式并返回首轮文本。"""
    return handle_research_style(
        db, latest_user="测测我的科研风格", **_SESSION
    )


def test_welcome_text_honest_and_starts_first_question():
    text = welcome_text()
    assert "第一题" in text
    assert "不判断你是否适合科研，也不评价能力高低" in text
    assert "4 题" in text


def test_accept_answer_numeric_text_and_invalid():
    assert accept_answer("2", 0) == "deep"
    assert accept_answer("广泛涉猎", 0) == "broad"
    assert accept_answer("从方法创新出发", 1) == "method"
    assert accept_answer("工程", 2) == "engineering"
    assert accept_answer("分析", 3) == "analysis"
    # 非法/空答案不匹配任何选项
    assert accept_answer("随便", 0) is None
    assert accept_answer("", 0) is None
    assert accept_answer("11", 0) is None  # 序号精确匹配，不误中 "1"


def test_question_text_bounds():
    assert "第二题" in question_text(1)
    assert "第四题" in question_text(3)
    with pytest.raises(IndexError):
        question_text(4)
    with pytest.raises(IndexError):
        question_text(-1)


def test_classify_style_deterministic_and_mode_mapping():
    a = classify_style(("deep", "method", "theory", "paper"))
    b = classify_style(("deep", "method", "theory", "paper"))
    # 确定性：相同答案 → 完全相同结果
    assert a == b
    assert a["name"] == "深耕·理论建构型"
    assert a["mode"] == "theory"

    eng = classify_style(("broad", "problem", "engineering", "system"))
    assert eng["name"] == "多线·落地攻坚型"
    assert eng["mode"] == "engineering"

    mix = classify_style(("mixed", "data", "balanced", "analysis"))
    assert mix["name"] == "实证归纳型"
    assert mix["mode"] == "mixed"

    # 解释包含范围与成果形态的两条参考建议
    assert "多线探索" in a["explanation"] or "单点深耕" in a["explanation"]
    assert "论文" in a["explanation"]


def test_handle_research_style_full_flow_four_turns():
    with SessionLocal() as db:
        first = _enter(db)
        assert "第一题" in first
        assert get_dialogue_mode(db, **_SESSION) == MODE_RESEARCH_STYLE

        # 依次作答：1(范围-broad) / 方法 / 2(工程) / 论文
        for answer, expect_q in (
            ("1", "第二题"),
            ("从方法创新出发", "第三题"),
            ("2", "第四题"),
        ):
            reply = handle_research_style(
                db, latest_user=answer, **_SESSION
            )
            assert expect_q in reply
        final = handle_research_style(db, latest_user="论文", **_SESSION)

        assert "【你的科研风格速测结果】" in final
        assert "多线·方法工程型" in final
        assert "不评价能力高低" in final
        assert "「确认」后生效" in final
        # v3.1.6：结果后保留 pending 态等待「确认」回填，模式未清除
        assert get_dialogue_mode(db, **_SESSION) == MODE_RESEARCH_STYLE
        state = get_dialogue_state(db, **_SESSION)
        assert state["step"] == 4
        assert state["pending"] is True
        assert state["answers"] == ["broad", "method", "engineering", "paper"]


def test_handle_research_style_confirm_fills_research_mode():
    with SessionLocal() as db:
        sess = {"session_id": "s-style-confirm", "student_id": "stu-style-confirm"}
        handle_research_style(db, latest_user="测测我的科研风格", **sess)
        for answer in ("1", "从方法创新出发", "2", "论文"):
            handle_research_style(db, latest_user=answer, **sess)

        reply = handle_research_style(db, latest_user="确认", **sess)
        assert "研究方式 = 工程与落地" in reply
        assert "「确认画像」" in reply
        # 回填后模式清除
        assert get_dialogue_mode(db, **sess) is None
        # 画像已写入 research_mode
        session = db.get(QuestionnaireSession, sess["session_id"])
        assert session is not None
        assert session.portrait["research_mode"] == "engineering"


def test_handle_research_style_result_cancel_abandons_without_fill():
    with SessionLocal() as db:
        sess = {"session_id": "s-style-cancel", "student_id": "stu-style-cancel"}
        handle_research_style(db, latest_user="测测我的科研风格", **sess)
        for answer in ("1", "从方法创新出发", "2", "论文"):
            handle_research_style(db, latest_user=answer, **sess)

        reply = handle_research_style(db, latest_user="取消", **sess)
        assert "已放弃" in reply
        assert get_dialogue_mode(db, **sess) is None
        session = db.get(QuestionnaireSession, sess["session_id"])
        assert session is None or session.portrait.get("research_mode") is None


def test_handle_research_style_result_restyle_restarts():
    with SessionLocal() as db:
        sess = {"session_id": "s-style-restyle", "student_id": "stu-style-restyle"}
        handle_research_style(db, latest_user="测测我的科研风格", **sess)
        for answer in ("1", "从方法创新出发", "2", "论文"):
            handle_research_style(db, latest_user=answer, **sess)

        reply = handle_research_style(db, latest_user="再测测我的科研风格", **sess)
        assert "第一题" in reply
        assert get_dialogue_mode(db, **sess) == MODE_RESEARCH_STYLE


def test_handle_research_style_result_other_message_keeps_pending():
    with SessionLocal() as db:
        sess = {"session_id": "s-style-nudge", "student_id": "stu-style-nudge"}
        handle_research_style(db, latest_user="测测我的科研风格", **sess)
        for answer in ("1", "2", "2", "论文"):
            handle_research_style(db, latest_user=answer, **sess)

        reply = handle_research_style(db, latest_user="随便聊聊", **sess)
        assert "「确认」" in reply
        assert "「取消」" in reply
        # 保持 pending，不吞消息也不写画像
        assert get_dialogue_mode(db, **sess) == MODE_RESEARCH_STYLE
        session = db.get(QuestionnaireSession, sess["session_id"])
        assert session is None or session.portrait.get("research_mode") is None


def test_handle_research_style_result_nav_releases_mode():
    """v3.1.6：pending 态下导航词放行走主流程（返回 None + 清模式）。"""
    with SessionLocal() as db:
        sess = {"session_id": "s-style-nav", "student_id": "stu-style-nav"}
        handle_research_style(db, latest_user="测测我的科研风格", **sess)
        for answer in ("1", "从方法创新出发", "2", "论文"):
            handle_research_style(db, latest_user=answer, **sess)

        assert handle_research_style(db, latest_user="方向地图", **sess) is None
        assert get_dialogue_mode(db, **sess) is None


def test_handle_research_style_cancel_exits_and_clears():
    with SessionLocal() as db:
        _enter(db)
        reply = handle_research_style(db, latest_user="不测了", **_SESSION)
        assert "已退出科研风格速测" in reply
        assert get_dialogue_mode(db, **_SESSION) is None


def test_handle_research_style_invalid_answer_retries_same_question():
    with SessionLocal() as db:
        _enter(db)
        reply = handle_research_style(db, latest_user="随便", **_SESSION)
        assert "再选一次" in reply
        assert "第一题" in reply
        # 未推进：仍在第一题，合法答案可继续
        assert get_dialogue_mode(db, **_SESSION) == MODE_RESEARCH_STYLE
        next_reply = handle_research_style(db, latest_user="1", **_SESSION)
        assert "第二题" in next_reply


def test_render_direction_map_lists_directions_without_teachers():
    text = render_direction_map()
    assert "【研究方向地图】" in text
    assert "不涉及具体导师" in text
    # 16 个规范方向全部列出
    for name, _desc, _keywords in DIRECTION_MAP_DATA:
        assert name in text
    # 治理边界：方向地图不输出参考教师名单，也不出现任何"参考教师"字样
    assert "参考教师" not in text
    assert "回复其中一个方向名" in text


def test_direction_map_data_shape_and_uniqueness():
    names = [entry[0] for entry in DIRECTION_MAP_DATA]
    assert len(names) == len(set(names))  # 规范方向名不重复
    for name, desc, keywords in DIRECTION_MAP_DATA:
        assert name and desc and keywords


def test_resolve_direction_aliases_and_miss():
    assert resolve_direction("NLP") == "自然语言处理"
    assert resolve_direction("nlp") == "自然语言处理"
    assert resolve_direction(" 大模型 ") == "大模型 / 大语言模型"
    assert resolve_direction("自动驾驶") == "机器人 / 无人系统"
    assert resolve_direction("生物") == "生物 / 计算生物学"
    # 未收录方向诚实返回 None，不做语义推断
    assert resolve_direction("量子计算") is None
    assert resolve_direction("") is None
    assert resolve_direction(None) is None


# —— v3.1.6 方向地图闭环：选方向 → 回填 research_interests → 引导 ——

def _enter_direction_map(db, sess):
    """进入方向地图模式并返回地图文本。"""
    return handle_direction_map(db, latest_user="方向地图", **sess)


def test_handle_direction_map_choice_fills_interests_and_guides():
    from app.services.direction_map import handle_direction_map

    with SessionLocal() as db:
        sess = {"session_id": "s-dir-fill", "student_id": "stu-dir-fill"}
        first = _enter_direction_map(db, sess)
        assert "【研究方向地图】" in first
        assert "不涉及具体导师" in first

        reply = handle_direction_map(db, latest_user="大模型", **sess)
        assert "已记录研究方向：**大模型 / 大语言模型**" in reply
        assert "「确认画像」" in reply
        assert "「招募」" in reply
        # 模式清除 + 画像写入规范方向名
        assert get_dialogue_mode(db, **sess) is None
        session = db.get(QuestionnaireSession, sess["session_id"])
        assert session is not None
        assert session.portrait["research_interests"] == ["大模型 / 大语言模型"]


def test_handle_direction_map_canonical_full_name_matches():
    from app.services.direction_map import handle_direction_map

    with SessionLocal() as db:
        sess = {"session_id": "s-dir-canon", "student_id": "stu-dir-canon"}
        _enter_direction_map(db, sess)
        # 回复完整规范名也应命中（v3.1.6 resolve_direction 补全名匹配）
        reply = handle_direction_map(db, latest_user="自然语言处理", **sess)
        assert "已记录研究方向：**自然语言处理**" in reply
        session = db.get(QuestionnaireSession, sess["session_id"])
        assert session.portrait["research_interests"] == ["自然语言处理"]


def test_handle_direction_map_alias_miss_is_honest_and_clears():
    from app.services.direction_map import handle_direction_map

    with SessionLocal() as db:
        sess = {"session_id": "s-dir-miss", "student_id": "stu-dir-miss"}
        _enter_direction_map(db, sess)
        # 未收录方向：不编造、不写画像，模式清除（只拦截一次）
        assert handle_direction_map(db, latest_user="量子计算", **sess) is None
        assert get_dialogue_mode(db, **sess) is None
        session = db.get(QuestionnaireSession, sess["session_id"])
        assert session is None or session.portrait.get("research_interests") in (None, [])


def test_handle_direction_map_cancel_exits_cleanly():
    from app.services.direction_map import handle_direction_map

    with SessionLocal() as db:
        sess = {"session_id": "s-dir-cancel", "student_id": "stu-dir-cancel"}
        _enter_direction_map(db, sess)
        reply = handle_direction_map(db, latest_user="取消", **sess)
        assert "已退出方向地图" in reply
        assert get_dialogue_mode(db, **sess) is None
