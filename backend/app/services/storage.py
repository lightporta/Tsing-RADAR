"""对象存储适配器骨架（v2.2 新增）。

对应 Annotation 1 门禁「真实私有 S3 读写、权限与加密探测」。
当前仅提供 LocalStorageBackend：写本地对象目录、随机 object key、
读取时强制 BoundedReader + MAX_DOWNLOAD_BYTES。

真实私有 S3 适配器（S3StorageBackend）为占位骨架，需授权真实云账号、
最小权限凭证、TLS、服务端加密、随机对象键、禁止 public ACL，属于未关闭门禁。

本地实现遵循以下安全约束：
- object_key 为随机 hex，不暴露原文件名；
- 读取强制走 BoundedReader，超限即失败；
- 删除走状态机（见 api/v1/storage.py），失败可重试；
- 无 public ACL 概念（本地目录不对外暴露）。
"""

from __future__ import annotations

import os
import secrets
from typing import Optional, Protocol

from app.core.config import settings
from app.services.security import BoundedReader


class ObjectMeta:
    """读取对象时返回的元数据 + 流。"""

    def __init__(self, *, path: str, size: int, mime: str) -> None:
        self.path = path
        self.size = size
        self.mime = mime


class StorageBackend(Protocol):
    """存储后端协议。"""

    def put(self, src_path: str, *, mime: str) -> tuple[str, int]:
        """把本地暂存文件写入存储，返回 (object_key, size_bytes)。"""
        ...

    def open(self, object_key: str) -> ObjectMeta:
        """打开对象用于流式读取（调用方负责用 BoundedReader 限制读取）。"""
        ...

    def delete(self, object_key: str) -> None:
        """删除对象。"""
        ...


def _random_key() -> str:
    """生成 32 字节随机 hex 作为对象键，避免原文件名泄露。"""
    return secrets.token_hex(16)


class LocalStorageBackend:
    """本地文件系统存储后端（开发期默认）。"""

    name = "local"

    def __init__(self, root_dir: Optional[str] = None, bucket: Optional[str] = None) -> None:
        self.root = root_dir or settings.STORAGE_LOCAL_DIR
        self.bucket = bucket or settings.STORAGE_BUCKET
        os.makedirs(os.path.join(self.root, self.bucket), exist_ok=True)

    def _path(self, object_key: str) -> str:
        # 防 path traversal：仅允许 hex 键
        if not all(c in "0123456789abcdef" for c in object_key) or not object_key:
            raise ValueError(f"非法 object_key：{object_key}")
        return os.path.join(self.root, self.bucket, object_key)

    def put(self, src_path: str, *, mime: str) -> tuple[str, int]:
        object_key = _random_key()
        dst = self._path(object_key)
        size = 0
        # 用 BoundedReader 强制写入上限，避免一次性读取超大文件
        with open(src_path, "rb") as src, open(dst, "wb") as out:
            reader = BoundedReader(src, max_bytes=settings.MAX_UPLOAD_BYTES)
            for chunk in reader.read_chunks():
                out.write(chunk)
                size += len(chunk)
        return object_key, size

    def open(self, object_key: str) -> ObjectMeta:
        path = self._path(object_key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"对象不存在：{object_key}")
        size = os.path.getsize(path)
        return ObjectMeta(path=path, size=size, mime="application/octet-stream")

    def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        if os.path.exists(path):
            os.remove(path)


class S3StorageBackend:
    """真实私有 S3 适配器占位（需授权真实云账号）。

    生产期应使用最小权限凭证、TLS、服务端加密（SSE-KMS）、随机对象键、
    禁止 public ACL，并补齐越权访问、对象缺失、删除失败、并发覆盖、
    短时签名过期及元数据—对象一致性的测试。当前一律抛错，保证不误用。
    """

    name = "s3"

    def put(self, src_path: str, *, mime: str) -> tuple[str, int]:
        raise NotImplementedError("真实 S3 未配置（未授权连接），不可写入")

    def open(self, object_key: str) -> ObjectMeta:
        raise NotImplementedError("真实 S3 未配置（未授权连接），不可读取")

    def delete(self, object_key: str) -> None:
        raise NotImplementedError("真实 S3 未配置（未授权连接），不可删除")


_storage: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """获取存储后端（默认 local；生产可切 s3，需真实凭证）。"""
    global _storage
    if _storage is None:
        backend = settings.STORAGE_BACKEND.lower()
        if backend == "s3":
            # 未授权时仍实例化占位，调用即抛错
            _storage = S3StorageBackend()
        else:
            _storage = LocalStorageBackend()
    return _storage


def reset_storage_cache() -> None:
    """重置缓存（测试用）。"""
    global _storage
    _storage = None
