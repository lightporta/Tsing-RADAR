"""LangGraph 对话编排（文档 §4.1 对话编排层）。

脚手架：问卷节点 → 匹配节点 → 推荐节点的状态机。
依赖 langgraph 时启用真实编排；否则降级为简单函数链。
"""

from typing import Any, Optional

from app.services.llm import LLM_SYSTEM_PROMPT  # noqa: F401


class GraphState(dict):
    """对话编排状态。"""

    messages: list[dict[str, str]]
    portrait: Optional[dict[str, Any]]
    recommend_ready: bool
    matched_advisors: list[dict[str, Any]]


def questionnaire_node(state: GraphState) -> GraphState:
    """问卷节点：判断是否收集足够信息。

    真实实现应调用 LLM 判断；此处简化为基于轮数的规则。
    """
    user_turns = sum(1 for m in state.get("messages", []) if m.get("role") == "user")
    last = state.get("messages", [{}])[-1].get("content", "").lower() if state.get("messages") else ""
    signals = ["推荐", "够了", "完了", "可以了", "结束", "match", "recommend", "开始匹配"]
    state["recommend_ready"] = user_turns >= 3 or any(s in last for s in signals)
    return state


def match_node(state: GraphState) -> GraphState:
    """匹配节点：调用匹配服务产出推荐列表。"""
    if not state.get("recommend_ready"):
        return state
    # 真实实现：from app.services.matching import match_mentors
    state["matched_advisors"] = []
    return state


def recommend_node(state: GraphState) -> GraphState:
    """推荐节点：生成推荐理由与展示数据。"""
    if not state.get("matched_advisors"):
        return state
    # 真实实现：调用 build_reason 生成个性化理由
    return state


def build_graph():
    """构建对话编排图。

    依赖 langgraph 时使用 StateGraph；否则降级为函数链。
    """
    try:
        from langgraph.graph import END, StateGraph

        workflow = StateGraph(GraphState)
        workflow.add_node("questionnaire", questionnaire_node)
        workflow.add_node("match", match_node)
        workflow.add_node("recommend", recommend_node)

        workflow.set_entry_point("questionnaire")
        workflow.add_conditional_edges(
            "questionnaire",
            lambda s: "match" if s.get("recommend_ready") else END,
        )
        workflow.add_edge("match", "recommend")
        workflow.add_edge("recommend", END)
        return workflow.compile()
    except ImportError:
        # langgraph 未安装，降级为简单函数链
        def simple_chain(state: GraphState) -> GraphState:
            state = questionnaire_node(state)
            state = match_node(state)
            state = recommend_node(state)
            return state

        return simple_chain


# 全局编译图实例
graph = build_graph()
