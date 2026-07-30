"""[PATCH] LLM 对话与向量化路由。

修改点：
- SSE 帧格式改为 OpenAI Chat Completions stream 规范
- delta 帧使用 choices[0].delta.content
- 终止帧使用 choices[0].finish_reason="stop" + data: [DONE]
- 自定义元数据通过 x_soda 扩展字段传递
"""

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
    """LLM 多轮对话问卷：GLM 优先、DeepSeek 兜底、无 key 走本地 stub；SSE 流式响应。

    [PATCH] SSE 帧格式改为 OpenAI 兼容：
    - data: {"choices":[{"delta":{"content":"..."}}]}
    - data: {"choices":[{"finish_reason":"stop"}], "x_soda":{"recommend_ready":true,"session_id":"..."}}
    - data: [DONE]
    """
    session_id = req.session_id or str(uuid.uuid4())
    history = QUESTIONNAIRE_SESSIONS.setdefault(session_id, [])
    for m in req.messages:
        history.append({"role": m.role, "content": m.content})

    async def sse_stream():
        # 获取完整回复（LLM 或 stub）
        reply = await llm_complete(req.messages)
        visible = (reply or stub_reply(req.messages)).strip()
        recommend_ready = "RECOMMEND_READY" in visible
        visible = visible.replace("RECOMMEND_READY", "").strip()

        # 记录回复到会话历史
        QUESTIONNAIRE_SESSIONS[session_id].append({"role": "assistant", "content": visible})

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        # [PATCH] 首帧：role 标识
        first_frame = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "model": "tsing-radar-v2",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(first_frame, ensure_ascii=False)}\n\n"

        # 分块流式输出（模拟 token 级 SSE）
        chunks = [visible[i : i + 8] for i in range(0, len(visible), 8)] or [""]
        for chunk in chunks:
            frame = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "model": "tsing-radar-v2",
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)

        # [PATCH] 终止帧：finish_reason=stop + x_soda 扩展字段
        finish_frame = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "model": "tsing-radar-v2",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "x_soda": {
                "recommend_ready": recommend_ready,
                "session_id": session_id,
            },
        }
        yield f"data: {json.dumps(finish_frame, ensure_ascii=False)}\n\n"

        # [PATCH] OpenAI 规范：最终 [DONE] 信号
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@router.post("/v1/llm/embeddings")
async def llm_embeddings(req: LLMEmbeddingRequest):
    """文本向量化；无 API key 返回基于文本 hash 的 128 维伪向量。"""
    vec = await embed_text(req.text)
    return {"data": vec}
