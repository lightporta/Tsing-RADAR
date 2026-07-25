"""LLM 对话与向量化路由。"""

import asyncio
import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.advisor import LLMChatRequest, LLMEmbeddingRequest
from app.services.llm import embed_text, llm_complete, stub_reply
from app.services.memory_store import QUESTIONNAIRE_SESSIONS

router = APIRouter()


@router.post("/v1/llm/chat")
async def llm_chat(req: LLMChatRequest):
    """LLM 多轮对话问卷：GLM 优先、DeepSeek 兜底、无 key 走本地 stub；SSE 流式响应。"""
    session_id = req.session_id or str(uuid.uuid4())
    history = QUESTIONNAIRE_SESSIONS.setdefault(session_id, [])
    for m in req.messages:
        history.append({"role": m.role, "content": m.content})

    async def sse_stream():
        # 获取完整回复（LLM 或 stub）
        reply = await llm_complete(req.messages)
        if reply is None:
            reply = stub_reply(req.messages)

        # 检测完成标记，从可见文本中剥离
        recommend_ready = "RECOMMEND_READY" in reply
        visible = reply.replace("RECOMMEND_READY", "").strip()

        # 记录助手回复到会话历史
        QUESTIONNAIRE_SESSIONS[session_id].append({"role": "assistant", "content": visible})

        # 分块流式输出（模拟 token 级 SSE）
        chunks = [visible[i : i + 8] for i in range(0, len(visible), 8)] or [""]
        for chunk in chunks:
            payload = {"delta": chunk, "role": "assistant"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)
        # 终止帧
        yield f"data: {json.dumps({'delta': '', 'finish': True, 'recommend_ready': recommend_ready, 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@router.post("/v1/llm/embeddings")
async def llm_embeddings(req: LLMEmbeddingRequest):
    """文本向量化；无 API key 返回基于文本 hash 的 128 维伪向量。"""
    vec = await embed_text(req.text)
    return {"data": vec}
