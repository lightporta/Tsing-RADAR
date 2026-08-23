"""mentor_profile_edits 导师档案字段级编辑申请（逐字段进审批流）。"""

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid

# status：pending / approved / rejected
EDIT_PENDING = "pending"
EDIT_APPROVED = "approved"
EDIT_REJECTED = "rejected"


class MentorProfileEdit(Base):
    __tablename__ = "mentor_profile_edits"

    edit_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    account_id = Column(
        String(36),
        ForeignKey("mentor_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    advisor_id = Column(String(20), nullable=False, index=True)
    field_name = Column(String(50), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=EDIT_PENDING)
    admin_note = Column(Text, nullable=True)
    decided_by = Column(String(64), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
