"""应用配置（pydantic-settings，从 .env 读取）。

混合方案：
- 开发期默认 SQLite + 内存 store，开箱即用
- 生产期通过 .env 切换 PostgreSQL + Redis + Milvus
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # —— 应用 ——
    APP_NAME: str = "Tsing-RADAR 清研寻师雷达 v2.1"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = True

    # —— 数据库 ——
    # 开发期默认 SQLite（开箱即用）；生产期 .env 配置 PostgreSQL
    DATABASE_URL: str = "sqlite:///./tsing_radar.db"

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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
