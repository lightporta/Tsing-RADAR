"""对话越界话题检测（v4.0.0）。

确定性词法判定"这条消息和导师匹配/科研服务无关"，供两处使用：
1. `interview.answer_session` 防吸收守卫——跑题文本不再被写进画像（
   现状：天气文本会变成研究兴趣标签、笑话会被记成"暂不确定"）；
2. `chat.py` 已匹配态兜底——跑题消息不再静默重跑并复读匹配结果，
   改为能力引导回复。

设计约束：
- 完全不依赖 LLM，字节级确定；
- 词表保守，宁放过不误伤——合法访谈答案（含自由表述）绝不拦截；
- 越界判定只影响"是否温和重问/引导"，不改变任何画像数据语义。
"""

from __future__ import annotations

import re

# 注意：direction_map 会导入 interview，而 interview 导入本模块——
# 方向词表必须在函数内惰性构建，避免模块加载期循环导入。

# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------

# 科研通用词（方向词之外仍算"科研相关"的话题）
_RESEARCH_WORDS: tuple[str, ...] = (
    "科研", "学术", "研究", "实验", "论文", "算法", "数学", "物理", "化学",
    "生物", "编程", "代码", "数据", "智能", "神经", "优化", "隐私", "安全",
    "分布式", "编译", "体系结构", "架构", "图形", "视觉", "语音", "音频",
    "推荐系统", "推荐算法", "检索", "知识图谱", "推理", "多模态", "生成", "深度学习",
    "机器学习", "强化学习", "自然语言", "机器人", "芯片", "集成电路",
    "通信", "网络", "数据库", "操作系统", "计算机", "软件", "硬件",
    "自动化", "控制", "仿真", "电子", "材料", "能源", "环境", "医学",
    "药学", "统计", "金融", "遥感", "天文", "地理", "气象", "量子",
    "密码", "区块链", "云计算", "边缘计算", "物联网", "卫星", "航天",
    "航空", "军工", "工业",
)

_DIRECTION_WORDS_CACHE: tuple[str, ...] | None = None


def _direction_words() -> tuple[str, ...]:
    """16 规范方向名 + 全部别名（NLP↔自然语言处理、LLM↔大模型 …），惰性构建。"""
    global _DIRECTION_WORDS_CACHE
    if _DIRECTION_WORDS_CACHE is None:
        from app.services.direction_map import (
            DIRECTION_KNOWLEDGE,
            DIRECTION_MAP_ALIASES,
        )

        _DIRECTION_WORDS_CACHE = tuple(
            sorted(
                {word for pair in DIRECTION_MAP_ALIASES for word in pair}
                | set(DIRECTION_KNOWLEDGE)
            )
        )
    return _DIRECTION_WORDS_CACHE

# 兴趣声明的语法锚（"我对…感兴趣" 等声明句式，即使方向词未命中也算相关）
_DECLARATION_ANCHORS: tuple[str, ...] = (
    "我对", "我喜欢", "感兴趣", "想研究", "想做", "研究方向", "希望",
    "擅长", "在学", "专业是", "学的是", "接触过", "做过", "目前在",
    "想做的是", "我的方向", "关注", "爱好", "兴趣", "倾向于", "偏向",
)

# 不确定/探索中措辞（这类答案不算跑题，按既有逻辑处理或温和重问）
UNCERTAIN_WORDS: tuple[str, ...] = (
    "不确定", "没想好", "没想", "不知道", "不清楚", "还没", "暂不确定",
    "都可以", "都行", "随便", "无所谓", "暂时", "再说吧", "看看再说",
    "没什么想法", "没想法", "无想法", "还在探索", "边做边看",
)

_GREETING_WORDS: tuple[str, ...] = (
    "你好", "您好", "嗨", "hello", "hi", "开始", "开始吧", "你好呀",
    "大家好", "早上好", "下午好", "晚上好", "在吗", "在不在",
)

_THANKS_WORDS: tuple[str, ...] = (
    "谢谢", "感谢", "辛苦了", "多谢", "谢谢啦", "谢谢您", "thanks", "thx",
)

_ACK_WORDS: tuple[str, ...] = (
    "好的", "好", "嗯", "哦", "ok", "明白", "知道了", "收到", "行", "可以",
)

# 选择题的通用锚词：即使未命中该题关键词映射，也算"在回答"，不进跑题重问
_CHOICE_EXTRA_ANCHORS: tuple[str, ...] = (
    "动手", "实践", "代码", "做实验", "写代码", "推导", "落地", "导师",
    "老师", "方向", "想法", "考虑", "倾向", "希望", "想", "喜欢",
    "两者", "结合", "都能", "愿意", "可以", "偏好", "方式", "风格",
)

_CHOICE_SIGNAL_WORDS_CACHE: tuple[str, ...] | None = None


def _choice_signal_words() -> tuple[str, ...]:
    """四道选择题的维度关键词 + 通用锚词（惰性导入，避免与 interview 循环导入）。

    研究兴趣是自由文本题，用户常在这里直接给出偏好式表述
    （如"我偏理论证明""以后想进大厂就业"）。这类回答必须放行进既有
    信号提取逻辑，只有完全无关的话题（天气/笑话/点外卖…）才温和重问。
    """
    global _CHOICE_SIGNAL_WORDS_CACHE
    if _CHOICE_SIGNAL_WORDS_CACHE is None:
        from app.services.interview import (
            _CAREER_ORIENTATION_KEYWORDS,
            _INNOVATION_RISK_KEYWORDS,
            _MENTORSHIP_STYLE_KEYWORDS,
            _RESEARCH_MODE_KEYWORDS,
        )

        _CHOICE_SIGNAL_WORDS_CACHE = tuple(
            set(_CHOICE_EXTRA_ANCHORS)
            | {
                word
                for keywords in (
                    _RESEARCH_MODE_KEYWORDS,
                    _MENTORSHIP_STYLE_KEYWORDS,
                    _CAREER_ORIENTATION_KEYWORDS,
                    _INNOVATION_RISK_KEYWORDS,
                )
                for _, words in keywords
                for word in words
            }
        )
    return _CHOICE_SIGNAL_WORDS_CACHE

# 硬性条件题的锚词（地点/时间/学历/语言/保密/毕业/院系/经费…）
_CONSTRAINT_ANCHOR_WORDS: tuple[str, ...] = (
    "地点", "城市", "北京", "上海", "深圳", "广州", "杭州", "成都",
    "武汉", "西安", "南京", "国外", "海外", "每周", "时间", "投入",
    "全职", "兼职", "博士", "硕士", "本科", "研究生", "学历", "学位",
    "语言", "英语", "保密", "涉密", "资格", "毕业", "院系", "学院",
    "方向", "导师", "性别", "经费", "补助", "工资", "待遇", "宿舍",
    "办公室", "实验室", "团队", "名额", "招生", "延期", "转博",
    "实习", "通勤", "要求", "条件", "必须", "限定", "期望",
)

# v4.2.x 修复1/2 权威词表（interview/matching 共用，避免各模块各存一份漂移）：
# 硬约束值黑名单 —— 确认指令、态度词、开场白残留等一律不构成硬约束，
# 命中即整体清空（不产生任何草案）；这是"已放行的答案"进入画像前
# 的最后一层值清洗，与上方锚词守卫（答不上来就重问）是两道关卡。
CONSTRAINT_JUNK_SIGNALS: frozenset[str] = frozenset({
    "确认画像",
    "画像确认",
    "确认无误",
    "确认并匹配",
    "以上无误",
    "仅作参考",
    "一般偏好",
    "都可以",
    "都行",
    "无所谓",
    "不在意",
    "不重要",
    "随便",
    "不知道",
    "不清楚",
    "没想好",
    "没有什么特别的",
    "没什么特别",
    "没特别要求",
    "没有特别要求",
    "想不出来",
    "再说",
    "后面再说",
    "暂时没有",
})
# 负向表达模式（《访谈引擎修复方案》NEGATIVE_PATTERNS）
CONSTRAINT_NEGATIVE_RE = re.compile(
    r"^(?:无|没有|没有硬|无硬|不确定|都行|无所谓|不重要|随便|都可以)$"
    r"|(?:没有|无).{0,6}(?:硬性?|必须|不可|特别).{0,4}(?:要求|条件|约束|限制)"
    r"|不作硬约束|没有硬约束|无硬约束|(?:都是|只是|均为)(?:一般)?偏好|仅作参考"
)


def is_constraint_rejection_answer(answer: str) -> bool:
    """负向/态度式答案 → 无硬约束（清空草案），不进入澄清环。"""
    cleaned = answer.strip(" ，。；、,.!?！？")
    return (
        cleaned in CONSTRAINT_JUNK_SIGNALS
        or bool(CONSTRAINT_NEGATIVE_RE.search(cleaned))
    )


# 已匹配态的能力词：命中即视为"在聊我们能力范围内的事"，不回引导语
_MATCHED_CAPABILITY_WORDS_CACHE: tuple[str, ...] | None = None


def _matched_capability_words() -> tuple[str, ...]:
    global _MATCHED_CAPABILITY_WORDS_CACHE
    if _MATCHED_CAPABILITY_WORDS_CACHE is None:
        _MATCHED_CAPABILITY_WORDS_CACHE = tuple(
            set(
                _direction_words()
                + _RESEARCH_WORDS
                + (
                    "导师", "匹配", "候选", "推荐几个", "推荐一些", "推荐一下",
                    "再推荐", "给我推荐", "推荐导师", "推荐候选", "适合", "契合", "雷达",
                    "招募", "招生", "实习", "简历", "套磁", "邮件", "报告",
                    "方向", "科研", "研究", "实验室", "项目", "面试", "读研",
                    "读博", "申请", "联系", "结果", "筛选", "详情", "差距",
                    "画像", "确认", "风格", "速测", "地图", "咨询", "知识",
                    "换一批", "缩小范围", "恢复", "排除", "主题", "兴趣",
                )
            )
        )
    return _MATCHED_CAPABILITY_WORDS_CACHE


def contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def is_uncertain(text: str) -> bool:
    return contains_any(text.strip().lower(), UNCERTAIN_WORDS)


def is_acknowledgment(text: str) -> bool:
    cleaned = text.strip().lower().rstrip("。！？!?～~")
    return cleaned in _ACK_WORDS or contains_any(cleaned, _THANKS_WORDS)


def is_greeting(text: str) -> bool:
    return contains_any(text.strip().lower(), _GREETING_WORDS)


# 他人事务/索取信息/编造请求模式：即使夹带方向词（如"大模型"）或通用锚词
# （如"老师""喜欢"），也不是"你的研究兴趣"的回答 → 跑题温和重问。
_OTHER_PERSON_RE_CACHE: re.Pattern[str] | None = None
_OTHER_PERSON_PRONOUNS = frozenset(
    ("我们", "你们", "大家", "他们", "咱们", "咱", "我", "你", "他", "她")
)
_OTHER_PERSON_INFO_WORDS: tuple[str, ...] = (
    "邮箱", "电话", "联系方式", "微信", "手机号", "主页", "个人主页",
    "招生", "名额", "传闻", "八卦", "缺点", "风评", "口碑",
    # 对具体某人数据的篡改指令（如"把X老师的tolerance改成95"）
    "改成", "改为", "修改成",
)
_FABRICATION_WORDS: tuple[str, ...] = (
    "编一个", "编一份", "编造", "瞎编", "不用真实", "造假", "伪造", "虚构",
)


def _other_person_re() -> re.Pattern[str]:
    """「姓氏+名（≤4字）+ 老师/教授/导师/同学」模式（惰性构建，避免循环导入）。

    姓氏须为百家姓开头：拦截"把张三同学…"（张三）而放行"把这本书…"。
    """
    global _OTHER_PERSON_RE_CACHE
    if _OTHER_PERSON_RE_CACHE is None:
        from app.services.dialogue_intent import _COMMON_SURNAMES

        _OTHER_PERSON_RE_CACHE = re.compile(
            f"([{_COMMON_SURNAMES}][\u4e00-\u9fa5]{{0,3}}?)(老师|教授|导师|同学)"
        )
    return _OTHER_PERSON_RE_CACHE


def _is_other_person_request(text: str) -> bool:
    """「X老师/X同学 + 索取信息/求评价词」→ 他人事务，与本人研究兴趣无关。"""
    lowered = text.lower()
    if not contains_any(lowered, _OTHER_PERSON_INFO_WORDS):
        return False
    for match in _other_person_re().finditer(text):
        name = match.group(1)
        if name in _OTHER_PERSON_PRONOUNS:
            continue
        return True
    return False


def detect_off_topic_interests(answer: str) -> bool:
    """研究兴趣（文本题）：无方向词/科研词/声明锚且非问候/不确定 → 跑题。"""
    text = answer.strip()
    if not text or len(text) < 2:
        return False  # 空/过短交给既有 greeting 分支（重问）
    lowered = text.lower()
    if is_greeting(text) or is_uncertain(text):
        return False
    if _is_other_person_request(text):
        return True  # 他人信息/评价索取（v4.0.0）
    if contains_any(lowered, _FABRICATION_WORDS):
        return True  # 编造/伪造请求（v4.0.0）
    if contains_any(lowered, _direction_words() + _RESEARCH_WORDS):
        return False
    if contains_any(lowered, _DECLARATION_ANCHORS):
        return False
    if contains_any(lowered, _choice_signal_words()):
        return False  # 偏好式自由表述（含选择题信号词）放行，走既有提取逻辑
    return True


def detect_off_topic_choice(
    answer: str,
    dimension_keywords: tuple[str, ...],
) -> bool:
    """选择题守卫：命中维度关键词/通用锚词/不确定词 → 不算跑题。"""
    text = answer.strip()
    if not text:
        return False
    lowered = text.lower()
    if is_uncertain(text):
        return False
    if contains_any(
        lowered,
        dimension_keywords + _CHOICE_EXTRA_ANCHORS + _RESEARCH_WORDS,
    ):
        return False
    return True


def detect_off_topic_constraints(answer: str) -> bool:
    """硬性条件（文本题）：无约束锚词且非"无"类/确认类 → 跑题。"""
    text = answer.strip()
    if not text:
        return False
    lowered = text.lower()
    if is_uncertain(text):
        return False
    if contains_any(lowered, _CONSTRAINT_ANCHOR_WORDS):
        return False
    # "无/没有/暂无/都没有" 类答案由既有 _EMPTY_CONSTRAINTS 处理
    if lowered in {"无", "没有", "暂无", "都没有", "无硬性条件", "没有硬性条件"}:
        return False
    # v4.2.x 修复1：负向/态度式回答（"无硬约束""都行""仅作参考"…）不是跑题，
    # 必须放行到 _is_constraint_rejection 走"清空草案"分支，而不是被 nudge 重问。
    if is_constraint_rejection_answer(text):
        return False
    return True


def detect_off_topic_matched(text: str) -> bool:
    """已匹配态兜底：无任何能力词且非致谢/不确定 → 给能力引导。"""
    cleaned = text.strip()
    if not cleaned:
        return False
    if is_acknowledgment(cleaned) or is_uncertain(cleaned):
        return False
    if contains_any(cleaned.lower(), _matched_capability_words()):
        return False
    return True


# ---------------------------------------------------------------------------
# v4.3.0 轻闲聊（三明治容忍）与敏感话题（明确拒绝）
# ---------------------------------------------------------------------------

# 轻闲聊词表：非科研、非硬红线的日常话题。与问候（_GREETING_WORDS）、
# 致谢（_THANKS_WORDS）、他人事务（_OTHER_PERSON_INFO_WORDS）、编造
# （_FABRICATION_WORDS）严格互斥——命中那些类别的消息绝不进闲聊分支。
_CHITCHAT_WORDS: tuple[str, ...] = (
    "天气", "下雨", "下雪", "晴天", "刮风", "降温", "笑话", "段子", "无聊",
    "心情", "开心", "难过", "烦", "累", "困", " emo", "emo了", "游戏",
    "打游戏", "上分", "排位", "吃饭", "吃什么", "早饭", "午饭", "晚饭",
    "外卖", "睡觉", "熬夜", "失眠", "追剧", "电视剧", "综艺", "看电影",
    "音乐", "听歌", "唱歌", "逛街", "购物", "快递", "猫", "狗", "撸猫",
    "周末", "放假", "假期", "放假了", "旅游", "旅行", "运动", "健身",
    "打球", "跑步",
)


def is_light_chitchat(text: str) -> bool:
    """轻闲聊判定（v4.3.0 三明治容忍的前置条件）。

    确定性词法：命中闲聊词表，且不属问候/致谢/不确定/他人事务/编造，
    也不含任何科研/方向/声明锚词（"我对机器学习感兴趣"不是闲聊）。
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 2:
        return False
    lowered = cleaned.lower()
    if is_greeting(cleaned) or is_uncertain(cleaned) or is_acknowledgment(cleaned):
        return False
    if _is_other_person_request(cleaned):
        return False
    if contains_any(lowered, _FABRICATION_WORDS):
        return False
    if contains_any(lowered, _direction_words() + _RESEARCH_WORDS):
        return False
    if contains_any(lowered, _DECLARATION_ANCHORS):
        return False
    return contains_any(lowered, _CHITCHAT_WORDS)


_SENSITIVE_WORDS_CACHE: tuple[str, ...] | None = None


def sensitive_words() -> tuple[str, ...]:
    """敏感词表（外置配置，默认空 = 不拦截任何话题）。

    政治类/宗教类词表由部署方经 CHAT_SENSITIVE_WORDS（逗号分隔）或
    CHAT_SENSITIVE_WORDS_FILE（每行一词）注入，代码不硬编码大词表
    （与 CONTENT_SENSITIVE_WORDS 同一模式）。
    """
    global _SENSITIVE_WORDS_CACHE
    if _SENSITIVE_WORDS_CACHE is None:
        from app.core.config import settings

        words: list[str] = [
            word.strip()
            for word in (settings.CHAT_SENSITIVE_WORDS or "").split(",")
            if word.strip()
        ]
        path = settings.CHAT_SENSITIVE_WORDS_FILE
        if path:
            try:
                with open(path, encoding="utf-8") as handle:
                    words.extend(
                        line.strip()
                        for line in handle
                        if line.strip() and not line.startswith("#")
                    )
            except OSError:
                pass  # 文件缺失 → 词表保持已加载部分（fail-open 到空表=不拦截）
        _SENSITIVE_WORDS_CACHE = tuple(dict.fromkeys(words))
    return _SENSITIVE_WORDS_CACHE


def is_sensitive(text: str) -> bool:
    """敏感话题判定：命中外置词表 → 明确拒绝并回主线（v4.3.0）。"""
    cleaned = text.strip()
    if not cleaned:
        return False
    words = sensitive_words()
    if not words:
        return False
    return contains_any(cleaned.lower(), words)
