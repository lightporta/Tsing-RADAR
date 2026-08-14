"""Tsing-RADAR FastAPI 主入口。

模块化 v2.1：
- 13+ 个 API 路由（导师/对话/匹配/散点/招募/简历/反馈/训练/校内）
- CORS + 路由注册 + 健康检查 + 启动事件
"""

import logging

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.api.v1.chat import router as qxd_router
from app.core.config import settings
from app.core.logging_filters import install_artifact_token_log_redaction
from app.core.security_validation import validate_production_secrets
from app.services.observability import observe_http_request
from app.services.readiness import local_readiness

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
install_artifact_token_log_redaction()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="清研寻师雷达 —— 清华导师智能匹配智能体（部署于清小搭智能体广场）",
)


async def reject_declared_oversized_private_upload(
    request: Request,
    call_next,
):
    """Reject clearly oversized multipart bodies before Starlette parses them."""
    if request.method == "POST" and request.url.path == "/api/documents":
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit():
            # Multipart framing varies by client; reserve a bounded allowance
            # while keeping the file payload limit authoritative in the service.
            maximum_request_bytes = settings.PRIVATE_UPLOAD_MAX_BYTES + 64 * 1024
            if int(content_length) > maximum_request_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "文件超过大小限制"},
                )
    return await call_next(request)


app.middleware("http")(reject_declared_oversized_private_upload)
app.middleware("http")(observe_http_request)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Artifact-SHA256",
        "X-Request-ID",
    ],
)

# 注册路由
# 清小搭 OpenAI-compatible 协议入口与内部业务 API 分离。
app.include_router(qxd_router, tags=["清小搭 OpenAI-compatible"])
app.include_router(api_router, prefix="/api")


@app.on_event("startup")
async def startup_event() -> None:
    """启动事件：开发期可建表；Compose/生产只验证迁移后的数据库。"""
    logger.info("Tsing-RADAR 启动中...")
    try:
        if settings.AUTO_CREATE_SCHEMA:
            from app.db.session import init_db

            init_db()
            logger.info("开发模式数据库表已初始化")
        else:
            from sqlalchemy import text

            from app.db.session import engine

            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("数据库连接可用；表结构由 Alembic migration 服务管理")
    except Exception as e:  # noqa: BLE001
        logger.critical("数据库启动检查失败，服务停止启动: %s", type(e).__name__)
        raise

    if not settings.DEBUG:
        if settings.AUTO_CREATE_SCHEMA:
            raise RuntimeError("生产模式必须关闭 AUTO_CREATE_SCHEMA 并使用 Alembic")
        if (
            settings.PRODUCTION_DEPLOYMENT
            and not settings.production_secret_files_configured
        ):
            raise RuntimeError("生产部署必须通过独立的 *_FILE 配置秘密")
        if (
            settings.PRODUCTION_DEPLOYMENT
            and not settings.production_secret_file_permissions_valid
        ):
            raise RuntimeError("生产秘密文件必须为绝对路径且禁止组/其他用户读取")
        validate_production_secrets(settings)
        if not settings.WEB_COOKIE_SECURE:
            raise RuntimeError("生产模式必须启用 WEB_COOKIE_SECURE")
        if settings.FILE_SCAN_MODE != "clamav" or not settings.CLAMAV_HOST:
            raise RuntimeError("生产模式必须配置可用的 ClamAV 扫描服务")
        if settings.OBJECT_STORE_BACKEND != "s3":
            raise RuntimeError("生产模式必须使用私有 S3 兼容对象存储")
        if settings.S3_SERVER_SIDE_ENCRYPTION != "AES256":
            raise RuntimeError("生产模式必须启用 S3 服务端加密")
        if not all(
            (
                settings.S3_BUCKET,
                settings.S3_ACCESS_KEY_ID,
                settings.S3_SECRET_ACCESS_KEY,
            )
        ):
            raise RuntimeError("生产模式必须完整配置私有 S3 桶与访问凭证")
        if settings.PRODUCTION_DEPLOYMENT:
            from app.services.object_storage import (
                validate_tencent_cos_configuration,
            )

            if settings.S3_PROVIDER != "tencent_cos":
                raise RuntimeError("生产部署必须显式使用腾讯云 COS provider")
            validate_tencent_cos_configuration(
                endpoint_url=settings.S3_ENDPOINT_URL,
                bucket=settings.S3_BUCKET,
                region=settings.S3_REGION,
                addressing_style=settings.S3_ADDRESSING_STYLE,
                server_side_encryption=settings.S3_SERVER_SIDE_ENCRYPTION,
            )
        from app.services.qxd_media import validate_remote_media_configuration

        validate_remote_media_configuration(settings)
        if settings.QXD_ATTACHMENTS_ENABLED:
            if not settings.QXD_API_KEY:
                raise RuntimeError("启用清小搭附件前必须先启用清小搭协议凭证")
            if settings.ALLOW_TEST_PUBLIC_BASE_URL:
                raise RuntimeError("生产模式不得允许专用测试附件域名")
            from app.services.artifact_delivery import assert_qxd_delivery_ready

            try:
                assert_qxd_delivery_ready()
            except Exception as exc:
                raise RuntimeError(
                    "清小搭附件交付必须配置合法的公网 HTTPS 根地址"
                ) from exc
        elif settings.PUBLIC_BASE_URL:
            if settings.PRODUCTION_DEPLOYMENT:
                raise RuntimeError("未启用附件交付时 PUBLIC_BASE_URL 必须为空")
            # Preserve the pre-L1 fail-closed contract for legacy deployments:
            # an unused delivery URL may remain configured, but it must never
            # bypass the same public-root validation as an enabled endpoint.
            from app.services.artifact_delivery import assert_qxd_delivery_ready

            try:
                assert_qxd_delivery_ready()
            except Exception as exc:
                raise RuntimeError(
                    "清小搭附件交付必须配置合法的公网 HTTPS 根地址"
                ) from exc

    from app.services.data_loader import mentor_data_summary

    summary = mentor_data_summary()
    logger.info(
        "导师治理数据已加载：总数=%s，可发布=%s，暂缓=%s",
        summary["total_records"],
        summary["published_records"],
        summary["withheld_records"],
    )

    # 仅记录 provider 与是否配置；绝不记录密钥值、长度、摘要或前后缀。
    if settings.configured_llm_providers:
        logger.info(
            "LLM provider=%s，密钥已配置",
            ",".join(settings.configured_llm_providers),
        )
    else:
        logger.warning("LLM provider=none，密钥未配置；使用本地规则模式")


@app.get("/")
def root():
    """根路径：应用信息。"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "endpoints": [
            "/v1/models",
            "/v1/chat/completions",
            "/api/mentors",
            "/api/mentors/sort",
            "/api/scatter",
            "/api/match",
            "/api/session",
            "/api/documents",
            "/api/artifacts/match-report",
            "/api/applications",
            "/api/interviews",
            "/api/v1/llm/chat",
            "/api/v1/llm/embeddings",
            "/api/recruitments",
            "/api/resume/generate",
            "/api/resume/submit",
            "/api/feedback",
            "/api/train/trigger",
            "/health/live",
            "/health/ready",
        ],
    }


@app.get("/health")
def health():
    """健康检查。"""
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/health/live")
def health_live():
    """Pure liveness probe; it never checks an external dependency."""
    return {
        "status": "alive",
        "version": settings.APP_VERSION,
        "external_dependencies_probed": False,
    }


@app.get("/health/ready")
def health_ready(response: Response):
    """Local readiness only; cloud/scanner/public reachability is not implied."""
    result = local_readiness()
    if result["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
