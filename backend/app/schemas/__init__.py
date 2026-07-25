"""Pydantic schemas 聚合。"""

from app.schemas.advisor import (
    AdvisorOut,
    LLMChatRequest,
    LLMEmbeddingRequest,
    LLMMessage,
    MatchRequest,
    MatchedAdvisorOut,
    ScatterPoint,
)
from app.schemas.recruitment import RecruitmentCreateRequest, RecruitmentItem
from app.schemas.resume import ResumeGenerateRequest, ResumeSubmitRequest
from app.schemas.feedback import FeedbackRequest
from app.schemas.train import TrainTriggerRequest

__all__ = [
    "AdvisorOut",
    "LLMChatRequest",
    "LLMEmbeddingRequest",
    "LLMMessage",
    "MatchRequest",
    "MatchedAdvisorOut",
    "ScatterPoint",
    "RecruitmentCreateRequest",
    "RecruitmentItem",
    "ResumeGenerateRequest",
    "ResumeSubmitRequest",
    "FeedbackRequest",
    "TrainTriggerRequest",
]
