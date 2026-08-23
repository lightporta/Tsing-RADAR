"""applications 投递表（文档表 6）。"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)

from app.db.base import Base
from app.models.match_record import _uuid


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "status = 'withdrawn' OR resume_id IS NOT NULL",
            name="ck_active_application_has_document",
        ),
        Index(
            "uq_applications_active_document",
            "student_id",
            "recruit_id",
            "resume_id",
            unique=True,
            sqlite_where=text("status != 'withdrawn'"),
            postgresql_where=text("status != 'withdrawn'"),
        ),
    )

    app_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    recruit_id = Column(String(36), index=True)
    student_id = Column(String(64), nullable=False, index=True)
    resume_id = Column(
        String(36),
        ForeignKey("private_documents.document_id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(20), nullable=False, default="submitted")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
