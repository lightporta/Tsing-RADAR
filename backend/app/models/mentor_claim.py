"""mentor_claims 档案认领申请与审批记录。"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid

# factor_used：auto_unique（唯一候选自动绑定）/ email_match / manual（管理员人工审批）
FACTOR_AUTO_UNIQUE = "auto_unique"
FACTOR_EMAIL_MATCH = "email_match"
FACTOR_MANUAL = "manual"
# status：pending / approved / rejected
CLAIM_PENDING = "pending"
CLAIM_APPROVED = "approved"
CLAIM_REJECTED = "rejected"


class MentorClaim(Base):
    __tablename__ = "mentor_claims"

    claim_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    account_id = Column(
        String(36),
        ForeignKey("mentor_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    advisor_id = Column(String(20), nullable=True)  # 审批通过时写入
    candidate_json = Column(JSON, nullable=False, default=list)
    factor_used = Column(String(20), nullable=False, default=FACTOR_MANUAL)
    status = Column(String(20), nullable=False, default=CLAIM_PENDING)
    admin_note = Column(Text, nullable=True)
    decided_by = Column(String(64), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
