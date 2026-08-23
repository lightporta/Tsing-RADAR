"""recruitment_comments 招募评论表（两级评论，软删保楼层）。

公开输出永不含 author_principal；审核历史写入行内 governance JSON，
与 recruitment_review.py 的 review_history 模式同构。
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text, func

from app.db.base import Base
from app.models.match_record import _uuid


class RecruitmentComment(Base):
    __tablename__ = "recruitment_comments"

    comment_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    recruit_id = Column(String(36), nullable=False, index=True)
    parent_id = Column(String(36), nullable=True, index=True)  # 仅两级
    author_principal = Column(String(64), nullable=False, index=True)
    author_label = Column(String(20), nullable=False, default="student")
    # student / senior / advisor / verified_student
    is_op = Column(Boolean, nullable=False, default=False)
    content = Column(Text, nullable=False)
    review_status = Column(String(20), nullable=False, default="pending_review")
    # pending_review / approved / rejected
    like_count = Column(Integer, nullable=False, default=0)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # 软删保楼层
    created_at = Column(DateTime, server_default=func.now())
    governance = Column(JSON, nullable=False, default=dict)  # review_history 等


class RecruitmentCommentLike(Base):
    """点赞去重表：每主体每评论一次（唯一约束兜底并发）。"""

    __tablename__ = "recruitment_comment_likes"

    like_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    comment_id = Column(String(36), nullable=False, index=True)
    principal = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
