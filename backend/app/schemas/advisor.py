"""导师 / 匹配 / 对话相关 Pydantic 模型。"""

from typing import Optional

from pydantic import BaseModel

from app.schemas.matching import MatchRequest


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMChatRequest(BaseModel):
    messages: list[LLMMessage]
    session_id: Optional[str] = None


class LLMEmbeddingRequest(BaseModel):
    text: str


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
