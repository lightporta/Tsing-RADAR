"""user_memories 长期记忆表（v4.0.0，Ultra-Memory 的确定性等价物）。

只存"已确认画像"的白名单事实（六维 + 硬性条件 + 确认门标记），
由 memory_service 统一写入/召回；本表不承接任何未确认猜测。
键为 (student_id, memory_key) 复合主键，重新确认即覆盖，无冗余历史。
"""

from sqlalchemy import JSON, Column, DateTime, String, func

from app.db.base import Base


class UserMemory(Base):
    __tablename__ = "user_memories"

    student_id = Column(String(64), primary_key=True)
    memory_key = Column(String(50), primary_key=True)
    memory_value = Column(JSON, nullable=False)
    source = Column(String(30), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
