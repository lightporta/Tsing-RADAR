"""Alembic 环境配置：从 app.core.config 读取 DATABASE_URL，从 models 导入元数据。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app import models  # noqa: F401  # 确保所有模型被导入

config = context.config
# ConfigParser treats percent signs as interpolation tokens. SQLAlchemy URLs
# legitimately contain percent-escaped credential bytes, so escape only for
# ConfigParser storage; reading the option restores the original URL bytes.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
