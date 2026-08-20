"""科研风格速测：4 题确定性分类，输出风格名称 + 通俗解释 + 匹配建议。

设计动机：学习竞品"清研向导"的科研风格测试（16 题 LLM 判定），但做成
我们的轻量确定性版本 —— 4 题、规则表分类、不依赖 LLM、结果可复现可测试。
语义与诚实性红线保持一致：
- 只描述用户"当前更偏好的科研启动方式/范围/推进方式"，不判断是否适合科研、
  不评价能力高低（措辞与竞品对齐，避免制造"你很弱/你很适合"的暗示）。
- 结果仅作偏好参考，可回填画像 research_mode（theory/engineering/mixed），
  不写入任何六维导师评分，不参与门控数据。
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.orm import Session

from app.services.dialogue_intent import _RESEARCH_STYLE_TERMS
from app.services.dialogue_state_store import (
    clear_dialogue_state,
    get_dialogue_mode,
    get_dialogue_state,
    upsert_dialogue_state,
)
from app.services.interview import upsert_portrait_field

MODE_RESEARCH_STYLE = "research_style"

# —— 四题（依次）：研究范围 / 推进方式 / 理论 vs 工程 / 成果偏好 ——
# 每题选项 (显示文字, 选项标签)。答案用序号或选项文字匹配，大小写不敏感。
_QUESTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "第一题：你更习惯怎么铺开自己的研究范围？\n"
        "1. 广泛涉猎多个子方向，边看边找感觉\n"
        "2. 认准一个子方向，往里深挖\n"
        "3. 跟着具体问题走，范围可宽可窄\n"
        "（回复 1 / 2 / 3，或选项文字；回复「取消」退出）",
        (("1", "broad"), ("广泛涉猎", "broad"), ("多", "broad"),
         ("2", "deep"), ("深挖", "deep"), ("一个", "deep"),
         ("3", "mixed"), ("具体问题", "mixed")),
    ),
    (
        "第二题：你推进科研时更依赖哪种切入点？\n"
        "1. 从实际问题出发，先有场景再找方法\n"
        "2. 从方法创新出发，先有想法再做验证\n"
        "3. 从数据/现象出发，先观察规律再归纳\n"
        "（回复 1 / 2 / 3，或选项文字）",
        (("1", "problem"), ("问题", "problem"), ("场景", "problem"),
         ("2", "method"), ("方法", "method"), ("想法", "method"),
         ("3", "data"), ("数据", "data"), ("现象", "data")),
    ),
    (
        "第三题：你更偏好哪类工作形态？\n"
        "1. 理论推导 / 形式化证明\n"
        "2. 工程实现 / 系统落地\n"
        "3. 两者兼顾，看课题需要\n"
        "（回复 1 / 2 / 3，或选项文字）",
        (("1", "theory"), ("理论", "theory"), ("推导", "theory"),
         ("2", "engineering"), ("工程", "engineering"), ("系统", "engineering"),
         ("3", "balanced"), ("兼顾", "balanced"), ("都", "balanced")),
    ),
    (
        "第四题：你希望自己的成果主要长成什么样？\n"
        "1. 论文 / 方法 / 新理论\n"
        "2. 系统 / 产品 / 开源工具\n"
        "3. 分析报告 / 决策建议\n"
        "（回复 1 / 2 / 3，或选项文字）",
        (("1", "paper"), ("论文", "paper"), ("方法", "paper"),
         ("2", "system"), ("系统", "system"), ("产品", "system"), ("工具", "system"),
         ("3", "analysis"), ("分析", "analysis"), ("报告", "analysis")),
    ),
)

_STYLE_ANSWERS = ("1", "2", "3", "4")
_STYLE_CANCEL_TERMS = ("取消", "退出", "不测了", "算了", "停")

# v3.1.6：结果待回填态（pending）下的确认词与"下一步导航"词。
# 确认词包含匹配（"确认画像" 也命中 "确认"），优先于导航判定；
# 导航词直接放行走主流程（匹配/招募/方向地图等），不阻塞结果文本承诺的下一步。
_STYLE_CONFIRM_TERMS = ("确认", "生效", "确定", "可以")
_STYLE_NAV_TERMS = ("匹配", "招募", "方向地图", "雷达图", "匹配报告", "套磁")

# 回填 research_mode 的中文标签（与访谈 _VALUE_LABELS 同口径）
_MODE_FILL_LABELS = {
    "theory": "理论与原理",
    "engineering": "工程与落地",
    "mixed": "混合/兼顾",
}

# 核心风格：形态 × 驱动 → 名称 + 通俗解释（确定性规则表）
_CORE_STYLES: dict[tuple[str, str], tuple[str, str]] = {
    ("theory", "problem"): (
        "问题溯源型",
        "习惯从真实问题倒推理论缺口：先问“为什么会这样”，再追到原理层。"
        "适合需要拆解难题、做机理分析的课题。",
    ),
    ("theory", "method"): (
        "理论建构型",
        "习惯从方法创新出发做严谨推导，重视逻辑闭环与可证明性。"
        "适合理论性强、方法为主线的课题。",
    ),
    ("theory", "data"): (
        "现象洞察型",
        "习惯从数据/现象里找规律再上升为理论，观察力是你的优势。"
        "适合实证研究与模式发现类课题。",
    ),
    ("engineering", "problem"): (
        "落地攻坚型",
        "习惯从场景出发做工程实现，重视能不能真跑起来。"
        "适合系统开发、落地导向的课题。",
    ),
    ("engineering", "method"): (
        "方法工程型",
        "习惯把方法创新做进工程系统，既想新又要能用。"
        "适合算法研发与工具链建设类课题。",
    ),
    ("engineering", "data"): (
        "数据驱动型",
        "习惯从数据现象出发建模并工程化，重视实验与指标。"
        "适合数据密集、评测驱动型课题。",
    ),
    ("balanced", "problem"): (
        "问题牵引型",
        "形态不设限、以问题为准绳：哪个工具能解决问题就用哪个。"
        "适合交叉课题与开放性问题。",
    ),
    ("balanced", "method"): (
        "方法探索型",
        "既做理论也做工程，习惯围绕方法主线多形态验证。"
        "适合方法创新+系统验证并重的课题。",
    ),
    ("balanced", "data"): (
        "实证归纳型",
        "从数据出发、形态灵活，重视证据链条而非单一范式。"
        "适合实证研究与跨领域课题。",
    ),
}

# 范围修饰 → 一句话（拼在风格解释后）
_SCOPE_NOTES: dict[str, str] = {
    "broad": "研究范围偏好多线探索，匹配时注意课题广度与导师方向覆盖面。",
    "deep": "研究范围偏好单点深耕，匹配时注意课题纵深与长期投入空间。",
    "mixed": "研究范围跟着问题走，匹配时注意课题开放性即可。",
}

# 成果偏好 → 一句话建议
_OUTPUT_NOTES: dict[str, str] = {
    "paper": "成果形态偏好论文/方法，适合以论文产出为核心的课题组。",
    "system": "成果形态偏好系统/产品，适合有工程沉淀与开源传统的课题组。",
    "analysis": "成果形态偏好分析/决策建议，适合咨询式、评估式的合作场景。",
}

# 风格 → 画像 research_mode 回填映射（theory/engineering/mixed 为合法枚举值）
_MODE_MAP: dict[str, str] = {
    "theory": "theory",
    "engineering": "engineering",
    "balanced": "mixed",
}


def _match_answer(text: str, options: tuple[tuple[str, str], ...]) -> str | None:
    """返回选项标签；序号或选项文字（忽略空白与大小写）均匹配。"""
    norm = (text or "").strip().lower()
    for phrase, tag in options:
        if norm == phrase or phrase.lower() in norm and phrase not in _STYLE_ANSWERS:
            # 序号必须精确匹配，避免 "11" 误中 "1"；文字短语允许包含匹配
            if phrase in _STYLE_ANSWERS and norm != phrase:
                continue
            return tag
    return None


def _style_name(scope: str, core: str) -> str:
    scope_mod = {
        "broad": "多线·",
        "deep": "深耕·",
        "mixed": "",
    }.get(scope, "")
    return f"{scope_mod}{core}"


def classify_style(answers: Sequence[str]) -> dict[str, str]:
    """按四题答案标签做确定性分类。answers 顺序与 _QUESTIONS 一致。

    返回 {name, core, explanation, mode}；mode 用于回填画像 research_mode。
    """
    scope, driver, shape, output = list(answers) + ["mixed", "problem", "balanced", "paper"][len(answers):]
    core_name, core_text = _CORE_STYLES[(shape, driver)]
    name = _style_name(scope, core_name)
    explanation = (
        f"{core_text}\n"
        f"{_SCOPE_NOTES.get(scope, '')}\n"
        f"{_OUTPUT_NOTES.get(output, '')}"
    )
    return {
        "name": name,
        "core": core_name,
        "explanation": explanation,
        "mode": _MODE_MAP.get(shape, "mixed"),
    }


def question_text(step: int) -> str:
    """第 step 题（0 起）的题干文本。"""
    if not 0 <= step < len(_QUESTIONS):
        raise IndexError(f"research_style question step out of range: {step}")
    return _QUESTIONS[step][0]


def welcome_text() -> str:
    return (
        "好的，来做个 4 题的科研风格速测（比传统量表更轻，结果由确定性规则"
        "判定，不依赖模型发挥）。\n\n"
        "它只描述你当前更偏好的科研启动方式、研究范围和推进方式，"
        "**不判断你是否适合科研，也不评价能力高低**；完成后可作为匹配参考，"
        "不会写入导师评分。\n\n"
        f"{question_text(0)}"
    )


def accept_answer(text: str, step: int) -> str | None:
    """校验第 step 题答案；非法返回 None，合法返回选项标签。"""
    if not 0 <= step < len(_QUESTIONS):
        return None
    return _match_answer(text, _QUESTIONS[step][1])


def _style_result_text(answers: Sequence[str]) -> str:
    result = classify_style(answers)
    return (
        "【你的科研风格速测结果】\n"
        f"**{result['name']}**\n\n"
        f"{result['explanation']}\n\n"
        "说明：结果只反映你当前更偏好的科研方式，不判断是否适合科研、"
        "不评价能力高低；可作为匹配导师/岗位时的参考（偏好形态可回填画像，"
        "「确认」后生效）。\n"
        "接下来可以继续：\n"
        "1. 回复「确认」把偏好形态回填到画像；\n"
        "2. 回复「取消」放弃回填；\n"
        "3. 直接说「匹配」「招募」或「方向地图」继续。"
    )


def handle_research_style(
    db: Session,
    *,
    latest_user: str,
    session_id: str,
    student_id: str,
) -> str | None:
    """科研风格速测的多轮入口（状态存 dialogue_sessions）。

    v3.1.6：答完 4 题后保留 pending 态，「确认」把研究方式回填画像
    research_mode（upsert_portrait_field），随后清除模式；导航词（匹配/
    招募/方向地图等）清除模式并返回 None 放行走主流程；返回 None 时
    调用方（chat.py）不再把已消费的风格轮次重放给访谈。
    """
    text = (latest_user or "").strip()
    mode = get_dialogue_mode(db, session_id=session_id, student_id=student_id)
    if mode != MODE_RESEARCH_STYLE:
        # 触发消息即答案（如"测测我，我偏工程"）→ 从第一题开始正常走
        upsert_dialogue_state(
            db,
            session_id=session_id,
            student_id=student_id,
            mode=MODE_RESEARCH_STYLE,
            state={"step": 0, "answers": []},
        )
        return welcome_text()

    state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
    answers: list[str] = list((state or {}).get("answers") or [])
    step = int((state or {}).get("step", 0))
    pending = bool((state or {}).get("pending", False))

    if any(term in text for term in _STYLE_CANCEL_TERMS):
        clear_dialogue_state(db, session_id=session_id, student_id=student_id)
        if pending:
            return (
                "已放弃把偏好形态回填画像，可以继续聊导师匹配、招募机会"
                "或方向地图。"
            )
        return (
            "已退出科研风格速测，可以继续聊导师匹配、招募机会或方向地图。"
        )

    if step >= len(_QUESTIONS) and pending:
        # 结果待回填态：确认→回填画像；重测→重来；导航→放行；其它→提醒
        if any(term in text for term in _STYLE_CONFIRM_TERMS):
            mode_value = classify_style(answers)["mode"]
            upsert_portrait_field(
                db,
                session_id=session_id,
                student_id=student_id,
                changes={"research_mode": mode_value},
            )
            clear_dialogue_state(db, session_id=session_id, student_id=student_id)
            label = _MODE_FILL_LABELS.get(mode_value, mode_value)
            return (
                f"已把你的科研风格偏好回填到画像：研究方式 = {label}。\n\n"
                "画像有更新，需要重新确认后再匹配（回复「确认画像」）；"
                "也可以回复「招募」查询在招岗位，或回复「方向地图」查看方向。"
            )
        if any(term in text for term in _RESEARCH_STYLE_TERMS):
            upsert_dialogue_state(
                db,
                session_id=session_id,
                student_id=student_id,
                mode=MODE_RESEARCH_STYLE,
                state={"step": 0, "answers": []},
            )
            return welcome_text()
        if any(term in text for term in _STYLE_NAV_TERMS):
            clear_dialogue_state(db, session_id=session_id, student_id=student_id)
            return None
        return (
            "风格速测结果还没处理：回复「确认」把偏好形态回填画像，"
            "回复「取消」放弃；也可以直接说「匹配」「招募」或「方向地图」继续。"
        )

    tag = accept_answer(text, step)
    if tag is None:
        return (
            f"没看懂这一题的答案，再选一次：\n\n{question_text(step)}\n\n"
            "回复序号（1/2/3）或选项文字即可；回复「取消」退出。"
        )
    answers.append(tag)
    step += 1
    upsert_dialogue_state(
        db,
        session_id=session_id,
        student_id=student_id,
        mode=MODE_RESEARCH_STYLE,
        state={"step": step, "answers": answers},
    )
    if step >= len(_QUESTIONS):
        # 答完：保留 pending 态等待「确认」回填（v3.1.6 起不再直接清模式）
        upsert_dialogue_state(
            db,
            session_id=session_id,
            student_id=student_id,
            mode=MODE_RESEARCH_STYLE,
            state={"step": step, "answers": answers, "pending": True},
        )
        return _style_result_text(answers)
    return question_text(step)
