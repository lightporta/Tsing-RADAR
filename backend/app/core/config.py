"""应用配置（pydantic-settings，从 .env 读取）。

统一方案（不再支持 SQLite 运行时）：
- 本地开发与生产线上统一使用 MySQL 8.x
- DATABASE_URL 走环境变量；唯一驱动 mysql+pymysql
- 字符集 utf8mb4，支持中文与 emoji
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # —— 应用 ——
    APP_NAME: str = "Tsing-RADAR 清研寻师雷达 v2.2"
    APP_VERSION: str = "2.2.0"
    DEBUG: bool = True

    # —— 数据库 ——
    # 统一 MySQL 8.x；本地开发与生产同方言，不再支持 SQLite 运行时
    # 示例：mysql+pymysql://root:password@127.0.0.1:3306/teacher_db?charset=utf8mb4
    DATABASE_URL: str = "mysql+pymysql://root:password@127.0.0.1:3306/teacher_db?charset=utf8mb4"

    # —— Redis（可选，未配置时降级为内存缓存）——
    REDIS_URL: Optional[str] = None

    # —— 向量数据库（可选，未配置时降级为 hash 伪向量）——
    MILVUS_HOST: Optional[str] = None
    MILVUS_PORT: int = 19530

    # —— 大模型（用户要求接真模型，需配置）——
    GLM_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    GLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    GLM_CHAT_MODEL: str = "glm-4-flash"
    DEEPSEEK_CHAT_MODEL: str = "deepseek-chat"
    GLM_EMBED_MODEL: str = "embedding-3"
    LLM_TIMEOUT: int = 30

    # —— 邮件（清华 SMTP，OAuth 2.0 占位）——
    SMTP_HOST: Optional[str] = "smtp.tsinghua.edu.cn"
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # —— CORS ——
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000,null"
    )

    # —— 管理员（训练触发）——
    ADMIN_TOKEN: str = "admin"

    # —— 清小搭平台 ——
    APP_KEY: Optional[str] = None
    QXD_BASE_URL: Optional[str] = None
    # 公网基址（v2.2）：清小搭附件必须能从真实 HTTPS 地址取得。
    # 未配置时，附件协议必须返回「不可交付」，不得降级为测试域。
    PUBLIC_BASE_URL: Optional[str] = None

    # —— 对象存储（v2.2）——
    # local：本地文件目录（开发期默认）；生产期应切到真实私有 S3（需授权）
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_DIR: str = "./storage_objects"
    STORAGE_BUCKET: str = "tsing-radar"

    # —— 下载签名（v2.2）——
    # HMAC 一次性下载令牌密钥；生产期必须从环境变量注入强随机值
    DOWNLOAD_SIGNING_SECRET: str = "dev-only-do-not-use-in-prod"
    DOWNLOAD_TOKEN_TTL: int = 300  # 秒

    # —— 对象读取硬上限（v2.2，对应门禁「对象读取硬上限」）——
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MB
    MAX_DOWNLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MB
    MAX_PDF_PAGES: int = 100

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
