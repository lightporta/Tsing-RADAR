"""内部动态访谈与向量化路由。"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_mutating_student
from app.db.session import get_db
from app.schemas.advisor import LLMChatRequest, LLMEmbeddingRequest
from app.services.agent_orchestrator import run_agent_turn
from app.services.agent_wiring import (
    agent_interview_anchors,
    agent_interview_state_context,
)
from app.services.chat_expression import (
    MAX_PREVIOUS_REPLY_CHARS,
    build_interview_fact_pack,
)
from app.services.dialogue_state_store import (
    get_session_value,
    set_session_value,
)
from app.services.interview import (
    InterviewAccessError,
    InterviewConflictError,
    InterviewNotFoundError,
    state_response,
    sync_user_transcript,
)
from app.services.llm import embed_text, enhance_interview_reply
from app.services.memory_service import format_memory_summary

router = APIRouter()
logger = logging.getLogger("tsing_radar.llm")


@router.post("/v1/llm/chat")
async def llm_chat(
    req: LLMChatRequest,
    stream: bool = True,
    db: Session = Depends(get_db),
    student_id: str = Depends(get_mutating_student),
):
    """持久化动态访谈；状态机决定下一题，LLM 不决定完成条件。"""
    session_id = req.session_id or str(uuid.uuid4())
    user_messages = [
        message.content for message in req.messages if message.role == "user"
    ]
    if not user_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="messages 至少需要一条 user 消息",
        )
    try:
        session = sync_user_transcript(
            db,
            session_id=session_id,
            student_id=student_id,
            user_messages=user_messages,
        )
    except InterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InterviewAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InterviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    interview_state = state_response(session)
    # —— v4.3.x 网页端访谈接入 Agent 编排（与清小搭入口同款闸门+降级）——
    # 激活条件：LLM 凭据 + 编排总开关 + 未到推荐就绪态。recommend_ready
    # （匹配结果）是确定性保留区，永不走 Agent（红线）；无凭据/开关关闭
    # 时保留既有 enhance_interview_reply 路径，行为逐字节不变。
    agent_active = (
        bool(settings.llm_credentials)
        and settings.AGENT_ORCHESTRATION_ENABLED
        and not interview_state.recommend_ready
    )
    if agent_active:
        # 状态机已在上方推进并持久化，此处只接管回复渲染：把事实包渲染成
        # 状态注入文本 + 逐字锚点，交 run_agent_turn 编排（GLM 对话 + 确定性
        # 工具调用 + 服务端校验闸门）。网页端无招募注入特性，
        # recruitment_summary 不注入。成功用 Agent 回复；任何失败/拒绝降级
        # 状态机确定性文本（不再调 enhance_interview_reply，避免双 LLM 延迟）。
        fact_pack = build_interview_fact_pack(
            interview_state,
            user_messages[-1] if user_messages else "",
            memory_summary=format_memory_summary(db, student_id),
            previous_reply=get_session_value(
                db,
                session_id=session_id,
                student_id=student_id,
                key="interview_last_expression",
            )
            or "",
        )
        agent_result = await run_agent_turn(
            db,
            session_id=session_id,
            student_id=student_id,
            messages=[
                m for m in req.messages if m.role in ("user", "assistant")
            ],
            state_context=agent_interview_state_context(
                interview_state, fact_pack
            ),
            required_anchors=agent_interview_anchors(
                interview_state, fact_pack
            ),
        )
        logger.info(
            "web_agent_turn status=%s tools=%s",
            agent_result.status,
            ",".join(agent_result.tool_names) or "none",
        )
        visible = interview_state.assistant_message
        if agent_result.status == "success" and agent_result.text:
            visible = agent_result.text
        # 记住本轮实际展示话术（与清小搭入口同款 best-effort 持久化），
        # 下一轮 Agent 据此防重复承接。
        set_session_value(
            db,
            session_id=session_id,
            student_id=student_id,
            key="interview_last_expression",
            value=visible[:MAX_PREVIOUS_REPLY_CHARS],
        )
        enhancement_meta = {
            "assistant_mode": "agent_orchestration",
            "agent_status": agent_result.status,
            "agent_tools": ",".join(agent_result.tool_names) or "none",
        }
    else:
        enhancement = await enhance_interview_reply(
            user_message=user_messages[-1],
            fixed_reply=interview_state.assistant_message,
        )
        visible = interview_state.assistant_message
        if enhancement.text:
            visible = f"{enhancement.text}\n\n{visible}"
        enhancement_meta = {
            "assistant_mode": "fixed_interview_with_optional_llm_enhancement",
            "enhancement_provider": enhancement.provider,
            "enhancement_status": enhancement.status,
        }
    finish_meta = interview_state.model_dump(
        mode="json",
        exclude={"assistant_message", "messages"},
    )
    finish_meta.update(enhancement_meta)
    if not stream:
        payload = interview_state.model_dump(mode="json")
        payload["assistant_message"] = visible
        payload.update(enhancement_meta)
        return payload

    async def sse_stream():
        chunks = [visible[i : i + 8] for i in range(0, len(visible), 8)] or [""]
        for chunk in chunks:
            payload = {"delta": chunk, "role": "assistant"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)
        yield (
            "data: "
            + json.dumps(
                {"delta": "", "finish": True, **finish_meta},
                ensure_ascii=False,
            )
            + "\n\n"
        )

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@router.post("/v1/llm/embeddings")
async def llm_embeddings(req: LLMEmbeddingRequest):
    """文本向量化；无 API key 返回基于文本 hash 的 128 维伪向量。"""
    vec = await embed_text(req.text)
    return {"data": vec}
