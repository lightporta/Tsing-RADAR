"""导师 / 匹配 / 对话相关 Pydantic 模型。"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.matching import MatchRequest


class LLMMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(max_length=20_000)


class LLMChatRequest(BaseModel):
    messages: list[LLMMessage] = Field(max_length=50)
    session_id: Optional[str] = None


class LLMEmbeddingRequest(BaseModel):
    text: str = Field(max_length=20_000)


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
