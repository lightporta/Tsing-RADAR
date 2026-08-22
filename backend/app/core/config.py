"""应用配置（pydantic-settings，从 .env 读取）。

混合方案：
- 开发期默认 SQLite + 内存 store，开箱即用
- 生产期通过 .env 切换 PostgreSQL + Redis
"""

from functools import lru_cache
import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from pydantic import Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_MAX_SECRET_FILE_BYTES = 64 * 1024


def _read_secret_file(name: str, value: str) -> str:
    path = Path(value)
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError
        if path.stat().st_size > _MAX_SECRET_FILE_BYTES:
            raise ValueError
        material = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{name} secret file is unavailable") from exc
    if not material or "\x00" in material:
        raise ValueError(f"{name} secret file is empty or invalid")
    return material


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # —— 应用 ——
    APP_NAME: str = "Tsing-RADAR 清研寻师雷达 v2.2"
    APP_VERSION: str = "2.2.0"
    DEBUG: bool = True
    # The additive production Compose sets this flag. Development and the
    # existing local integration Compose intentionally retain their semantics.
    PRODUCTION_DEPLOYMENT: bool = False

    # —— 数据库 ——
    # 开发期默认 SQLite（开箱即用）；生产期 .env 配置 PostgreSQL
    DATABASE_URL: str = "sqlite:///./tsing_radar.db"
    DATABASE_HOST: Optional[str] = None
    DATABASE_PORT: int = Field(default=5432, ge=1, le=65535)
    DATABASE_NAME: Optional[str] = None
    DATABASE_USER: Optional[str] = None
    DATABASE_PASSWORD_FILE: Optional[str] = None
    # SQLite 开发可自动建表；Compose/生产必须由单独 Alembic 任务管理。
    AUTO_CREATE_SCHEMA: bool = True

    # —— Redis（可选，未配置时降级为内存缓存）——
    REDIS_URL: Optional[str] = None
    REDIS_HOST: Optional[str] = None
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    REDIS_DATABASE: int = Field(default=0, ge=0, le=15)
    REDIS_PASSWORD_FILE: Optional[str] = None

    # Optional score evidence is a separate, fail-closed release from mentor
    # directory facts.  No file means the visualisation coverage gate is shut.
    MENTOR_SCORE_DATA_FILE: Optional[str] = None
    MENTOR_SCORE_DATA_EXPECTED_SHA256: Optional[str] = None
    MENTOR_SCORE_COVERAGE_THRESHOLD: float = Field(default=0.8, gt=0, le=1)

    # —— 大模型 ——
    # 生产只接受 provider + 文件型密钥；开发继续兼容既有直接变量。
    LLM_ENABLED: bool = True
    # GLM is the only supported provider.  A different LLM_PROVIDER is rejected
    # by Pydantic before startup; provider-specific fallback channels do not
    # exist in the application settings anymore.
    LLM_PROVIDER: Optional[Literal["glm"]] = None
    LLM_API_KEY_FILE: Optional[str] = None
    GLM_API_KEY: Optional[str] = None
    GLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    GLM_CHAT_MODEL: str = "glm-4-flash"
    GLM_EMBED_MODEL: str = "embedding-3"
    LLM_TIMEOUT: int = 30
    # Optional interview wording must never hold the fixed state-machine reply
    # for the full generic document/analysis timeout.
    LLM_INTERVIEW_ENHANCEMENT_TIMEOUT_SECONDS: float = Field(
        default=4.0,
        ge=0.5,
        le=8.0,
    )
    _llm_credentials: tuple[tuple[str, str], ...] = PrivateAttr(default=())

    # —— 导师服务邮件（邮箱验证码登录）——
    # MAIL_MODE=console：验证码仅打印到服务端日志（开发/测试默认，不发送）；
    # MAIL_MODE=smtp：走 SMTP 发送（生产，须配置 MAIL_HOST/USER/PASSWORD/MAIL_FROM）。
    # 生产禁止 console（验证码不得进日志）；SMTP 密码用 MAIL_PASSWORD_FILE 文件挂载。
    MAIL_MODE: str = "console"
    MAIL_PASSWORD_FILE: Optional[str] = None
    MAIL_HOST: Optional[str] = "smtp.tsinghua.edu.cn"
    MAIL_PORT: int = Field(default=465, ge=1, le=65535)
    MAIL_USER: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: str = "Tsing-RADAR 导师服务 <no-reply@tsingradar.com.cn>"
    MAIL_USE_TLS: bool = True
    # 验证码有效期 / 重发限频 / 日上限 / 校验失败次数上限
    MENTOR_CODE_TTL_SECONDS: int = Field(default=600, ge=60, le=3600)
    MENTOR_CODE_RESEND_SECONDS: int = Field(default=60, ge=30, le=600)
    MENTOR_CODE_DAILY_LIMIT: int = Field(default=10, ge=3, le=50)
    MENTOR_CODE_MAX_ATTEMPTS: int = Field(default=5, ge=3, le=20)

    # —— 学生评价（M1）——
    # 同一评分主体每日提交上限（服务端确定性计数；IP 频控随 B-05 上线前补齐）
    ADVISOR_RATING_DAILY_LIMIT: int = Field(default=5, ge=1, le=100)
    # 主观雷达展示门槛：单维样本量低于该值时 API 不下发该维数值
    # （防低样本暴露与操纵；与前端 RATING_MIN_DIMENSION_N 保持一致）
    ADVISOR_RATING_MIN_SAMPLES: int = Field(default=8, ge=1, le=100)

    # —— 网页免认证测试模式（未实名认证测试身份）——
    # 接入清华统一身份认证之前，网页通道整体是临时测试模式；到期后端
    # 自动停止该通道的云端功能（fail-closed）。生产 preflight 要求显式
    # 配置到期时间；未配置时不做到期拦截（本地开发默认）。
    WEB_TEST_MODE_ENABLED: bool = True
    WEB_TEST_MODE_EXPIRES_AT: Optional[datetime] = None

    # —— 招募评论区 ——
    # 服务内确定性限频：同一评论主体每日上限 / 单帖每主体上限（超限 429）
    COMMENT_DAILY_LIMIT: int = Field(default=10, ge=1, le=100)
    COMMENT_PER_POST_LIMIT: int = Field(default=3, ge=1, le=20)
    # 评论列表每父评论内嵌的回复条数
    COMMENT_REPLY_PREVIEW_LIMIT: int = Field(default=3, ge=1, le=20)
    # 敏感词表外置：逗号分隔内联词表 + 外部文件（每行一词），代码不硬编码词表
    CONTENT_SENSITIVE_WORDS: str = ""
    CONTENT_SENSITIVE_WORDS_FILE: Optional[str] = None
    # 对话敏感话题词表（v4.3.0）：政治/宗教等对话红线话题，命中即明确拒绝
    # 并回主线；默认空 = 不拦截任何话题（部署方按需注入）
    CHAT_SENSITIVE_WORDS: str = ""
    CHAT_SENSITIVE_WORDS_FILE: Optional[str] = None
    # v4.3.0 阶段三：知识库向量语义补充的余弦相似度阈值——词法未命中时，
    # 仅相似度 ≥ 阈值的导师块进入 top-K 补充；全不达标则保持诚实拒答
    # （拒答门红线）。默认 0.60，生产可按实测分布调优。
    KNOWLEDGE_VECTOR_MIN_SIMILARITY: float = Field(
        default=0.60, ge=0.0, le=1.0
    )

    # —— CORS ——
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000,null"
    )

    # —— 管理员（训练触发）——
    # No public development default. Production validation requires at least
    # 32 bytes and separation from every other signing/authentication secret.
    ADMIN_TOKEN: Optional[str] = None
    ADMIN_TOKEN_FILE: Optional[str] = None

    # —— 清小搭平台 ——
    APP_KEY: Optional[str] = None
    QXD_BASE_URL: Optional[str] = None
    # 平台调用本服务时使用的入站 Bearer 凭证。生产环境必须显式配置。
    QXD_API_KEY: Optional[str] = None
    QXD_API_KEY_FILE: Optional[str] = None
    # Inbound remote media fetching and outbound signed artifact delivery are
    # separate capabilities. Both remain disabled unless explicitly released.
    QXD_REMOTE_MEDIA_FETCH_ENABLED: bool = False
    QXD_ATTACHMENTS_ENABLED: bool = False
    # 清小搭文本雷达图形态：auto（默认，退化数据自动降级柱状图）/
    # radar（固定线状雷达）/ bars（固定柱状图）。未知取值按 auto。
    RADAR_TEXT_FORM: str = "auto"
    # 逗号分隔的媒体下载域名白名单；启用远程媒体抓取时必须非空。
    QXD_MEDIA_ALLOWED_HOSTS: str = ""
    QXD_MEDIA_MAX_REDIRECTS: int = Field(default=3, ge=0, le=10)
    QXD_MEDIA_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0, le=60)
    QXD_REQUEST_TIMEOUT_SECONDS: float = Field(default=110.0, gt=0, lt=120)
    # 清小搭“测试验证”当前可能只发送最新一条 user 消息，且不提供可验证的
    # 终端用户 claim。此开关只用于单人、本地、临时隧道试聊；生产启动门拒绝启用。
    QXD_TRIAL_SINGLE_USER_MODE: bool = False
    QXD_TRIAL_IDLE_TTL_SECONDS: int = Field(
        default=10 * 60,
        ge=60,
        le=30 * 60,
    )
    QXD_TRIAL_ABSOLUTE_TTL_SECONDS: int = Field(
        default=60 * 60,
        ge=5 * 60,
        le=2 * 60 * 60,
    )
    QXD_MAX_MEDIA_PARTS: int = Field(default=8, ge=1, le=16)
    QXD_IMAGE_MAX_BYTES: int = Field(default=20 * 1024 * 1024, gt=0)
    QXD_AUDIO_MAX_BYTES: int = Field(default=25 * 1024 * 1024, gt=0)
    QXD_FILE_MAX_BYTES: int = Field(default=200 * 1024 * 1024, gt=0)
    QXD_MEDIA_MAX_TOTAL_BYTES: int = Field(default=250 * 1024 * 1024, gt=0)

    # —— A5 身份与私有文件 ——
    # 仅用于服务端摘要，生产环境必须覆盖默认值。
    SESSION_HMAC_SECRET: str = "local-development-only-change-me"
    SESSION_HMAC_SECRET_FILE: Optional[str] = None
    WEB_SESSION_COOKIE: str = "tsing_radar_session"
    WEB_CSRF_COOKIE: str = "tsing_radar_csrf"
    WEB_COOKIE_SECURE: bool = False
    WEB_SESSION_TTL_SECONDS: int = Field(default=7 * 24 * 60 * 60, ge=300)
    # processing 记录超过此时间会由下一次同键请求原子标记为失败，
    # 防止进程崩溃后永久占用幂等键。正常生成/解析预算远低于该值。
    IDEMPOTENCY_PROCESSING_TTL_SECONDS: int = Field(
        default=300,
        ge=30,
        le=3600,
    )
    # 平台 Bearer 只认证平台调用；终端用户 claim 使用独立密钥验证。
    QXD_END_USER_SIGNING_SECRET: Optional[str] = None
    QXD_END_USER_SIGNING_SECRET_FILE: Optional[str] = None
    PRIVATE_UPLOAD_ROOT: str = "./private_uploads"
    PRIVATE_UPLOAD_MAX_BYTES: int = Field(default=8 * 1024 * 1024, gt=0)
    PDF_MAX_PAGES: int = Field(default=120, ge=1, le=1000)
    PDF_MAX_PAGE_TEXT_CHARS: int = Field(default=100_000, ge=1)
    PDF_MAX_EXTRACTED_TEXT_CHARS: int = Field(default=500_000, ge=1)
    PDF_PARSE_TIMEOUT_SECONDS: float = Field(default=8.0, gt=0, le=60)

    # —— A6 私有对象存储、扫描与短时签名交付 ——
    # 本地开发使用私有文件系统对象存储；生产可切换到私有 S3 兼容桶。
    OBJECT_STORE_BACKEND: Literal["local", "s3"] = "local"
    OBJECT_STORAGE_LOCAL_ROOT: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None
    S3_REGION: Optional[str] = None
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_ACCESS_KEY_ID_FILE: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None
    S3_SECRET_ACCESS_KEY_FILE: Optional[str] = None
    S3_PROVIDER: Literal["s3_compatible", "tencent_cos"] = "s3_compatible"
    S3_ADDRESSING_STYLE: Literal["auto", "path", "virtual"] = "auto"
    # DEP2 本地 MinIO 未配置 KMS，必须显式为 none；非 DEBUG 启动门强制 AES256。
    S3_SERVER_SIDE_ENCRYPTION: Literal["none", "AES256"] = "AES256"
    OBJECT_STORAGE_MAX_READ_BYTES: int = Field(
        default=16 * 1024 * 1024,
        ge=1024,
        le=256 * 1024 * 1024,
    )
    # 只允许应用层签名 URL；对象桶本身不得设为 public。
    ARTIFACT_SIGNING_SECRET: str = "local-artifact-signing-change-me"
    ARTIFACT_SIGNING_SECRET_FILE: Optional[str] = None
    WEB_DOWNLOAD_TTL_SECONDS: int = Field(default=300, ge=30, le=1800)
    QXD_ATTACHMENT_TTL_SECONDS: int = Field(default=180, ge=30, le=600)
    PUBLIC_BASE_URL: Optional[str] = None
    # 只供本地合同测试显式允许 example.* / *.test；生产模式一律拒绝。
    ALLOW_TEST_PUBLIC_BASE_URL: bool = False
    # builtin 只代表结构与已知特征检查，不冒充完整反病毒扫描。
    FILE_SCAN_MODE: Literal["builtin", "clamav"] = "builtin"
    CLAMAV_HOST: Optional[str] = None
    CLAMAV_PORT: int = Field(default=3310, ge=1, le=65535)
    CLAMAV_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    DOCUMENT_CJK_FONT_PATH: Optional[str] = None

    @model_validator(mode="after")
    def load_file_backed_secrets(self) -> "Settings":
        """Resolve explicit *_FILE inputs without exposing material in Compose.

        Direct environment values remain supported for existing development and
        test paths. The production deployment gate separately requires files.
        """

        fields_set = self.model_fields_set
        mappings = (
            ("ADMIN_TOKEN", "ADMIN_TOKEN_FILE"),
            ("QXD_API_KEY", "QXD_API_KEY_FILE"),
            (
                "QXD_END_USER_SIGNING_SECRET",
                "QXD_END_USER_SIGNING_SECRET_FILE",
            ),
            ("SESSION_HMAC_SECRET", "SESSION_HMAC_SECRET_FILE"),
            ("ARTIFACT_SIGNING_SECRET", "ARTIFACT_SIGNING_SECRET_FILE"),
            ("S3_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID_FILE"),
            ("S3_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY_FILE"),
            ("MAIL_PASSWORD", "MAIL_PASSWORD_FILE"),
        )
        for target_name, file_name in mappings:
            secret_path = getattr(self, file_name)
            if not secret_path:
                continue
            if target_name in fields_set:
                raise ValueError(
                    f"{target_name} and {file_name} are mutually exclusive"
                )
            object.__setattr__(
                self,
                target_name,
                _read_secret_file(file_name, secret_path),
            )

        if self.DATABASE_PASSWORD_FILE:
            if "DATABASE_URL" in fields_set:
                raise ValueError(
                    "DATABASE_URL and DATABASE_PASSWORD_FILE are mutually exclusive"
                )
            if not all(
                (self.DATABASE_HOST, self.DATABASE_NAME, self.DATABASE_USER)
            ):
                raise ValueError(
                    "DATABASE_HOST, DATABASE_NAME and DATABASE_USER are required"
                )
            password = _read_secret_file(
                "DATABASE_PASSWORD_FILE",
                self.DATABASE_PASSWORD_FILE,
            )
            database_url = (
                "postgresql+psycopg://"
                f"{quote(self.DATABASE_USER or '', safe='')}:"
                f"{quote(password, safe='')}@{self.DATABASE_HOST}:"
                f"{self.DATABASE_PORT}/{quote(self.DATABASE_NAME or '', safe='')}"
            )
            object.__setattr__(self, "DATABASE_URL", database_url)

        if self.REDIS_PASSWORD_FILE:
            if "REDIS_URL" in fields_set:
                raise ValueError(
                    "REDIS_URL and REDIS_PASSWORD_FILE are mutually exclusive"
                )
            if not self.REDIS_HOST:
                raise ValueError("REDIS_HOST is required with REDIS_PASSWORD_FILE")
            password = _read_secret_file(
                "REDIS_PASSWORD_FILE",
                self.REDIS_PASSWORD_FILE,
            )
            redis_url = (
                f"redis://:{quote(password, safe='')}@{self.REDIS_HOST}:"
                f"{self.REDIS_PORT}/{self.REDIS_DATABASE}"
            )
            object.__setattr__(self, "REDIS_URL", redis_url)

        direct_credentials = (("glm", self.GLM_API_KEY),) if self.GLM_API_KEY else ()
        if not self.LLM_ENABLED:
            if self.LLM_API_KEY_FILE or self.LLM_PROVIDER or direct_credentials:
                raise ValueError(
                    "LLM credentials require LLM_ENABLED=true"
                )
            credentials = ()
        elif self.LLM_API_KEY_FILE:
            if direct_credentials:
                raise ValueError(
                    "LLM_API_KEY_FILE and direct provider keys are mutually exclusive"
                )
            if not self.LLM_PROVIDER:
                raise ValueError("LLM_PROVIDER is required with LLM_API_KEY_FILE")
            credentials = (
                (
                    self.LLM_PROVIDER,
                    _read_secret_file(
                        "LLM_API_KEY_FILE",
                        self.LLM_API_KEY_FILE,
                    ),
                ),
            )
        elif self.PRODUCTION_DEPLOYMENT:
            if direct_credentials:
                raise ValueError(
                    "production deployment rejects direct LLM provider keys"
                )
            raise ValueError(
                "production deployment requires LLM_PROVIDER and LLM_API_KEY_FILE"
            )
        elif self.LLM_PROVIDER:
            selected = tuple(
                item for item in direct_credentials if item[0] == self.LLM_PROVIDER
            )
            if len(selected) != 1 or len(direct_credentials) != 1:
                raise ValueError(
                    "LLM_PROVIDER must match the only configured direct provider key"
                )
            credentials = selected
        else:
            credentials = direct_credentials
        object.__setattr__(self, "_llm_credentials", credentials)

        if self.PRODUCTION_DEPLOYMENT:
            if self.MAIL_MODE != "smtp":
                raise ValueError(
                    "production deployment requires MAIL_MODE=smtp "
                    "(console mode would leak verification codes to logs)"
                )
            if self.MAIL_MODE == "smtp" and not self.MAIL_PASSWORD_FILE:
                raise ValueError(
                    "production deployment requires MAIL_PASSWORD_FILE "
                    "(direct SMTP passwords are not accepted)"
                )
        return self

    @property
    def production_secret_files_configured(self) -> bool:
        required = [
            self.DATABASE_PASSWORD_FILE,
            self.REDIS_PASSWORD_FILE,
            self.ADMIN_TOKEN_FILE,
            self.SESSION_HMAC_SECRET_FILE,
            self.ARTIFACT_SIGNING_SECRET_FILE,
            self.S3_ACCESS_KEY_ID_FILE,
            self.S3_SECRET_ACCESS_KEY_FILE,
        ]
        if self.LLM_ENABLED:
            required.append(self.LLM_API_KEY_FILE)
        return all(required)

    @property
    def production_secret_file_paths(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self.DATABASE_PASSWORD_FILE,
                self.REDIS_PASSWORD_FILE,
                self.ADMIN_TOKEN_FILE,
                self.SESSION_HMAC_SECRET_FILE,
                self.ARTIFACT_SIGNING_SECRET_FILE,
                self.S3_ACCESS_KEY_ID_FILE,
                self.S3_SECRET_ACCESS_KEY_FILE,
                self.QXD_API_KEY_FILE,
                self.QXD_END_USER_SIGNING_SECRET_FILE,
                self.LLM_API_KEY_FILE,
                self.MAIL_PASSWORD_FILE,
            )
            if value
        )

    @property
    def production_secret_file_permissions_valid(self) -> bool:
        if not self.production_secret_files_configured:
            return False
        for value in self.production_secret_file_paths:
            path = Path(value)
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                return False
            if os.name == "posix" and path.stat().st_mode & 0o077:
                return False
        return True

    @property
    def llm_credentials(self) -> tuple[tuple[str, str], ...]:
        """Resolved provider/key pairs; file material is read once at startup."""
        return self._llm_credentials

    @property
    def configured_llm_providers(self) -> tuple[str, ...]:
        return tuple(provider for provider, _ in self._llm_credentials)

    @property
    def llm_secret_file_permissions_valid(self) -> bool:
        if not self.LLM_ENABLED:
            return True
        if not self.LLM_API_KEY_FILE:
            return False
        path = Path(self.LLM_API_KEY_FILE)
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            return False
        return not (os.name == "posix" and path.stat().st_mode & 0o077)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def qxd_media_allowed_hosts_list(self) -> list[str]:
        return [
            host.strip().lower().rstrip(".")
            for host in self.QXD_MEDIA_ALLOWED_HOSTS.split(",")
            if host.strip()
        ]

    @property
    def object_storage_local_root(self) -> str:
        return self.OBJECT_STORAGE_LOCAL_ROOT or self.PRIVATE_UPLOAD_ROOT


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
