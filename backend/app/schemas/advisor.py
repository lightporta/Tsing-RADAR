"""导师 / 匹配 / 对话相关 Pydantic 模型。"""

from typing import Any, Optional

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMChatRequest(BaseModel):
    # [PATCH] 增加 model 字段，兼容清小搭传入的 OpenAI 格式
    model: Optional[str] = None
    messages: list[LLMMessage]
    session_id: Optional[str] = None
    stream: Optional[bool] = True


class LLMEmbeddingRequest(BaseModel):
    text: str


class MatchRequest(BaseModel):
    interest: str
    portrait: Optional[dict[str, Any]] = None
    weight: Optional[dict[str, float]] = None


class MatchedAdvisorOut(BaseModel):
    name: str
    dept: str
    field: str
    tags: list[str] = []
    score: float
    reason: str
    radar_traits: dict[str, float]
    popularity: float
    sector: str
    synergy: float = 0
    projects: list[dict] = []
    recruitments: list[dict] = []
    contact_email: Optional[str] = None
    office_loc: Optional[str] = None


class AdvisorOut(BaseModel):
    name: str
    dept: str
    field: str
    tags: list[str] = []
    score: float
    reason: str
    radar_traits: dict[str, float]
    popularity: float
    sector: str
    projects: list[dict] = []
    recruitments: list[dict] = []
    contact_email: Optional[str] = None
    office_loc: Optional[str] = None


class ScatterPoint(BaseModel):
    name: str
    x: float
    y: float
    color: str
    dept: str
