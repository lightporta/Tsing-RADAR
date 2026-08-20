"""email_verification_codes 邮箱验证码表（只存 SHA-256 摘要，不留明文）。"""

from sqlalchemy import Column, DateTime, Integer, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    email = Column(String(100), nullable=False, index=True)
    purpose = Column(String(20), nullable=False, default="mentor_login")
    code_digest = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
