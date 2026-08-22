"""mentor_campus_cards 导师校园卡人工审核表。

邮箱验证码只用于登录；认领导师档案前必须上传校园卡并通过管理员
人工审核。审核结束后私有材料（图片/PDF 对象）立即清理，表内只保留
哈希与状态等非正文元数据。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid

# 审核状态：pending（待审）→ approved / rejected；材料在终态即清理
CARD_PENDING = "pending"
CARD_APPROVED = "approved"
CARD_REJECTED = "rejected"


class MentorCampusCard(Base):
    __tablename__ = "mentor_campus_cards"

    card_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    account_id = Column(String(36), nullable=False, index=True)
    # 对象存储后端与键；材料清理后键置空，防止悬空引用
    object_backend = Column(String(20), nullable=False, default="local")
    object_key = Column(String(200), nullable=False, default="")
    media_type = Column(String(40), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default=CARD_PENDING)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_by = Column(String(64), nullable=True)
    review_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    material_cleared_at = Column(DateTime(timezone=True), nullable=True)
