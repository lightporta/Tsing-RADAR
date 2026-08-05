"""[PATCH] Tsing-RADAR FastAPI 主入口。

修改点：
- 注册统一异常处理器（BizError / ValidationError / 通用异常）
- 开启 debug 模式标记
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from app.api.v1 import api_router
from app.core.config import settings
# [PATCH] 导入统一响应处理器
from app.core.response import biz_error_handler, validation_handler, generic_handler, BizError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="清研寻师雷达 —— 清华导师智能匹配智能体（部署于清小搭智能体广场）",
    debug=settings.DEBUG,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [PATCH] 注册全局异常处理器
app.add_exception_handler(BizError, biz_error_handler)
app.add_exception_handler(RequestValidationError, validation_handler)
app.add_exception_handler(Exception, generic_handler)

# 注册路由
app.include_router(api_router, prefix="/api")

logger.info("Tsing-RADAR 后端已启动 | debug=%s | 版本=%s", settings.DEBUG, settings.APP_VERSION)


@app.get("/")
def root():
    """根路径信息。"""
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
            "/api/v1/chat/completions",
            "/api/v1/models",
            "/api/recruitments",
            "/api/resume/generate",
            "/api/resume/submit",
            "/api/storage/upload",
            "/api/storage/download",
            "/api/feedback",
            "/api/train/trigger",
            "/api/tsinghua/auth/verify",
            "/api/tsinghua/lib/papers",
        ],
    }


@app.get("/health")
def health():
    """健康检查。"""
    return {"status": "ok", "version": settings.APP_VERSION}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
