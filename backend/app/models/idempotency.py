"""服务端持久化幂等记录；只保存键控摘要，不保存原始幂等键或请求正文。"""

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)

from app.db.base import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject_id",
            "operation",
            "key_digest",
            name="uq_idempotency_owner_operation_key",
        ),
    )

    idempotency_id = Column(String(36), primary_key=True)
    owner_subject_id = Column(String(64), nullable=False, index=True)
    operation = Column(String(48), nullable=False)
    key_digest = Column(String(64), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    # The raw per-attempt lease exists only in worker memory.
    attempt_digest = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="processing")
    resource_type = Column(String(32), nullable=True)
    resource_id = Column(String(64), nullable=True)
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
