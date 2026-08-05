"""storage_objects 对象存储表（v2.2 新增）。

记录每个上传对象的所有权、声明大小、MIME、扫描状态与本地路径/键。
扫描状态取值：pending / clean / quarantined。
失败关闭：扫描不可用、超时或失败时，状态保持 pending/quarantined，
对象不得进入 clean，因此不可被下载（见 services/scanner.py 与 api/v1/storage.py）。
"""

from sqlalchemy import Column, DateTime, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class StorageObject(Base):
    __tablename__ = "storage_objects"

    object_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    owner_subject = Column(String(64), index=True)  # 服务端会话主体，不信任前端自报
    bucket = Column(String(64))
    object_key = Column(String(128))  # 随机键，避免暴露原文件名
    original_filename = Column(String(255))  # 仅元数据，不作为存储路径
    declared_size = Column(String(32))  # 声明字节数（字符串以兼容 SQLite/PG）
    mime = Column(String(128))
    scan_status = Column(String(16), default="pending", index=True)
    created_at = Column(DateTime, server_default=func.now())
