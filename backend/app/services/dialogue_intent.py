"""v2.5 对话智能基座：意图分类 + 口语-专业维度映射 + 隐式意图识别。

纯确定性规则（与项目"状态机不交给 LLM"基调一致）：
- 意图分类只决定"路由到哪个对话模块"，不改变访谈状态机；
- 口语表达映射为匹配维度标签（如"不延毕"→产出效率），用于匹配解读
  与后续推荐的解释文本，不改动排序权重本身；
- 隐式意图：统计最近若干轮用户消息中的维度关键词命中，识别用户隐含
  关注的维度（如连续询问经费/设备 → 关注「经费实力」），供匹配与招募
  输出在解释层面体现。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Sequence


class DialogueMode(str, Enum):
    """对话模式（清小搭入口的新增路由目标）。"""

    RESUME_BUILD = "resume_build"        # 从零生成简历（分步采集）
    RESUME_POLISH = "resume_polish"      # 优化已有简历（粘贴 → 润色）
    RESUME_TARGETED = "resume_targeted"  # 针对目标导师/岗位定向优化
    RECRUITMENT = "recruitment_query"    # 招募信息查询/筛选
    SCATTER = "scatter_summary"          # 四象限分类汇总
    CONSULT_EMAIL = "consult_email"      # 套磁邮件撰写
    CONSULT_FAQ = "consult_faq"          # 学业/导师 FAQ 咨询
    RESEARCH_STYLE = "research_style"    # 科研风格速测（4 题确定性分类）
    DIRECTION_MAP = "direction_map"      # 研究方向地图（说不清兴趣时的引导）
    MATCH_REFINE = "match_refine"        # 匹配结果二次筛选（仅 recommend_ready 上下文）
    MENTOR_KNOWLEDGE = "mentor_knowledge"  # 导师公开评价综述咨询（v4.0.0）
    MEMORY_VIEW = "memory_view"          # 长期记忆隐私查看（v4.1.0）
    MEMORY_CLEAR = "memory_clear"        # 长期记忆隐私清除（v4.1.0）
    NONE = "none"


# 六维主观评价键（与 services/constants.TRAIT_KEYS 对齐）
DIMENSION_ACUMEN = "acumen"
DIMENSION_NETWORK = "network"
DIMENSION_MENTORSHIP = "mentorship"
DIMENSION_TOLERANCE = "tolerance"
DIMENSION_FUNDING = "funding"
DIMENSION_EFFICIENCY = "efficiency"

# 口语表达 → 匹配维度映射词典（"想找不延毕的导师"自动关联「产出效率」等）
UTTERANCE_DIMENSION_MAP: tuple[tuple[str, str], ...] = (
    # 产出效率
    ("不延毕", DIMENSION_EFFICIENCY),
    ("按时毕业", DIMENSION_EFFICIENCY),
    ("准时毕业", DIMENSION_EFFICIENCY),
    ("产出快", DIMENSION_EFFICIENCY),
    ("发论文快", DIMENSION_EFFICIENCY),
    ("出成果快", DIMENSION_EFFICIENCY),
    ("好毕业", DIMENSION_EFFICIENCY),
    ("毕业压力小", DIMENSION_EFFICIENCY),
    # 指导意愿
    ("有人带", DIMENSION_MENTORSHIP),
    ("手把手", DIMENSION_MENTORSHIP),
    ("指导多", DIMENSION_MENTORSHIP),
    ("多指导", DIMENSION_MENTORSHIP),
    ("老师愿意教", DIMENSION_MENTORSHIP),
    ("带新人", DIMENSION_MENTORSHIP),
    # 性格包容度
    ("性格好", DIMENSION_TOLERANCE),
    ("不push", DIMENSION_TOLERANCE),
    ("不施压", DIMENSION_TOLERANCE),
    ("包容", DIMENSION_TOLERANCE),
    ("好说话", DIMENSION_TOLERANCE),
    ("不骂人", DIMENSION_TOLERANCE),
    ("脾气好", DIMENSION_TOLERANCE),
    ("氛围好", DIMENSION_TOLERANCE),
    # 经费实力
    ("经费足", DIMENSION_FUNDING),
    ("经费充足", DIMENSION_FUNDING),
    ("资源多", DIMENSION_FUNDING),
    ("设备好", DIMENSION_FUNDING),
    ("有钱", DIMENSION_FUNDING),
    ("项目多", DIMENSION_FUNDING),
    # 人脉资源
    ("人脉广", DIMENSION_NETWORK),
    ("大牛", DIMENSION_NETWORK),
    ("院士", DIMENSION_NETWORK),
    ("title高", DIMENSION_NETWORK),
    ("关系硬", DIMENSION_NETWORK),
    ("资源广", DIMENSION_NETWORK),
    # 学术敏锐度
    ("方向前沿", DIMENSION_ACUMEN),
    ("学术敏锐", DIMENSION_ACUMEN),
    ("洞察", DIMENSION_ACUMEN),
    ("有新意", DIMENSION_ACUMEN),
    ("点子多", DIMENSION_ACUMEN),
)

# 维度 → 中文标签（与 radar_chart.RADAR_DIMENSION_LABELS 的六维口径一致）
DIMENSION_LABELS: dict[str, str] = {
    DIMENSION_ACUMEN: "学术敏锐度",
    DIMENSION_NETWORK: "人脉资源",
    DIMENSION_MENTORSHIP: "指导意愿",
    DIMENSION_TOLERANCE: "性格包容度",
    DIMENSION_FUNDING: "经费实力",
    DIMENSION_EFFICIENCY: "产出效率",
}


def map_utterance_dimensions(text: str) -> list[str]:
    """把一句口语映射为命中的匹配维度列表（去重、保持词典顺序）。

    例："想找不延毕、有人带的导师" → ["efficiency", "mentorship"]
    """
    hits: list[str] = []
    for phrase, dimension in UTTERANCE_DIMENSION_MAP:
        if phrase in text and dimension not in hits:
            hits.append(dimension)
    return hits


def detect_implicit_dimension_attention(
    user_messages: Sequence[str],
    *,
    window: int = 4,
) -> list[str]:
    """统计最近 window 轮用户消息的维度关键词命中，识别隐式关注维度。

    命中 >= 2 次的维度视为"隐式关注"，按命中次数降序返回；
    命中 1 次不视为关注（避免单次口语被过度解读）。
    """
    counts: dict[str, int] = {}
    for message in user_messages[-window:]:
        for dimension in map_utterance_dimensions(message):
            counts[dimension] = counts.get(dimension, 0) + 1
    return sorted(
        (dim for dim, count in counts.items() if count >= 2),
        key=lambda dim: counts[dim],
        reverse=True,
    )


# 各对话模式的触发词（子串匹配，风格与 chat.py 的 _REPORT_INTENTS 对齐）
_RESUME_BUILD_TERMS = (
    "写简历",
    "写一份简历",
    "做简历",
    "做一份简历",
    "帮我建简历",
    "生成简历",
    "生成个简历",
    "生成一份简历",
    "创建简历",
    "简历生成",
    "从零写",
    "从零生成",
    "从零开始写",
    "从零搞",
    "从零做",
    "从零弄",
    "帮我制作简历",
)
_RESUME_POLISH_TERMS = (
    "优化简历",
    "润色",
    "润色简历",
    "打磨简历",
    "打磨下",
    "打磨一下",
    "打磨打磨",
    "改简历",
    "改改",
    "简历润色",
    "简历优化",
    "优化下",
    "优化一下",
    "优化优化",
    "帮我改简历",
    "完善简历",
    "看看简历",
    "看下简历",
    "看下我的简历",
)
_RESUME_TARGETED_TERMS = (
    "定向优化",
    "针对简历",
    "投递优化",
    "适配岗位",
    "适配导师",
    "适配",
    "适合这个岗位",
    "适合这个",
    "针对岗位",
    "针对导师",
    "针对",
    "课题组",
    "的组",
    "投",
)
_RECRUITMENT_TERMS = (
    "招募",
    "实习信息",
    "实习吗",
    "实习岗位",
    "实习机会",
    "招实习",
    "招生信息",
    "科研助理",
    "找实习",
    "找科研",
    "招募信息",
    "招人",
    "岗位",
    "招聘",
    "工作机会",
    "有在招",
)
_SCATTER_TERMS = (
    "四象限",
    "热区",
    "方向分类",
    "导师分布",
    "国热",
    "国冷",
    "私热",
    "私冷",
    "热门分布",
    "散点",
    "方向是热门",
    "方向是冷门",
    "方向算热门",
    "方向算冷门",
    "热门还是",
    "冷门还是",
    "热门啊",
    "冷门啊",
    "热门吗",
    "冷门吗",
)
_CONSULT_EMAIL_TERMS = (
    "写邮件",
    "写封",
    "写一封",
    "套磁",
    "联系导师",
    "邮件初稿",
    "给老师写信",
    "给老师发邮件",
    "发邮件",
    "发封",
    "发个",
    "发简历",
    "简历发给",
    "怎么联系",
)
_CONSULT_FAQ_TERMS = (
    "组会",
    "延毕",
    "毕业难度",
    "招生名额",
    "学生评价",
    "风评",
    "口碑",
    "实验室氛围",
    "怎么选导师",
    "怎么匹配",
    "怎么投递",
    "投递流程",
    "雷达图是什么",
    "雷达图是啥",
    "雷达图是干嘛的",
    "雷达图是干什么的",
    "雷达图有什么用",
    "匹配怎么算",
    "如何开始",
    "怎么用",
    "能干什么",
    "老师怎么样",
    "老师咋样",
    "老师如何",
    "导师怎么样",
    "导师咋样",
    "导师如何",
    "简历",
)

# 科研风格速测触发词（v3.1.4，学竞品清研向导的科研风格测试，做轻量确定性版）
_RESEARCH_STYLE_TERMS = (
    "科研风格",
    "研究风格",
    "风格测试",
    "科研方式测试",
    "研究偏好",
    "我适合什么科研",
    "我适合做什么方向",
    "测测我",
    "测一下我",
    "自我认知",
    "了解自己",
)
# 研究方向地图触发词（"说不清兴趣"时的方向引导）。刻意用完整问句结构，
# 不引入裸词"方向"，避免拦截"我研究方向是自然语言处理"这类访谈自述。
_DIRECTION_MAP_TERMS = (
    "有哪些方向",
    "什么方向",
    "研究方向地图",
    "方向地图",
    "有哪些研究方向",
    "方向有哪些",
    "这个系有什么方向",
    "院系有哪些方向",
    "能做什么方向",
    "想做什么方向",
    "方向怎么选",
    "怎么选方向",
    "研究方向有哪些",
)

# —— v4.1.0 长期记忆隐私入口（查看/清除）——
# 刻意用完整词组，避免裸词"记忆"拦截访谈中的自然表达。
_MEMORY_VIEW_TERMS = (
    "查看记忆",
    "看看记忆",
    "我的记忆",
    "你记住了什么",
    "你记得我什么",
    "你记得我的什么",
    "记忆列表",
)
_MEMORY_CLEAR_TERMS = (
    "清除记忆",
    "清空记忆",
    "删除记忆",
    "忘掉我",
    "忘记我",
    "删除我的记忆",
)
# 记忆清除的二次确认指令（与 _REPORT_DELIVERY_CONFIRMATION 同风格）
MEMORY_CLEAR_CONFIRMATION = "确认清除记忆"


# —— v4.0.0 导师公开评价综述咨询（任务1 A-1 确定性词法索引）——
# 确定性模式：`姓名 + 老师/教授/导师 + 咨询词`。防误伤设计：
# - 姓名必须位于消息开头（允许少量前置词），避免把句中"方向老师"
#   "课题组老师"等误判为人名；
# - 中文姓名须以常见百家姓单姓开头，并用停用词排除"研究生导师/
#   我们老师/专业课老师"等非人名组合；英文姓名（如 Charles David）
#   单独按字母名匹配；
# - 必须有咨询词（怎么样/如何/评价/口碑…）或以 吗/呢/么 结尾，
#   裸"XX老师"不拦截（留给简历定向/套磁等既有意图）。
_MENTOR_QUERY_PREFIXES = (
    "请问",
    "想了解",
    "了解下",
    "了解一下",
    "咨询下",
    "咨询一下",
    "关于",
    "帮我看看",
    "帮我查查",
    "帮我查一下",
    "查一下",
    "查查",
    "查下",
    "把",
    "说说",
    "听说",
)
_MENTOR_QUERY_SUFFIXES = (
    "长聘教授",
    "长聘副教授",
    "副研究员",
    "助理教授",
    "副教授",
    "研究员",
    "老师",
    "教授",
    "导师",
)
_MENTOR_QUERY_CONSULT = (
    "怎么样",
    "如何",
    "评价",
    "口碑",
    "风评",
    "水平",
    "好不好",
    "带学生",
    "招生",
    "情况",
    "怎么样啊",
    "怎么样呢",
    "怎么样呀",
    "怎么样嘛",
    # v4.0.0 导师信息类咨询（联系方式/主页/名额/缺点/传闻等）也路由知识库；
    # 知识库只含公开综述级聚合，缺字段时诚实缺省，绝不编造。
    "邮箱",
    "电话",
    "联系方式",
    "微信",
    "手机号",
    "主页",
    "个人主页",
    "名额",
    "缺点",
    "传闻",
    "八卦",
    "研究什么",
    "在做什么",
    "做什么",
)
_MENTOR_NAME_STOPWORDS = frozenset(
    (
        "我们",
        "你们",
        "大家",
        "咱们",
        "他们",
        "研究生",
        "博士生",
        "硕士生",
        "本科生",
        "辅导员",
        "班主任",
        "方向",
        "科研",
        "实验室",
        "课题组",
        "团队",
        "专业",
        "课程",
        "论文",
        "学术",
        "学院",
        "大学",
        "学校",
        "系里",
        "全系",
        "领域",
        "行业",
        "岗位",
        "工作",
        "实习",
        "项目",
        "组会",
        "学位",
        "毕业",
        "招生",
        "录取",
        "老师",
        "导师",
        "教授",
        "学生",
        "同学",
    )
)
# 百家姓常用单姓（防"方向老师/神经网络老师"类误判为人名）
_COMMON_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀郏浦尚农"
    "温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘"
    "匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空"
    "曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
_MENTOR_LATIN_NAME_RE = re.compile(r"^([A-Za-z][A-Za-z .'-]{1,30}?)(老师|教授|导师)")


def _mentor_consult_signal(tail: str) -> bool:
    """咨询信号：含咨询词，或以 吗/呢/么/嘛/呀 结尾。"""
    if any(word in tail for word in _MENTOR_QUERY_CONSULT):
        return True
    return tail.rstrip("。，！？!? ").endswith(("吗", "呢", "么", "嘛", "呀"))


def extract_mentor_query_name(text: str) -> str | None:
    """提取导师综述咨询的姓名；非此类咨询返回 None（确定性、防误伤）。

    例："李琦老师怎么样" → "李琦"；"研究生导师怎么样" → None。
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    for prefix in _MENTOR_QUERY_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break

    latin = _MENTOR_LATIN_NAME_RE.match(stripped)
    if latin:
        name = latin.group(1).strip()
        tail = stripped[latin.end():].strip()
        if name and _mentor_consult_signal(tail):
            return name
        return None

    for suffix in _MENTOR_QUERY_SUFFIXES:
        match = re.match(rf"^([\u4e00-\u9fa5]{{2,4}}){re.escape(suffix)}(.*)$", stripped)
        if not match:
            continue
        name, tail = match.group(1), match.group(2).strip()
        if name in _MENTOR_NAME_STOPWORDS:
            return None
        if name[0] not in _COMMON_SURNAMES:
            return None
        if not tail or not _mentor_consult_signal(tail):
            return None
        return name
    return None

# 简历模式内的控制意图（与访谈 _CONFIRM_SIGNALS 风格一致）
RESUME_CANCEL_TERMS = ("取消", "退出", "不写了", "算了", "停一下")
RESUME_DONE_TERMS = ("生成", "完成", "好了", "可以了", "生成简历", "就这样")

# 简历文本特征锚点：直接粘贴的简历通常同时出现 ≥2 个字段标签。
# 刻意使用完整字段名（而非"项目""技能"等单字），避免把访谈中
# 长段科研自述误判成简历粘贴。
_RESUME_PASTE_ANCHORS = (
    "姓名",
    "教育背景",
    "教育经历",
    "项目经历",
    "科研经历",
    "研究经历",
    "工作经历",
    "联系方式",
    "技能",
    "荣誉",
    "获奖",
    "任职",
)


def _looks_like_resume_paste(text: str) -> bool:
    """启发式：较长文本且含 ≥2 个简历字段标签 → 视为直接粘贴的简历原文。"""
    if len(text) < 60:
        return False
    hits = sum(1 for anchor in _RESUME_PASTE_ANCHORS if anchor in text)
    return hits >= 2


def classify_dialogue_intent(
    latest_user: str,
    *,
    user_messages: Sequence[str],
) -> DialogueMode:
    """按优先级返回对话模式；未命中返回 DialogueMode.NONE。

    优先级：简历定向 > 简历优化 > 简历从零 > 招募 > 四象限 > 套磁 > FAQ。
    「定向优化」必须在「优化」之前判定（"针对 XX 老师优化简历"同时命中
    两者时归入定向）。
    """
    text = (latest_user or "").strip()
    if not text:
        return DialogueMode.NONE
    if any(term in text for term in _RESUME_TARGETED_TERMS) and any(
        term in text for term in (_RESUME_POLISH_TERMS + ("简历",))
    ):
        return DialogueMode.RESUME_TARGETED
    if any(term in text for term in _RESUME_POLISH_TERMS):
        return DialogueMode.RESUME_POLISH
    if any(term in text for term in _RESUME_BUILD_TERMS):
        return DialogueMode.RESUME_BUILD
    if any(term in text for term in _RECRUITMENT_TERMS):
        return DialogueMode.RECRUITMENT
    # 招募详情追问："第 1 个 / 第一个" 是对上文岗位列表的指代
    if re.search(r"第\s*[一二两三四五六七八九十\d]+\s*个", text):
        return DialogueMode.RECRUITMENT
    if any(term in text for term in _SCATTER_TERMS):
        return DialogueMode.SCATTER
    if any(term in text for term in _CONSULT_EMAIL_TERMS):
        return DialogueMode.CONSULT_EMAIL
    if any(term in text for term in _RESEARCH_STYLE_TERMS):
        return DialogueMode.RESEARCH_STYLE
    if any(term in text for term in _DIRECTION_MAP_TERMS):
        return DialogueMode.DIRECTION_MAP
    # v4.0.0 导师公开评价综述（"李琦老师怎么样"）：须在 FAQ 之前判定
    # （"老师怎么样"同时是 FAQ 触发词，但无姓名时 extract 返回 None）。
    if extract_mentor_query_name(text):
        return DialogueMode.MENTOR_KNOWLEDGE
    # v4.1.0 长期记忆隐私入口：清除优先于查看（"清除记忆"不含查看词，
    # 两者词表无交叉，顺序仅作防御）；须在 FAQ 之前判定。
    if any(term in text for term in _MEMORY_CLEAR_TERMS):
        return DialogueMode.MEMORY_CLEAR
    if any(term in text for term in _MEMORY_VIEW_TERMS):
        return DialogueMode.MEMORY_VIEW
    if any(term in text for term in _CONSULT_FAQ_TERMS):
        return DialogueMode.CONSULT_FAQ
    # 直接粘贴简历原文（无触发词）→ 归入简历优化，等待润色
    if _looks_like_resume_paste(text):
        return DialogueMode.RESUME_POLISH
    return DialogueMode.NONE
