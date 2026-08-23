"""清小搭与网页端共用的 Agent 编排接线辅助（状态注入与锚点提取）。

红线（两个入口必须一致遵守）：
- 状态注入是确定性投影：只把服务端已有事实（题干/选项/画像进度/
  上一轮话术/记忆摘要）渲染成文本，不给模型留新事实空间；
- 锚点与逐字校验配套：状态注入里标注"必须逐字保留"的内容，与
  agent_interview_anchors 提取的锚点一一对应，由 run_agent_turn 的
  逐字校验闸门强制兜底；
- 确认门 / 匹配结果保留区：确认卡画像内容与匹配证据是确定性输出，
  Agent 只被允许在其前后加自然承接语，不得改写事实本身。

本模块由 app/api/v1/chat.py（清小搭入口）与 app/api/v1/llm.py（网页端
入口）共用，两处的激活闸门与降级语义保持同款。
"""

from __future__ import annotations

from app.services.chat_expression import InterviewFactPack
from app.services.interview import _VALUE_LABELS


def agent_interview_state_context(
    state,
    fact_pack: InterviewFactPack,
) -> str:
    """把访谈事实包渲染成 Agent 状态注入文本（确定性投影，无新事实）。

    要求逐字保留的内容（选项原文/确认卡画像内容）显式标注，与
    required_anchors 逐字校验闸门配套；选项/确认卡前后的承接语允许
    模型自由发挥（自然度许可），但事实本身一个字都不能动。
    """
    progress = (
        f"画像进度：已完成维度 {'、'.join(fact_pack.completed_dimensions) or '无'}；"
        f"待完成维度 {'、'.join(fact_pack.missing_dimensions) or '无'}；"
        f"{fact_pack.hard_constraint_status}"
    )
    lines: list[str] = []
    if state.needs_confirmation:
        # 确认门：无当前题，服务端确认卡（assistant_message）即本轮话术，
        # 其中的画像内容为逐字校验锚点（见 agent_interview_anchors）。
        lines.extend(
            (
                "当前阶段：访谈题目已全部完成，进入画像确认门"
                "（用户需回复确认指令或提出修改）。",
                "服务端确认卡原文"
                "（其中的画像内容必须逐字保留，不得改写、增删事实；"
                "前后可加一两句自然口语化承接）：",
                state.assistant_message,
                progress,
            )
        )
    else:
        lines.append(
            f"当前题目：第 {len(fact_pack.completed_dimensions) + 1} 题"
            f"（访谈阶段：{fact_pack.turn_phase}）"
        )
        if fact_pack.question_prompt:
            lines.append(
                f"题干（必须逐字保留）：{fact_pack.question_prompt}"
            )
        if fact_pack.options:
            lines.append(
                "选项原文（必须逐条完整逐字保留，不得改写、增删、意译；"
                "选项前后的承接语可自由发挥）：\n"
                + "\n".join(
                    f"{index}. {label}"
                    for index, label in enumerate(fact_pack.options, 1)
                )
            )
        lines.append(progress)
    if fact_pack.previous_reply:
        lines.append(
            "上一轮话术（仅供衔接参考：不要重复其中已问过的问题，"
            f"禁止逐字复读）：{fact_pack.previous_reply}"
        )
    if fact_pack.memory_summary:
        lines.append(
            f"记忆摘要（必须逐字保留其中的用户事实）：{fact_pack.memory_summary}"
        )
    if fact_pack.recruitment_summary:
        lines.append(
            f"招募摘要（必须逐字保留其中的招募事实）：{fact_pack.recruitment_summary}"
        )
    return "\n".join(lines)


def agent_interview_anchors(
    state,
    fact_pack: InterviewFactPack,
) -> list[str]:
    """Agent 最终回复必须逐字包含的锚点（确定性提取，不重写正则）。

    选项题 → 全部选项原文（复用 build_interview_fact_pack 的选项提取，
    即题库 label 原文）；画像确认门 → 画像关键字段值（研究兴趣标签 +
    已答维度值，与状态机确认卡话术同一 _VALUE_LABELS 映射，保证锚点
    字符串与用户实际看到的画像内容一致）；其余轮次 → 空。
    """
    if fact_pack.options:
        return list(fact_pack.options)
    if state.needs_confirmation:
        anchors = list(state.profile.research_interests)
        for field_name in (
            "research_mode",
            "mentorship_style",
            "career_orientation",
            "innovation_risk",
        ):
            value = getattr(state.profile, field_name, None)
            if value:
                anchors.append(_VALUE_LABELS.get(value, value))
        return anchors
    return []


def agent_portrait_summary(portrait) -> str:
    """把已确认画像渲染成 Agent 状态注入用的摘要文本（确定性投影）。"""
    if portrait is None:
        return "（画像暂不可用：本会话没有可读取的已确认画像）"
    lines: list[str] = []
    if portrait.research_interests:
        lines.append(f"- 研究兴趣：{'、'.join(portrait.research_interests)}")
    for field_name, label in (
        ("research_mode", "研究方式"),
        ("mentorship_style", "指导偏好"),
        ("career_orientation", "生涯方向"),
        ("innovation_risk", "创新风险"),
    ):
        value = getattr(portrait, field_name, None)
        if value:
            lines.append(f"- {label}：{_VALUE_LABELS.get(value, value)}")
    if portrait.hard_constraints:
        lines.append(f"- 已确认硬性条件：{len(portrait.hard_constraints)} 条")
    return "\n".join(lines) if lines else "（画像暂无已确认内容）"


def agent_post_match_state_context(portrait, previous_reply: str) -> str:
    """匹配结果展示后的 Agent 状态注入文本（确定性投影，无新事实）。"""
    lines = [
        "当前阶段：画像已确认，匹配结果已展示给用户。",
        "可用工具：查询导师详情、查询导师招募信息、查询导师知识库、重新计算匹配。",
        "画像摘要：",
        agent_portrait_summary(portrait),
    ]
    if previous_reply:
        lines.append(
            "上一轮话术（仅供衔接参考：不要重复其中已问过的问题，"
            f"禁止逐字复读）：{previous_reply}"
        )
    return "\n".join(lines)
