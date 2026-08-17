"""mentor_accounts 导师账号表（邮箱验证码登录 + 档案认领状态）。"""

from sqlalchemy import Column, DateTime, String, func

from app.db.base import Base
from app.models.match_record import _uuid

# 账号状态：unclaimed（已验证邮箱、未绑定档案）→ claim_pending（认领待审批）→ claimed
STATUS_UNCLAIMED = "unclaimed"
STATUS_CLAIM_PENDING = "claim_pending"
STATUS_CLAIMED = "claimed"


class MentorAccount(Base):
    __tablename__ = "mentor_accounts"

    account_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    advisor_id = Column(String(20), nullable=True, index=True)  # 认领后绑定
    email = Column(String(100), nullable=False, unique=True)
    subject_id = Column(String(64), nullable=False, unique=True)  # mnt_<uuid> 稳定主体
    # 当前绑定到哪个 Web 会话（复用 identity_sessions，不新增会话表/cookie）
    bound_session_id = Column(String(36), nullable=True, unique=True)
    status = Column(String(20), nullable=False, default=STATUS_UNCLAIMED)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
