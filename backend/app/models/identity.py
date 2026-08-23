"""A5 服务端主体、匿名 Web 会话与可信外部身份映射。"""

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint, func

from app.db.base import Base


class IdentitySession(Base):
    __tablename__ = "identity_sessions"

    session_id = Column(String(36), primary_key=True)
    subject_id = Column(String(64), nullable=False, index=True)
    channel = Column(String(16), nullable=False)
    token_digest = Column(String(64), nullable=False, unique=True)
    csrf_digest = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)


class ExternalIdentity(Base):
    """只保存带密钥摘要与随机主体；绝不保存外部 claim 或 Bearer。"""

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "claim_fingerprint", name="uq_external_identity"),
    )

    mapping_id = Column(String(36), primary_key=True)
    provider = Column(String(32), nullable=False)
    claim_fingerprint = Column(String(64), nullable=False)
    subject_id = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
