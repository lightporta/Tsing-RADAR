"""pytest 配置：将 backend 加入 sys.path，并在 import 前设置测试数据库。"""

import logging
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

# 本地 macOS 开发环境：为 PDF/DOCX 生成测试自动提供 CJK 字体
# （生产镜像内置字体；其他环境需自行配置 DOCUMENT_CJK_FONT_PATH）
if not os.environ.get("DOCUMENT_CJK_FONT_PATH"):
    _mac_cjk_font = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    if Path(_mac_cjk_font).is_file():
        os.environ["DOCUMENT_CJK_FONT_PATH"] = _mac_cjk_font

# 干净检出不得依赖本机未跟踪的导师 evidence。测试显式使用仓库中经过
# 发布门校验的 0 记录治理种子；缺失/损坏文件仍由聚焦负向测试覆盖。
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_MENTOR_DATA_PATH = (
    REPOSITORY_ROOT
    / "deploy"
    / "production"
    / "data"
    / "empty-mentor-governance.json"
)
if not TEST_MENTOR_DATA_PATH.is_file():
    raise RuntimeError("tracked_empty_mentor_governance_seed_missing")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 清除 settings 缓存，让测试环境变量生效
import app.core.config as _config  # noqa: E402
import app.services.data_loader as _data_loader  # noqa: E402

_config.get_settings.cache_clear()
_data_loader._DATA_PATH = str(TEST_MENTOR_DATA_PATH)

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


@pytest.fixture(autouse=True)
def isolate_mentor_service_records():
    """导师服务表按 FK 顺序清理，防止跨测试泄漏。"""

    yield
    from app.db.session import SessionLocal
    from app.models.artifact_audit import ArtifactAuditEvent
    from app.models.email_verification_code import EmailVerificationCode
    from app.models.mentor_account import MentorAccount
    from app.models.mentor_claim import MentorClaim
    from app.models.mentor_campus_card import MentorCampusCard
    from app.models.mentor_profile import MentorProfile
    from app.models.mentor_profile_edit import MentorProfileEdit
    from app.models.takedown_request import TakedownRequest

    with SessionLocal() as db:
        db.query(MentorProfileEdit).delete(synchronize_session=False)
        db.query(TakedownRequest).delete(synchronize_session=False)
        db.query(MentorCampusCard).delete(synchronize_session=False)
        db.query(MentorClaim).delete(synchronize_session=False)
        db.query(MentorProfile).delete(synchronize_session=False)
        db.query(EmailVerificationCode).delete(synchronize_session=False)
        db.query(MentorAccount).delete(synchronize_session=False)
        # 仅清理导师服务审计事件，不影响 A6 私有文件审计断言
        db.query(ArtifactAuditEvent).filter(
            ArtifactAuditEvent.event_type.like("mentor_%")
        ).delete(synchronize_session=False)
        db.commit()


@pytest.fixture(autouse=True)
def restore_loggers_disabled_by_alembic():
    """test_a5_migration 跑迁移时 alembic env.py 的 fileConfig 默认
    disable_existing_loggers=True，会把既有 logger 置为 disabled，导致其后
    caplog 断言（如导师验证码日志）捕获失效。每个测试后统一恢复。
    """

    yield
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and logger.disabled:
            logger.disabled = False
