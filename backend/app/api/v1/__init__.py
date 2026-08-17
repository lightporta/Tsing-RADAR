"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import (
    advisor,
    applications,
    artifacts,
    documents,
    feedback,
    interview,
    llm,
    match,
    recruitment,
    resume,
    scatter,
    session,
    train,
    tsinghua,
)

api_router = APIRouter()
api_router.include_router(session.router, tags=["会话"])
api_router.include_router(documents.router, tags=["私有文档"])
api_router.include_router(artifacts.router, tags=["私有产物"])
api_router.include_router(applications.router, tags=["站内投递"])
api_router.include_router(advisor.router, tags=["导师"])
api_router.include_router(feedback.router, tags=["反馈"])
api_router.include_router(interview.router, tags=["动态访谈"])
api_router.include_router(llm.router, tags=["LLM"])
api_router.include_router(match.router, tags=["匹配"])
api_router.include_router(recruitment.router, tags=["招募"])
api_router.include_router(resume.router, tags=["简历"])
api_router.include_router(scatter.router, tags=["散点图"])
api_router.include_router(train.router, tags=["训练"])
api_router.include_router(tsinghua.router, tags=["校内接口"])
