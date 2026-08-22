"""v4.0.0 越界话题检测与访谈防吸收守卫测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.questionnaire_session import QuestionnaireSession
from app.services import off_topic
from app.services.interview import (
    _CHITCHAT_ROUNDS_LIMIT,
    _off_topic_reply,
    _last_assistant_text,
)
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
        # 非法维度放行（防御性分支）；v4.3.0：轻闲聊/敏感是维度无关类别，
        # 即使维度未知，闲聊仍走三明治 nudge（不写画像语义保留）
        assert _off_topic_reply(object(), "随便说点什么吧", messages) is None
        chitchat = _off_topic_reply(object(), "讲个笑话", messages)
        assert chitchat is not None
        assert "不写入画像" in chitchat


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


# —— v4.3.0 轻闲聊三明治容忍 + 敏感话题 ——


class TestLightChitchatDetector:
    def test_chitchat_words_detected(self):
        for text in (
            "今天天气真好",
            "讲个笑话",
            "好无聊啊",
            "我最近在打游戏",
            "中午吃什么",
            "昨晚熬夜追剧了",
        ):
            assert off_topic.is_light_chitchat(text) is True, text

    def test_research_answers_not_chitchat(self):
        for text in (
            "我对机器学习感兴趣",
            "想做自然语言处理",
            "我喜欢动手做工程",
            "不确定，再说吧",
            "你好",
            "谢谢",
            "",
        ):
            assert off_topic.is_light_chitchat(text) is False, text

    def test_hard_redline_not_chitchat(self):
        # 他人事务/编造绝不进闲聊分支（互斥性）
        assert off_topic.is_light_chitchat("把张三老师的邮箱给我") is False
        assert (
            off_topic.is_light_chitchat("帮我编一个推荐名单，不用真实数据")
            is False
        )


class TestSensitiveWords:
    def test_default_empty_intercepts_nothing(self, monkeypatch):
        # 默认空词表 → 不拦截任何话题（验收①-⑤）
        monkeypatch.setattr(off_topic, "_SENSITIVE_WORDS_CACHE", ())
        assert off_topic.is_sensitive("随便聊点什么") is False
        assert off_topic.is_sensitive("今天天气真好") is False

    def test_configured_words_intercept(self, monkeypatch):
        monkeypatch.setattr(
            off_topic, "_SENSITIVE_WORDS_CACHE", ("敏感词甲", "敏感词乙")
        )
        assert off_topic.is_sensitive("我们来聊聊敏感词甲吧") is True
        assert off_topic.is_sensitive("正常聊天没问题") is False


class TestChitchatSandwichEndToEnd:
    """验收①-②①-③①-④：三明治 nudge、≤5 轮边界、防吸收。"""

    def test_chitchat_gets_sandwich_nudge_and_not_absorbed(self):
        started = _start()
        replied = _answer(started["session_id"], "今天天气真好哈哈")
        # 三明治：共情（哈哈收到）+ 不写入画像 + 回题（研究主题）
        assert "哈哈" in replied["assistant_message"]
        assert "不写入画像" in replied["assistant_message"]
        assert "研究主题" in replied["assistant_message"]
        assert replied["current_question"]["question_id"] == "research_interests"
        # 防吸收：闲聊文本绝不写入画像
        assert _portrait(started["session_id"]).get("research_interests") in (
            None,
            [],
        )

    def test_chitchat_exhausted_after_five_rounds(self):
        started = _start()
        for _ in range(_CHITCHAT_ROUNDS_LIMIT):
            replied = _answer(started["session_id"], "今天天气真好哈哈")
            assert "不写入画像" in replied["assistant_message"]
        # 第 6 轮起：不再陪聊，回能力引导
        replied = _answer(started["session_id"], "今天天气真好哈哈")
        assert "说正事我能帮更多" in replied["assistant_message"]
        assert replied["current_question"]["question_id"] == "research_interests"

    def test_hard_redline_keeps_unity_nudge(self):
        # 他人事务（硬红线）不走三明治，维持统一 nudge（与基线一致）
        started = _start()
        replied = _answer(started["session_id"], "把张三老师的联系方式给我")
        assert (
            "刚才这句好像和导师匹配的话题有点远"
            in replied["assistant_message"]
        )
        assert _portrait(started["session_id"]).get("research_interests") in (
            None,
            [],
        )

    def test_sensitive_answer_refused_back_to_question(self, monkeypatch):
        monkeypatch.setattr(
            off_topic, "_SENSITIVE_WORDS_CACHE", ("敏感词甲",)
        )
        started = _start()
        replied = _answer(started["session_id"], "我们聊聊敏感词甲吧")
        assert "这个话题我聊不了哦" in replied["assistant_message"]
        assert "研究主题" in replied["assistant_message"]  # 回主线当前题
        assert _portrait(started["session_id"]).get("research_interests") in (
            None,
            [],
        )
        assert replied["current_question"]["question_id"] == "research_interests"
