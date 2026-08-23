"""内部动态访谈与向量化路由。"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_mutating_student
from app.db.session import get_db
from app.schemas.advisor import LLMChatRequest, LLMEmbeddingRequest
from app.services.interview import (
    InterviewAccessError,
    InterviewConflictError,
    InterviewNotFoundError,
    state_response,
    sync_user_transcript,
)
from app.services.llm import embed_text, enhance_interview_reply

router = APIRouter()


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
