"""[PATCH] 清小搭兼容的对话接口（v1/chat/completions）。

修改点：
- 请求体从 MatchRequest 改为 OpenAIChatRequest（标准 OpenAI 格式）
- 解析 messages 提取用户最后一条消息作为 interest
- 响应体改为标准 OpenAI Chat Completions 格式
- 保留关键词匹配逻辑，输出格式兼容清小搭
"""

import json
import random
import re

from fastapi import APIRouter

from app.schemas.qxd import OpenAIChatRequest, OpenAIChatResponse, OpenAIChoice, OpenAIChoiceMessage
from app.services.data_loader import load_mentors
from app.services.matching import keyword_score

router = APIRouter()


@router.get("/v1/models")
def list_models():
    """返回模型列表（清小搭兼容）。"""
    return {
        "object": "list",
        "data": [
            {"id": "tsing-radar-v1", "object": "model"},
            {"id": "tsing-radar-v2", "object": "model"},
        ],
    }


@router.post("/v1/chat/completions", response_model=OpenAIChatResponse)
def chat(req: OpenAIChatRequest):
    """清小搭兼容接口：标准 OpenAI Chat Completions 协议。

    [PATCH] 请求体从 MatchRequest({interest, portrait, weight}) 改为
    OpenAIChatRequest({model, messages, stream, temperature})。
    从 messages 数组中提取最后一条 user 消息作为 interest 进行关键词匹配。
    """
    # [PATCH] 从标准 OpenAI messages 中提取用户意图
    user_messages = [m for m in req.messages if m.role == "user"]
    interest = user_messages[-1].content if user_messages else ""
    user_input = interest.lower().strip()
    keywords = re.split(r"[\s,，、]+", user_input)
    mentors = load_mentors()
    matched = [m for m in mentors if keyword_score(m, keywords) > 0]
    # 不足 5 条随机补充
    pool = [x for x in mentors if x not in matched]
    random.shuffle(pool)
    matched += pool[: max(0, 5 - len(matched))]
    matched = matched[:5]

    # [PATCH] 响应格式改为标准 OpenAI Chat Completions
    return OpenAIChatResponse(
        id=f"chatcmpl-{random.randint(100000000000, 999999999999)}",
        object="chat.completion",
        model=req.model or "tsing-radar-v2",
        choices=[
            OpenAIChoice(
                index=0,
                message=OpenAIChoiceMessage(
                    role="assistant",
                    content=json.dumps(matched, ensure_ascii=False),
                ),
                finish_reason="stop",
            )
        ],
    )
