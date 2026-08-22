"""mentor_favorites 导师收藏表（v4.3.0 阶段五）。

每主体每导师一条（唯一约束兜底并发）；advisor_name 为收藏时来自匹配
上下文的展示用去规范化姓名，advisor_id 是权威键。收藏写入只有两条
路径且同经 tools_registry 的 save_favorite 执行体（校验 + 幂等）：
确定性意图词路由（「收藏第 N 个」）与 LLM 自主调用（阶段B 转正）。
"""

from sqlalchemy import Column, DateTime, String, UniqueConstraint, func

from app.db.base import Base
from app.models.match_record import _uuid


class MentorFavorite(Base):
    __tablename__ = "mentor_favorites"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "advisor_id", name="uq_mentor_favorites_pair"
        ),
    )

    favorite_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(64), nullable=False, index=True)
    advisor_id = Column(String(64), nullable=False, index=True)
    advisor_name = Column(String(120), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
