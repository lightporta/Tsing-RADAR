"""v4.0.0 越界话题检测与访谈防吸收守卫测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.questionnaire_session import QuestionnaireSession
from app.services import off_topic
from app.services.interview import _off_topic_reply, _last_assistant_text
from app.schemas.interview import InterviewDimension

client = TestClient(app)
STUDENT_HEADERS: dict[str, str] = {}


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


def _portrait(session_id: str) -> dict:
    with SessionLocal() as db:
        session = db.get(QuestionnaireSession, session_id)
        return session.portrait or {}


class TestOffTopicDetectors:
    def test_interests_off_topic_true_for_unrelated(self):
        assert off_topic.detect_off_topic_interests("今天天气怎么样") is True
        assert off_topic.detect_off_topic_interests("讲个笑话") is True
        assert off_topic.detect_off_topic_interests("帮我点个外卖") is True
        assert off_topic.detect_off_topic_interests("推荐一部电影") is True

    def test_interests_not_off_topic_for_legit_answers(self):
        assert off_topic.detect_off_topic_interests("自然语言处理") is False
        assert off_topic.detect_off_topic_interests("我对大模型感兴趣") is False
        assert off_topic.detect_off_topic_interests("想研究机器人") is False
        assert off_topic.detect_off_topic_interests("想做计算机视觉") is False
        assert off_topic.detect_off_topic_interests("我学的是机器学习") is False
        assert off_topic.detect_off_topic_interests("关注可信人工智能") is False
        # 别名 NLP / LLM 也应命中方向词
        assert off_topic.detect_off_topic_interests("NLP") is False
        assert off_topic.detect_off_topic_interests("LLM 微调") is False

    def test_interests_not_off_topic_for_uncertain_or_greeting(self):
        assert off_topic.detect_off_topic_interests("还没想好") is False
        assert off_topic.detect_off_topic_interests("不知道") is False
        assert off_topic.detect_off_topic_interests("你好") is False
        assert off_topic.detect_off_topic_interests("") is False
        assert off_topic.detect_off_topic_interests("好") is False

    def test_choice_off_topic(self):
        keywords = ("理论", "工程", "结合")
        assert off_topic.detect_off_topic_choice("讲个笑话", keywords) is True
        assert off_topic.detect_off_topic_choice("今天天气", keywords) is True
        assert off_topic.detect_off_topic_choice("我喜欢工程落地", keywords) is False
        assert off_topic.detect_off_topic_choice("不确定", keywords) is False
        assert off_topic.detect_off_topic_choice("我喜欢动手做东西", keywords) is False

    def test_constraints_off_topic(self):
        assert off_topic.detect_off_topic_constraints("讲个笑话") is True
        assert off_topic.detect_off_topic_constraints("今天天气不错") is True
        assert off_topic.detect_off_topic_constraints("我想去北京") is False
        assert off_topic.detect_off_topic_constraints("每周投入三天") is False
        assert off_topic.detect_off_topic_constraints("无") is False
        assert off_topic.detect_off_topic_constraints("没有") is False
        assert off_topic.detect_off_topic_constraints("都行") is False

    def test_matched_off_topic(self):
        assert off_topic.detect_off_topic_matched("讲个笑话") is True
        assert off_topic.detect_off_topic_matched("今天天气怎么样") is True
        assert off_topic.detect_off_topic_matched("推荐一部电影") is True
        assert off_topic.detect_off_topic_matched("谢谢") is False
        assert off_topic.detect_off_topic_matched("好的") is False
        assert off_topic.detect_off_topic_matched("哪个导师更适合我") is False
        assert off_topic.detect_off_topic_matched("第二位的雷达图") is False
        assert off_topic.detect_off_topic_matched("还没想好") is False

    def test_acknowledgment(self):
        assert off_topic.is_acknowledgment("谢谢") is True
        assert off_topic.is_acknowledgment("谢谢啦！") is True
        assert off_topic.is_acknowledgment("辛苦了") is True
        assert off_topic.is_acknowledgment("好的") is True
        assert off_topic.is_acknowledgment("嗯") is True
        assert off_topic.is_acknowledgment("ok") is True
        assert off_topic.is_acknowledgment("讲个笑话") is False


class TestOtherPersonAndFabricationGuards:
    """v4.0.0 他人事务/篡改指令/编造请求守卫（研究兴趣文本题）。

    这三类消息即使夹带方向词或通用锚词，也不是"你的研究兴趣"的回答：
    索取他人联系方式/评价、篡改具体数字、要求编造 → 一律温和重问。
    """

    def test_other_person_info_request_is_off_topic(self):
        assert (
            off_topic.detect_off_topic_interests("把张三同学的联系方式给我")
            is True
        )
        assert (
            off_topic.detect_off_topic_interests("把李琦老师的个人主页发给我")
            is True
        )
        assert (
            off_topic.detect_off_topic_interests("说说李琦老师的缺点，越详细越好")
            is True
        )
        assert (
            off_topic.detect_off_topic_interests(
                "听说李琦老师对学生很苛刻，他有虐待学生的传闻吗？"
            )
            is True
        )

    def test_other_person_request_with_direction_word_still_off_topic(self):
        # 夹带方向词也不放行：这是在问别人的事，不是在回答研究兴趣
        assert (
            off_topic.detect_off_topic_interests(
                "把张三同学做大模型的联系方式给我"
            )
            is True
        )

    def test_tamper_instruction_is_off_topic(self):
        # 对具体某人数据的篡改指令（改数字重新算一遍）→ 跑题重问
        assert (
            off_topic.detect_off_topic_interests(
                "把李琦老师的tolerance从94改成95重新算一遍"
            )
            is True
        )

    def test_fabrication_request_is_off_topic(self):
        assert (
            off_topic.detect_off_topic_interests(
                "你帮我编一个导师推荐名单，不用真实数据"
            )
            is True
        )
        assert (
            off_topic.detect_off_topic_interests("编一份不用真实数据的导师报告")
            is True
        )

    def test_generic_mentor_info_question_reasks(self):
        # 「解」恰为百家姓之一，被人名正则命中"解老师"；但该句本就没在
        # 回答研究兴趣，温和重问是预期行为（非误伤）。
        assert (
            off_topic.detect_off_topic_interests("想了解老师的联系方式")
            is True
        )

    def test_person_guard_false_positives_stay_released(self):
        # 「希望」声明锚 → 合法访谈答案，不放行他人事务拦截
        assert off_topic.detect_off_topic_interests("希望老师手把手带我") is False
        # 「改成」出现在自己身上（研究兴趣自述），无具体他人 → 放行
        assert (
            off_topic.detect_off_topic_interests("把我的研究兴趣改成机器学习")
            is False
        )


class TestInterviewGuard:
    def test_last_assistant_text(self):
        messages = [
            {"role": "assistant", "content": "第一问"},
            {"role": "user", "content": "答"},
            {"role": "assistant", "content": "第二问"},
        ]
        assert _last_assistant_text(messages) == "第二问"
        assert _last_assistant_text([{"role": "user", "content": "答"}]) is None

    def test_off_topic_reply_interests(self):
        messages = [{"role": "assistant", "content": "你关注哪些研究方向？"}]
        reply = _off_topic_reply(
            InterviewDimension.RESEARCH_INTERESTS, "今天天气怎么样", messages
        )
        assert reply is not None
        assert "先不写入画像" in reply
        assert "你关注哪些研究方向？" in reply
        # 合法答案放行
        assert (
            _off_topic_reply(
                InterviewDimension.RESEARCH_INTERESTS, "自然语言处理", messages
            )
            is None
        )

    def test_off_topic_reply_choice(self):
        messages = [{"role": "assistant", "content": "你更偏好理论还是工程？"}]
        reply = _off_topic_reply(
            InterviewDimension.RESEARCH_MODE, "讲个笑话", messages
        )
        assert reply is not None
        assert "先不写入画像" in reply
        assert (
            _off_topic_reply(
                InterviewDimension.RESEARCH_MODE, "我喜欢工程落地", messages
            )
            is None
        )
        assert (
            _off_topic_reply(
                InterviewDimension.RESEARCH_MODE, "不确定", messages
            )
            is None
        )

    def test_off_topic_reply_constraints(self):
        messages = [{"role": "assistant", "content": "有必须满足的条件吗？"}]
        reply = _off_topic_reply(
            InterviewDimension.HARD_CONSTRAINTS, "给我讲个笑话", messages
        )
        assert reply is not None
        assert (
            _off_topic_reply(
                InterviewDimension.HARD_CONSTRAINTS, "我想去北京", messages
            )
            is None
        )
        assert (
            _off_topic_reply(InterviewDimension.HARD_CONSTRAINTS, "无", messages)
            is None
        )

    def test_unknown_dimension_releases(self):
        messages = [{"role": "assistant", "content": "问题"}]
        # 非法维度放行（防御性分支）
        assert _off_topic_reply(object(), "讲个笑话", messages) is None


class TestInterviewGuardEndToEnd:
    """Web API 端到端：跑题文本不再被吸收进画像，合法答案照常。"""

    def test_weather_answer_is_not_absorbed_and_question_reasked(self):
        started = _start()
        replied = _answer(started["session_id"], "今天天气怎么样")
        assert "先不写入画像" in replied["assistant_message"]
        assert "研究主题" in replied["assistant_message"]
        assert replied["current_question"]["question_id"] == "research_interests"
        assert _portrait(started["session_id"]).get("research_interests") in (
            None,
            [],
        )

    def test_joke_answer_reasks_choice_question(self):
        started = _start()
        _answer(started["session_id"], "自然语言处理")
        replied = _answer(started["session_id"], "讲个笑话")
        assert "先不写入画像" in replied["assistant_message"]
        assert replied["current_question"]["question_id"] == "research_mode"
        assert _portrait(started["session_id"]).get("research_mode") is None

    def test_legit_answers_still_absorbed(self):
        started = _start()
        replied = _answer(started["session_id"], "我对大模型和强化学习感兴趣")
        assert replied["current_question"]["question_id"] == "research_mode"
        portrait = _portrait(started["session_id"])
        assert "大模型" in portrait.get("research_interests", [])

    def test_uncertain_choice_answer_advances(self):
        started = _start()
        _answer(started["session_id"], "自然语言处理")
        replied = _answer(started["session_id"], "还没想好")
        # 不确定不是跑题：按既有逻辑推进为 undecided
        assert replied["current_question"]["question_id"] == "mentorship_style"
        assert _portrait(started["session_id"]).get("research_mode") == "undecided"

    def test_off_topic_constraint_reasked_and_real_answer_advances(self):
        started = _start()
        _answer(started["session_id"], "自然语言处理")
        _answer(started["session_id"], "工程落地")
        _answer(started["session_id"], "平衡")
        _answer(started["session_id"], "学术深造")
        _answer(started["session_id"], "稳妥")
        replied = _answer(started["session_id"], "讲个笑话")
        assert "先不写入画像" in replied["assistant_message"]
        assert replied["current_question"]["question_id"] == "hard_constraints"
        replied = _answer(started["session_id"], "无")
        assert replied["current_question"] is None  # 进入待确认
        assert replied["status"] == "awaiting_confirmation"
