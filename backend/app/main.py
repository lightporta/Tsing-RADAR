"""Tsing-RADAR FastAPI 主入口。

模块化 v2.1：
- 13+ 个 API 路由（导师/对话/匹配/散点/招募/简历/反馈/训练/校内）
- CORS + 路由注册 + 健康检查 + 启动事件
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="清研寻师雷达 —— 清华导师智能匹配智能体（部署于清小搭智能体广场）",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, prefix="/api")


@app.on_event("startup")
async def startup_event() -> None:
    """启动事件：初始化数据库表、加载导师库。"""
    logger.info("Tsing-RADAR 启动中...")
    try:
        from app.db.session import init_db

        init_db()
        logger.info("数据库表已初始化")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"数据库初始化失败（降级为内存模式）: {e}")

    from app.services.data_loader import load_mentors

    mentors = load_mentors()
    logger.info(f"已加载 {len(mentors)} 位导师")

    # LLM 配置检查
    if settings.GLM_API_KEY:
        logger.info("✅ 已配置 GLM_API_KEY，LLM 走真模型")
    elif settings.DEEPSEEK_API_KEY:
        logger.info("✅ 已配置 DEEPSEEK_API_KEY，LLM 走真模型")
    else:
        logger.warning("⚠️ 未配置 GLM_API_KEY / DEEPSEEK_API_KEY，LLM 将降级到本地 stub")


@app.get("/")
def root():
    """根路径：应用信息。"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "endpoints": [
            "/api/mentors",
            "/api/mentors/sort",
            "/api/scatter",
            "/api/match",
            "/api/v1/llm/chat",
            "/api/v1/llm/embeddings",
            "/api/recruitments",
            "/api/resume/generate",
            "/api/resume/submit",
            "/api/feedback",
            "/api/train/trigger",
            "/api/tsinghua/auth/verify",
        ],
    }


@app.get("/health")
def health():
    """健康检查。"""
    return {"status": "ok", "version": settings.APP_VERSION}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
