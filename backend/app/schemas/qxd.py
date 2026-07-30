"""[PATCH] 清小搭 / OpenAI 兼容协议 Schema 定义。

新增文件：定义符合 OpenAI Chat Completions API 规范的请求/响应模型，
用于 /api/v1/chat/completions 接口，替代原先不符合协议的 MatchRequest。
"""

from typing import Optional

from pydantic import BaseModel, Field


class OpenAIMessage(BaseModel):
    """OpenAI 消息格式。"""
    role: str = Field(..., description="system / user / assistant")
    content: str = Field(..., description="消息文本")


class OpenAIChatRequest(BaseModel):
    """OpenAI Chat Completions 请求体。

    清小搭平台会发送标准 OpenAI 格式：
    {
      "model": "tsing-radar-v2",
      "messages": [{"role":"user","content":"..."}],
      "stream": false,
      "temperature": 0.7
    }
    """
    model: str = Field(default="tsing-radar-v2", description="模型标识")
    messages: list[OpenAIMessage] = Field(..., description="对话消息列表")
    stream: bool = Field(default=False, description="是否流式返回")
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)


class OpenAIChoiceMessage(BaseModel):
    """OpenAI choice.message 格式。"""
    role: str = "assistant"
    content: str = ""


class OpenAIChoice(BaseModel):
    """OpenAI choice 格式。"""
    index: int = 0
    message: OpenAIChoiceMessage
    finish_reason: str = "stop"


class OpenAIChatResponse(BaseModel):
    """OpenAI Chat Completions 响应体。"""
    id: str = ""
    object: str = "chat.completion"
    model: str = "tsing-radar-v2"
    choices: list[OpenAIChoice] = []


class OpenAIDelta(BaseModel):
    """SSE 流式 delta 片段。"""
    content: str = ""


class OpenAIStreamChoice(BaseModel):
    """SSE 流式 choice。"""
    index: int = 0
    delta: OpenAIDelta
    finish_reason: Optional[str] = None


class OpenAIStreamChunk(BaseModel):
    """SSE 流式单帧。"""
    id: str = ""
    object: str = "chat.completion.chunk"
    model: str = "tsing-radar-v2"
    choices: list[OpenAIStreamChoice] = []


class Attachment(BaseModel):
    """清小搭多模态附件 (x_soda.attachments)。

    参考《清小搭多模态附件对端接口文档》v1.0。
    """
    fileUrl: str
    fileName: str
    fileType: str = Field(..., description="pdf / pptx / docx / xlsx / image / audio / txt / markdown")
    mimeType: str
    fileSize: Optional[int] = None
    previewUrl: Optional[str] = None
    expiresAt: Optional[str] = None
