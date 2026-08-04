"""LangGraph 对话编排兼容壳。

访谈状态由 A3 持久化服务维护；本模块不得按轮数或关键词绕过确认门。
A4 匹配由 ``services.match_application`` 统一编排；本兼容壳不复制排序逻辑。
"""

from typing import Any, Optional

from app.services.llm import LLM_SYSTEM_PROMPT  # noqa: F401


class GraphState(dict):
    """对话编排状态。"""

    messages: list[dict[str, str]]
    portrait: Optional[dict[str, Any]]
    interview_status: str
    recommend_ready: bool
    matched_advisors: list[dict[str, Any]]


def questionnaire_node(state: GraphState) -> GraphState:
    """只有持久化画像已确认时才允许进入后续节点。"""
    state["recommend_ready"] = state.get("interview_status") == "confirmed"
    return state


def match_node(state: GraphState) -> GraphState:
    """兼容节点：真实匹配必须由带数据库会话的应用服务执行。"""
    if not state.get("recommend_ready"):
        return state
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
