"""A5/A6 私有文档、生成产物与短时交付授权。"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    JSON,
    String,
    Text,
    func,
    text,
)

from app.db.base import Base


class PrivateDocument(Base):
    __tablename__ = "private_documents"

    document_id = Column(String(36), primary_key=True)
    owner_subject_id = Column(String(64), nullable=False, index=True)
    original_name = Column(String(180), nullable=False)
    stored_name = Column(String(80), nullable=False, unique=True)
    extension = Column(String(8), nullable=False)
    media_type = Column(String(120), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False)
    extracted_text = Column(Text, nullable=False, default="")
    document_kind = Column(String(24), nullable=False, default="upload")
    object_backend = Column(String(16), nullable=False, default="local")
    scan_status = Column(String(24), nullable=False, default="unscanned")
    scan_method = Column(String(80), nullable=False, default="")
    scan_checked_at = Column(DateTime(timezone=True), nullable=True)
    source_session_id = Column(String(36), nullable=True, index=True)
    generation_context = Column(JSON, nullable=False, default=dict)
    user_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ArtifactDeliveryGrant(Base):
    """只保存签名令牌摘要；Web 与清小搭使用不同受众。"""

    __tablename__ = "artifact_delivery_grants"
    __table_args__ = (
        Index(
            "uq_active_artifact_delivery_audience",
            "document_id",
            "audience",
            unique=True,
            sqlite_where=text("revoked = 0"),
            postgresql_where=text("revoked = false"),
        ),
    )

    grant_id = Column(String(36), primary_key=True)
    document_id = Column(
        String(36),
        ForeignKey("private_documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_subject_id = Column(String(64), nullable=False, index=True)
    audience = Column(String(24), nullable=False)
    token_digest = Column(String(64), nullable=False, unique=True)
    token_nonce = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    max_downloads = Column(Integer, nullable=False, default=1)
    use_count = Column(Integer, nullable=False, default=0)
    confirmed_at = Column(DateTime(timezone=True), nullable=False)
    last_downloaded_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DeletedArtifactTombstone(Base):
    """删除后的最小归属记录，用于幂等重试；不保留文件名或内容。"""

    __tablename__ = "deleted_artifact_tombstones"

    document_id = Column(String(36), primary_key=True)
    owner_subject_id = Column(String(64), nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=False)
