"""mentor_profiles 导师档案覆盖层（认领后）。

- self_claims：通过审批的自述字段 {field_name: value}（provenance=mentor_edit）
- visibility：字段展示策略 {field_name: bool}（false=对管理端/导师端隐藏）
- takedown_at：整档下线时间戳（full 下线审批通过后写入）

本期仅导师端+管理端可见；学生侧合并到发布投影预留二期（data_loader 零改动）。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, func

from app.db.base import Base
from app.models.match_record import _uuid

# 自述字段白名单（申请编辑时校验）
SELF_CLAIM_FIELDS = (
    "self_intro",  # 导师自述
    "research_highlights",  # 研究方向亮点
    "recruiting_requirements",  # 招生要求
    "contact_display_policy",  # 联系方式展示策略
)


class MentorProfile(Base):
    __tablename__ = "mentor_profiles"

    profile_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    account_id = Column(
        String(36),
        ForeignKey("mentor_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    advisor_id = Column(String(20), nullable=False, unique=True)
    self_claims = Column(JSON, nullable=False, default=dict)
    visibility = Column(JSON, nullable=False, default=dict)
    takedown_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
