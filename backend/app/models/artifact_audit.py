"""A6 私有产物安全审计事件；字段集合刻意不允许正文、文件名或原始令牌。"""

from sqlalchemy import Column, DateTime, Integer, String, func

from app.db.base import Base


class ArtifactAuditEvent(Base):
    __tablename__ = "artifact_audit_events"

    sequence_id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False, unique=True)
    owner_subject_id = Column(String(64), nullable=False, index=True)
    operation = Column(String(48), nullable=False)
    idempotency_key_digest = Column(String(64), nullable=True)
    document_id = Column(String(36), nullable=True, index=True)
    event_type = Column(String(40), nullable=False)
    outcome = Column(String(20), nullable=False)
    reason_code = Column(String(64), nullable=False)
    scan_method = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
