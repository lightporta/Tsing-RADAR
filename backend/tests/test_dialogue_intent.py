"""v2.5 对话智能基座测试：意图分类优先级、口语-维度映射、隐式意图识别。"""

from __future__ import annotations

from app.services.dialogue_intent import (
    DialogueMode,
    RESUME_CANCEL_TERMS,
    RESUME_DONE_TERMS,
    classify_dialogue_intent,
    detect_implicit_dimension_attention,
    map_utterance_dimensions,
)


def test_map_utterance_dimensions_hits_and_dedup():
    # "不延毕、有人带" → 产出效率 + 指导意愿
    hits = map_utterance_dimensions("想找不延毕、有人带的导师")
    assert "efficiency" in hits
    assert "mentorship" in hits
    assert len(hits) == len(set(hits))

    # 无关口语不产生映射
    assert map_utterance_dimensions("今天天气不错") == []

    # 一句话内重复命中同一维度只记一次
    repeated = map_utterance_dimensions("老师经费足、资源多，而且项目多")
    assert repeated.count("funding") == 1


def test_map_utterance_dimensions_common_phrases():
    expectations = {
        "不延毕": ["efficiency"],
        "按时毕业": ["efficiency"],
        "有人带": ["mentorship"],
        "性格好": ["tolerance"],
        "经费足": ["funding"],
        "人脉广": ["network"],
        "方向前沿": ["acumen"],
    }
    for phrase, expected in expectations.items():
        assert map_utterance_dimensions(phrase) == expected


def test_detect_implicit_dimension_attention_needs_two_hits():
    messages = [
        "我想找经费足的课题组",
        "你们有经费充足的导师吗",
    ]
    assert "funding" in detect_implicit_dimension_attention(messages)

    # 单次命中不算"关注"，避免过度解读
    single = ["我想找经费足的课题组", "你好", "帮我看一下匹配"]
    assert detect_implicit_dimension_attention(single) == []


def test_detect_implicit_dimension_attention_respects_window():
    messages = [
        "有人带吗", "有人带吗",  # 第 1、2 轮命中
        "不延毕", "不延毕",      # 第 3、4 轮命中
    ]
    attention = detect_implicit_dimension_attention(messages, window=2)
    # 只统计最近 2 轮：只有 efficiency 命中两次
    assert attention == ["efficiency"]
    full = detect_implicit_dimension_attention(messages, window=10)
    assert "mentorship" in full and "efficiency" in full


def test_classify_dialogue_intent_priority_order():
    assert (
        classify_dialogue_intent(
            "针对张三老师的课题组优化简历", user_messages=[]
        )
        == DialogueMode.RESUME_TARGETED
    )
    assert (
        classify_dialogue_intent("帮我润色一下简历", user_messages=[])
        == DialogueMode.RESUME_POLISH
    )
    assert (
        classify_dialogue_intent("帮我从零写一份简历", user_messages=[])
        == DialogueMode.RESUME_BUILD
    )
    assert (
        classify_dialogue_intent("计算机系最近有急招科研助理吗", user_messages=[])
        == DialogueMode.RECRUITMENT
    )
    assert (
        classify_dialogue_intent("四象限分布怎么样", user_messages=[])
        == DialogueMode.SCATTER
    )
    assert (
        classify_dialogue_intent("帮我写一封套磁邮件", user_messages=[])
        == DialogueMode.CONSULT_EMAIL
    )
    assert (
        classify_dialogue_intent("组会频率一般怎么样", user_messages=[])
        == DialogueMode.CONSULT_FAQ
    )
    assert (
        classify_dialogue_intent("今天天气不错", user_messages=[])
        == DialogueMode.NONE
    )


def test_classify_dialogue_intent_empty_and_blank():
    assert classify_dialogue_intent("", user_messages=[]) == DialogueMode.NONE
    assert classify_dialogue_intent("   ", user_messages=[]) == DialogueMode.NONE


def test_resume_control_terms_present():
    assert any(term in "取消" for term in RESUME_CANCEL_TERMS)
    assert any(term in "生成" for term in RESUME_DONE_TERMS)


def test_classify_dialogue_intent_natural_language_variants():
    """正常人口语说法批量路由（v3.1.3 扩充触发词后的回归护栏）。"""
    cases = [
        # 简历从零
        ("我想做一份简历", DialogueMode.RESUME_BUILD),
        ("帮我从零搞一份简历", DialogueMode.RESUME_BUILD),
        ("帮我生成个简历", DialogueMode.RESUME_BUILD),
        # 简历优化
        ("优化下我的简历", DialogueMode.RESUME_POLISH),
        ("帮我优化一下简历", DialogueMode.RESUME_POLISH),
        ("这简历太烂了帮我改改", DialogueMode.RESUME_POLISH),
        ("打磨一下我的简历", DialogueMode.RESUME_POLISH),
        # 简历定向
        ("把简历适配到 CV 组", DialogueMode.RESUME_TARGETED),
        ("帮我把简历改得适合这个岗位", DialogueMode.RESUME_TARGETED),
        ("我要投李教授的组，帮我改简历", DialogueMode.RESUME_TARGETED),
        ("投简历", DialogueMode.RESUME_TARGETED),
        # 招募
        ("你们这有实习吗", DialogueMode.RECRUITMENT),
        ("有实习机会吗", DialogueMode.RECRUITMENT),
        # 四象限
        ("现在哪些方向是热门啊", DialogueMode.SCATTER),
        ("这个方向算热门还是冷门", DialogueMode.SCATTER),
        # 套磁
        ("帮我写封邮件给老师", DialogueMode.CONSULT_EMAIL),
        ("我想给王老师发封邮件", DialogueMode.CONSULT_EMAIL),
        ("帮我把简历发给老师", DialogueMode.CONSULT_EMAIL),
        # FAQ
        ("王老师怎么样", DialogueMode.CONSULT_FAQ),
        ("雷达图是啥", DialogueMode.CONSULT_FAQ),
        ("雷达图是干嘛的", DialogueMode.CONSULT_FAQ),
        ("简历咋弄", DialogueMode.CONSULT_FAQ),
        # 闲聊不被误路由
        ("你好", DialogueMode.NONE),
        ("谢谢", DialogueMode.NONE),
        ("我有一段实习经历", DialogueMode.NONE),
        ("我研究的方向是自然语言处理", DialogueMode.NONE),
    ]
    for text, expected in cases:
        assert classify_dialogue_intent(text, user_messages=[text]) == expected, text


def test_classify_dialogue_intent_research_style_and_direction_map():
    """v3.1.4 科研风格速测 / 方向地图触发词（完整问句结构，防访谈误伤）。"""
    assert (
        classify_dialogue_intent("测测我的科研风格", user_messages=[])
        == DialogueMode.RESEARCH_STYLE
    )
    assert (
        classify_dialogue_intent("我想测一下科研风格", user_messages=[])
        == DialogueMode.RESEARCH_STYLE
    )
    assert (
        classify_dialogue_intent("我适合做什么方向", user_messages=[])
        == DialogueMode.RESEARCH_STYLE
    )
    assert (
        classify_dialogue_intent("有哪些方向", user_messages=[])
        == DialogueMode.DIRECTION_MAP
    )
    assert (
        classify_dialogue_intent("你们系有哪些研究方向", user_messages=[])
        == DialogueMode.DIRECTION_MAP
    )
    assert (
        classify_dialogue_intent("这个系有什么方向", user_messages=[])
        == DialogueMode.DIRECTION_MAP
    )
    assert (
        classify_dialogue_intent("方向怎么选", user_messages=[])
        == DialogueMode.DIRECTION_MAP
    )


def test_classify_dialogue_intent_style_beats_direction_map_on_self_knowledge():
    # "测测我"（自我认知）优先于"什么方向"（方向地图）
    assert (
        classify_dialogue_intent("测测我适合做什么方向", user_messages=[])
        == DialogueMode.RESEARCH_STYLE
    )


def test_classify_dialogue_intent_does_not_intercept_interview_statement():
    """访谈/画像自述不得被方向地图或风格测试触发词拦截（裸"方向"不触发）。"""
    assert (
        classify_dialogue_intent("我研究方向是自然语言处理", user_messages=[])
        == DialogueMode.NONE
    )
    assert (
        classify_dialogue_intent(
            "我对计算机视觉和强化学习比较感兴趣", user_messages=[]
        )
        == DialogueMode.NONE
    )
    assert (
        classify_dialogue_intent("我偏好理论推导的研究", user_messages=[])
        == DialogueMode.NONE
    )


def test_classify_dialogue_intent_resume_paste_heuristic():
    """直接粘贴简历原文（无触发词）→ 简历优化；长段科研自述不误判。"""
    paste = (
        "姓名：张三\n"
        "教育背景：清华大学计算机系\n"
        "项目经历：NLP 情感分类项目，负责模型训练\n"
        "联系方式：test@example.com\n"
        "技能：Python、PyTorch"
    )
    assert len(paste) >= 60
    assert (
        classify_dialogue_intent(paste, user_messages=[paste])
        == DialogueMode.RESUME_POLISH
    )
    # 访谈中长段科研自述（含"项目""技能"等单字但无字段标签组合）不拦截
    story = (
        "我本科做过情感分类相关的项目，用 Python 和 PyTorch 训练了模型，"
        "还参加了挑战杯拿了二等奖，平时在班里当学习委员，英语过了六级，"
        "希望找一个能按时毕业、经费充足的课题组继续做 NLP 方向的研究。"
    )
    assert len(story) >= 60
    assert classify_dialogue_intent(story, user_messages=[story]) == DialogueMode.NONE
