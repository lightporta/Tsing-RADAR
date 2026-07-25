"""pytest 配置：将 backend 加入 sys.path，并在 import 前设置测试数据库。"""

import os
import sys

# 测试专用 SQLite（在 import app 之前设置）
os.environ["DATABASE_URL"] = "sqlite:///./test_tsing_radar.db"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 清除 settings 缓存，让测试环境变量生效
import app.core.config as _config  # noqa: E402

_config.get_settings.cache_clear()

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """会话级：建表。"""
    from app.db.session import init_db

    init_db()
    yield
