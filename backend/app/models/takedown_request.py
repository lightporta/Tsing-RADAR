"""takedown_requests 导师隐私下线/字段隐藏申请。"""

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid

# scope：full（整档下线）/ field（单字段隐藏）
SCOPE_FULL = "full"
SCOPE_FIELD = "field"
# status：pending / approved / rejected
TK_PENDING = "pending"
TK_APPROVED = "approved"
TK_REJECTED = "rejected"


class TakedownRequest(Base):
    __tablename__ = "takedown_requests"

    req_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    account_id = Column(
        String(36),
        ForeignKey("mentor_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    advisor_id = Column(String(20), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    scope = Column(String(10), nullable=False, default=SCOPE_FULL)
    field_name = Column(String(50), nullable=True)  # scope=field 时指定
    status = Column(String(20), nullable=False, default=TK_PENDING)
    admin_note = Column(Text, nullable=True)
    decided_by = Column(String(64), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
