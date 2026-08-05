"""pytest 配置：将 backend 加入 sys.path，并在 import 前设置测试数据库。"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# 每个 pytest 进程使用独立临时 SQLite，避免旧 schema 掩盖迁移问题。
TEST_DB_PATH = Path(tempfile.gettempdir()) / f"tsing_radar_pytest_{os.getpid()}.db"
TEST_DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["QXD_API_KEY"] = "test-qxd-key"
os.environ["QXD_END_USER_SIGNING_SECRET"] = "test-qxd-end-user-secret"
os.environ["SESSION_HMAC_SECRET"] = "test-web-session-secret"
os.environ["ARTIFACT_SIGNING_SECRET"] = "test-artifact-signing-secret"
os.environ["ADMIN_TOKEN"] = "test-admin-token-not-for-production"
os.environ["PUBLIC_BASE_URL"] = "https://agent.example.edu"
os.environ["ALLOW_TEST_PUBLIC_BASE_URL"] = "true"
os.environ["QXD_ATTACHMENTS_ENABLED"] = "true"
os.environ["FILE_SCAN_MODE"] = "builtin"
os.environ["OBJECT_STORE_BACKEND"] = "local"
PRIVATE_UPLOAD_ROOT = (
    Path(tempfile.gettempdir()) / f"tsing_radar_uploads_{os.getpid()}"
)
shutil.rmtree(PRIVATE_UPLOAD_ROOT, ignore_errors=True)
os.environ["PRIVATE_UPLOAD_ROOT"] = str(PRIVATE_UPLOAD_ROOT)
os.environ["OBJECT_STORAGE_LOCAL_ROOT"] = str(PRIVATE_UPLOAD_ROOT)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 清除 settings 缓存，让测试环境变量生效
import app.core.config as _config  # noqa: E402

_config.get_settings.cache_clear()

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """会话级：建表。"""
    from app.db.session import engine, init_db

    init_db()
    yield
    engine.dispose()
    TEST_DB_PATH.unlink(missing_ok=True)
    shutil.rmtree(PRIVATE_UPLOAD_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_recruitment_records():
    """Recruitment/application fixtures must not leak into later API tests."""

    yield
    from app.db.session import SessionLocal
    from app.models.application import Application
    from app.models.recruitment import Recruitment

    with SessionLocal() as db:
        db.query(Application).delete(synchronize_session=False)
        db.query(Recruitment).delete(synchronize_session=False)
        db.commit()
