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
# [PATCH] 移除 TrainTriggerRequest —— admin_token 改为 Header 传递，不再需要请求体模型
# from app.schemas.train import TrainTriggerRequest
from app.schemas.qxd import (
    OpenAIChatRequest,
    OpenAIChatResponse,
    OpenAIChoice,
    OpenAIChoiceMessage,
    Attachment,
)

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
    "OpenAIChatRequest",
    "OpenAIChatResponse",
    "OpenAIChoice",
    "OpenAIChoiceMessage",
    "Attachment",
]
