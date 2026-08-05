"""数据库会话引擎。

统一 MySQL 8.x（本地与生产同方言）。DATABASE_URL 通过环境变量注入，
默认驱动 mysql+pymysql，字符集 utf8mb4。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# MySQL 连接池配置：
# - pool_pre_ping=True：连接被服务端断开时自动重连，避免长连接失效
# - pool_recycle=3600：每小时回收连接（MySQL 默认 wait_timeout=28800s，留充足余量）
# - echo=False：关闭 SQL 日志（debug 阶段可改 True）
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求获取独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """创建所有表（仅用于一次性 bootstrap 与测试 fixture，生产用 Alembic 迁移）。"""
    from app.db.base import Base  # noqa: F401
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
