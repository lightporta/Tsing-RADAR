"""研究方向地图：帮"说不清兴趣"的用户从公开学科方向清单里找到入口。

设计动机：学习竞品"清研向导"的院系研究方向地图（方向 + 说明 + 关键词 +
参考教师）。我们只输出"方向 + 一句话说明 + 示例关键词"，刻意**不输出
参考教师名单** —— 教师-方向绑定属于非公开数据治理范围，知识库无证据时
不编造（D1 红线）。方向表本身是公开学科常识，无隐私内容。

方向覆盖面比竞品更宽：除计算机相关外，覆盖材料/生物/化学/物理/新能源等
科研招募常见方向，与 recruitment_dialogue.DIRECTION_KEYWORDS 口径打通，
方便用户选方向后直接进入招募筛选/画像回填。
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.orm import Session

from app.services.dialogue_state_store import (
    clear_dialogue_state,
    get_dialogue_mode,
    upsert_dialogue_state,
)
from app.services.interview import upsert_portrait_field

MODE_DIRECTION_MAP = "direction_map"

# (规范方向名, 一句话说明, 示例关键词)
DIRECTION_MAP_DATA: tuple[tuple[str, str, str], ...] = (
    ("大模型 / 大语言模型", "大规模预训练语言模型的理论、对齐、智能体与评测。", "LLM、大模型、对齐、智能体"),
    ("自然语言处理", "文本理解、生成、机器翻译与信息抽取等 NLP 核心技术。", "NLP、文本生成、信息抽取"),
    ("计算机视觉", "图像/视频理解、生成与多模态感知。", "视觉、图像、视频、多模态"),
    ("机器学习 / 深度学习", "统计学习、神经网络、表示学习与优化。", "深度学习、表示学习、优化"),
    ("强化学习 / 智能决策", "序贯决策、博弈与机器人控制中的学习方法。", "强化学习、决策、博弈"),
    ("机器人 / 无人系统", "移动机器人、无人机、自动驾驶与具身智能。", "机器人、无人机、自动驾驶"),
    ("系统 / 体系结构 / 操作系统", "计算机体系结构、操作系统、分布式与并行系统。", "体系结构、操作系统、分布式"),
    ("网络 / 网络安全", "计算机网络、协议、系统与网络安全。", "网络、安全、密码学"),
    ("数据库 / 数据管理", "数据库系统、数据挖掘与大数据分析。", "数据库、数据挖掘、大数据"),
    ("芯片 / 集成电路", "芯片设计、EDA、集成电路与微体系结构。", "芯片、集成电路、EDA"),
    ("通信 / 信号处理", "无线通信、编码、信号与信息处理。", "通信、信号处理、编码"),
    ("理论计算", "算法、复杂度、形式化方法与计算理论。", "算法、复杂度、形式化"),
    ("材料 / 化学 / 物理", "材料计算、化学信息学、凝聚态与计算物理。", "材料、化学、物理"),
    ("生物 / 计算生物学", "生物信息学、计算生物学与医学 AI。", "生物信息、基因组、医学AI"),
    ("新能源 / 储能", "新能源材料、器件、系统与储能技术。", "新能源、储能、电池"),
    ("控制 / 优化 / 仿真", "自动控制、数学优化与系统仿真。", "控制、优化、仿真"),
)

# 方向别名 → 规范方向名（复用 recruitment_dialogue.DIRECTION_ALIASES 的
# 同义归一思路，词面匹配、不做语义推断）
DIRECTION_MAP_ALIASES: tuple[tuple[str, str], ...] = (
    ("大模型", "大模型 / 大语言模型"),
    ("llm", "大模型 / 大语言模型"),
    ("自然语言处理", "自然语言处理"),
    ("nlp", "自然语言处理"),
    ("计算机视觉", "计算机视觉"),
    ("cv", "计算机视觉"),
    ("机器学习", "机器学习 / 深度学习"),
    ("深度学习", "机器学习 / 深度学习"),
    ("强化学习", "强化学习 / 智能决策"),
    ("rl", "强化学习 / 智能决策"),
    ("机器人", "机器人 / 无人系统"),
    ("自动驾驶", "机器人 / 无人系统"),
    ("无人系统", "机器人 / 无人系统"),
    ("操作系统", "系统 / 体系结构 / 操作系统"),
    ("体系结构", "系统 / 体系结构 / 操作系统"),
    ("分布式", "系统 / 体系结构 / 操作系统"),
    ("网络", "网络 / 网络安全"),
    ("网络安全", "网络 / 网络安全"),
    ("数据库", "数据库 / 数据管理"),
    ("数据挖掘", "数据库 / 数据管理"),
    ("芯片", "芯片 / 集成电路"),
    ("集成电路", "芯片 / 集成电路"),
    ("通信", "通信 / 信号处理"),
    ("信号处理", "通信 / 信号处理"),
    ("理论计算", "理论计算"),
    ("材料", "材料 / 化学 / 物理"),
    ("化学", "材料 / 化学 / 物理"),
    ("物理", "材料 / 化学 / 物理"),
    ("生物", "生物 / 计算生物学"),
    ("计算生物", "生物 / 计算生物学"),
    ("新能源", "新能源 / 储能"),
    ("储能", "新能源 / 储能"),
    ("控制", "控制 / 优化 / 仿真"),
    ("仿真", "控制 / 优化 / 仿真"),
    ("优化", "控制 / 优化 / 仿真"),
)

_DIRECTION_INTRO = (
    "我整理了一份公开研究方向地图（方向 + 一句话说明 + 示例关键词）。"
    "它只列学科方向本身，不涉及具体导师，帮你先把“说不清的兴趣”变成"
    "可选的方向词。\n"
)

# 规范方向 → 入门知识点（v3.1.7 能力差距分析用）。
# 红线：只列公开学科常识，**绝不出现教师名单**；与 DIRECTION_MAP_DATA
# 规范名一一对应。知识映射缺失时调用方诚实省略，不编造内容。
DIRECTION_KNOWLEDGE: dict[str, tuple[str, ...]] = {
    "大模型 / 大语言模型": (
        "Transformer 架构与注意力机制",
        "预训练与指令微调",
        "对齐（RLHF）与评测",
        "智能体 / RAG 与工具调用",
    ),
    "自然语言处理": (
        "词向量与序列建模",
        "文本生成与机器翻译",
        "信息抽取与问答",
        "文本分类与情感分析",
    ),
    "计算机视觉": (
        "卷积网络与特征提取",
        "目标检测与图像分割",
        "图像 / 视频生成",
        "多模态对齐",
    ),
    "机器学习 / 深度学习": (
        "经典统计学习（回归 / 分类 / 聚类）",
        "神经网络与反向传播",
        "表示学习与自监督",
        "优化算法与正则化",
    ),
    "强化学习 / 智能决策": (
        "马尔可夫决策过程与价值函数",
        "Q 学习与策略梯度",
        "离线强化学习与模仿学习",
        "博弈与序贯决策",
    ),
    "机器人 / 无人系统": (
        "运动学与动力学建模",
        "SLAM 与感知融合",
        "路径规划与运动控制",
        "具身智能与操作学习",
    ),
    "系统 / 体系结构 / 操作系统": (
        "计算机组成与指令集",
        "操作系统内核与并发",
        "分布式系统与一致性",
        "性能分析与优化",
    ),
    "网络 / 网络安全": (
        "TCP/IP 协议栈",
        "路由与传输层",
        "密码学基础",
        "入侵检测与威胁建模",
    ),
    "数据库 / 数据管理": (
        "关系模型与 SQL",
        "索引与查询优化",
        "事务与并发控制",
        "数据挖掘与大数据计算",
    ),
    "芯片 / 集成电路": (
        "数字电路与逻辑设计",
        "RTL 与硬件描述语言",
        "EDA 工具链与物理设计",
        "半导体工艺与器件物理",
    ),
    "通信 / 信号处理": (
        "信号与系统",
        "数字通信与调制编码",
        "信道编码与信息论",
        "无线通信与 MIMO",
    ),
    "理论计算": (
        "算法设计与复杂度分析",
        "图论与组合优化",
        "形式化方法与逻辑",
        "概率论与随机算法",
    ),
    "材料 / 化学 / 物理": (
        "材料结构与表征",
        "量子力学基础",
        "计算模拟（DFT / 分子动力学）",
        "化学信息学与数据库",
    ),
    "生物 / 计算生物学": (
        "分子生物学基础",
        "基因组学与序列分析",
        "生物信息学工具与数据库",
        "医学 AI 与影像分析",
    ),
    "新能源 / 储能": (
        "电化学基础与电池原理",
        "材料电化学与表征",
        "储能系统与电网集成",
        "新能源器件与测试",
    ),
    "控制 / 优化 / 仿真": (
        "自动控制原理（反馈与稳定性）",
        "线性规划与凸优化",
        "系统建模与仿真",
        "最优控制与状态估计",
    ),
}

# 方向地图内"放弃选择"的短词
_DIRECTION_CANCEL_TERMS = ("取消", "退出", "算了", "不选了", "不用了")


def resolve_direction(alias: str) -> str | None:
    """方向别名 → 规范方向名；未命中返回 None。

    v3.1.6：别名未命中时再与规范方向名全名比对（回复完整规范名也能命中）。
    """
    key = (alias or "").strip().lower()
    if not key:
        return None
    for phrase, canonical in DIRECTION_MAP_ALIASES:
        if phrase.lower() == key:
            return canonical
    for name, _desc, _keywords in DIRECTION_MAP_DATA:
        if name.lower() == key:
            return name
    return None


def knowledge_for_terms(
    terms: Sequence[str],
) -> tuple[str | None, tuple[str, ...]]:
    """候选方向词列表 → (规范方向名, 入门知识点)；未映射返回 (None, ())。

    v3.1.7 能力差距分析用。顺序：逐词 resolve_direction（别名/规范全名）
    → 未命中时与规范名双向子串比对（如 "大模型" 命中 "大模型 / 大语言
    模型"）。只做词面匹配，不做语义推断；知识映射缺失时调用方诚实省略。
    """
    for term in terms or ():
        text = (term or "").strip()
        if not text:
            continue
        canonical = resolve_direction(text)
        if canonical is not None and canonical in DIRECTION_KNOWLEDGE:
            return canonical, DIRECTION_KNOWLEDGE[canonical]
    for term in terms or ():
        text = (term or "").strip().lower()
        if not text:
            continue
        for canonical, points in DIRECTION_KNOWLEDGE.items():
            name = canonical.lower()
            if name in text or text in name:
                return canonical, points
    return None, ()


def render_direction_map() -> str:
    """输出方向地图（确定性、单轮完成）。"""
    lines = [_DIRECTION_INTRO, "【研究方向地图】"]
    for name, desc, keywords in DIRECTION_MAP_DATA:
        lines.append(f"- **{name}**：{desc}\n  示例关键词：{keywords}")
    lines.append(
        "\n回复其中一个方向名（如「大模型」「自然语言处理」），"
        "我会基于它继续帮你匹配导师或查询招募岗位。"
    )
    return "\n".join(lines)


def handle_direction_map(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
) -> str | None:
    """方向地图的多轮入口（状态存 dialogue_sessions）。

    v3.1.6 从"单轮静态地图"升级为闭环：首轮触发渲染地图并记录模式；
    下一轮用户回复方向名 → 解析为规范方向 → 回填画像 research_interests
    （合并去重，由 upsert_portrait_field 保证）→ 引导匹配/招募。
    未命中方向（或取消）时清模式并返回 None 放行走主流程 —— 只拦截一次，
    不吞"我研究方向是自然语言处理"这类访谈自述。
    """
    text = (latest_user or "").strip()
    mode = get_dialogue_mode(db, session_id=session_id, student_id=student_id)
    if mode != MODE_DIRECTION_MAP:
        upsert_dialogue_state(
            db,
            session_id=session_id,
            student_id=student_id,
            mode=MODE_DIRECTION_MAP,
            state={"step": 0},
        )
        return render_direction_map()

    if any(term in text for term in _DIRECTION_CANCEL_TERMS):
        clear_dialogue_state(db, session_id=session_id, student_id=student_id)
        return "已退出方向地图，可以继续聊导师匹配、招募机会或访谈。"
    canonical = resolve_direction(text)
    clear_dialogue_state(db, session_id=session_id, student_id=student_id)
    if canonical is None:
        # 未命中：只放行一次（不拦截后续消息），返回 None 走主流程
        return None
    upsert_portrait_field(
        db,
        session_id=session_id,
        student_id=student_id,
        changes={"research_interests": [canonical]},
    )
    return (
        f"已记录研究方向：**{canonical}**。\n\n"
        "画像有更新，需要重新确认后再匹配：回复「确认画像」；"
        "或回复「招募」查询在招岗位；也可以直接说「匹配」继续。"
    )
