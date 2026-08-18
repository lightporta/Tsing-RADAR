"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import (
    admin_reviews,
    advisor,
    advisor_ratings,
    applications,
    artifacts,
    documents,
    feedback,
    interview,
    llm,
    match,
    mentor_auth,
    mentor_claim,
    mentor_inbox,
    mentor_privacy,
    mentor_profile,
    mentor_recruitment,
    recruitment,
    recruitment_comments,
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
api_router.include_router(recruitment_comments.router, tags=["招募评论"])
api_router.include_router(resume.router, tags=["简历"])
api_router.include_router(scatter.router, tags=["散点图"])
api_router.include_router(train.router, tags=["训练"])
api_router.include_router(tsinghua.router, tags=["校内接口"])
api_router.include_router(mentor_auth.router, tags=["导师服务-登录"])
api_router.include_router(mentor_claim.router, tags=["导师服务-认领"])
api_router.include_router(mentor_profile.router, tags=["导师服务-档案"])
api_router.include_router(mentor_inbox.router, tags=["导师服务-意向中心"])
api_router.include_router(mentor_recruitment.router, tags=["导师服务-招募"])
api_router.include_router(mentor_privacy.router, tags=["导师服务-隐私"])
api_router.include_router(admin_reviews.router, tags=["管理员-导师审批"])
api_router.include_router(advisor_ratings.router, tags=["学生评价"])
