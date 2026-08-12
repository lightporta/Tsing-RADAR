"""A6 私有对象存储适配层。

对象桶始终保持私有；Web/清小搭下载只能经过应用层短时签名授权。
"""

from __future__ import annotations

import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from app.core.config import settings

_ALLOWED_PRIVATE_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_READ_CHUNK_BYTES = 64 * 1024
_TENCENT_COS_REGION = "ap-hongkong"
_TENCENT_COS_ENDPOINT = "https://cos.ap-hongkong.myqcloud.com"
_TENCENT_COS_BUCKET = re.compile(
    r"^(?=.{3,63}$)[a-z0-9][a-z0-9-]*[a-z0-9]-[1-9][0-9]{4,12}$"
)


class ObjectStorageError(RuntimeError):
    pass


class ObjectNotFoundError(ObjectStorageError):
    pass


def validate_tencent_cos_configuration(
    *,
    endpoint_url: str | None,
    bucket: str | None,
    region: str | None,
    addressing_style: str,
    server_side_encryption: str,
) -> str:
    """Validate the Hong Kong COS SDK endpoint and return the request host.

    Tencent COS expects a bucket-free regional SDK endpoint. Botocore adds the
    ``bucketname-appid`` label exactly once when virtual addressing is used.
    """

    if not endpoint_url or not bucket or not region:
        raise ObjectStorageError("腾讯云 COS 配置不完整")
    try:
        parsed = urlsplit(endpoint_url)
        port = parsed.port
    except ValueError as exc:
        raise ObjectStorageError("腾讯云 COS endpoint 无效") from exc
    if (
        endpoint_url != _TENCENT_COS_ENDPOINT
        or parsed.scheme != "https"
        or parsed.hostname != "cos.ap-hongkong.myqcloud.com"
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise ObjectStorageError("腾讯云 COS endpoint 必须为香港 regional service host")
    if region != _TENCENT_COS_REGION:
        raise ObjectStorageError("腾讯云 COS region 必须为 ap-hongkong")
    if addressing_style != "virtual":
        raise ObjectStorageError("腾讯云 COS 必须使用 virtual addressing")
    if server_side_encryption != "AES256":
        raise ObjectStorageError("腾讯云 COS 必须使用 AES256 服务端加密")
    if not _TENCENT_COS_BUCKET.fullmatch(bucket):
        raise ObjectStorageError("腾讯云 COS bucket 必须使用 bucketname-appid 格式")
    final_host = f"{bucket}.{parsed.hostname}"
    if final_host.count(bucket) != 1:
        raise ObjectStorageError("腾讯云 COS 最终请求 Host 中 bucket 出现次数无效")
    return final_host


class PrivateObjectStore(Protocol):
    backend_name: str

    def put_bytes(self, object_key: str, payload: bytes, content_type: str) -> None:
        ...

    def get_bytes(self, object_key: str, *, max_bytes: int) -> bytes:
        ...

    def delete(self, object_key: str) -> None:
        ...


def _validate_object_key(object_key: str) -> str:
    normalized = object_key.replace("\\", "/").strip("/")
    if (
        not normalized
        or normalized != object_key.replace("\\", "/")
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ObjectStorageError("对象键无效")
    return normalized


def _validate_payload(payload: bytes, content_type: str) -> None:
    if content_type not in _ALLOWED_PRIVATE_CONTENT_TYPES:
        raise ObjectStorageError("私有对象 MIME 类型无效")
    if not payload:
        raise ObjectStorageError("私有对象内容为空")
    if len(payload) > settings.OBJECT_STORAGE_MAX_READ_BYTES:
        raise ObjectStorageError("私有对象超过存储读取上限")


def _validate_read_limit(max_bytes: int) -> int:
    if max_bytes <= 0 or max_bytes > settings.OBJECT_STORAGE_MAX_READ_BYTES:
        raise ObjectStorageError("私有对象读取预算无效")
    return max_bytes


def _read_bounded_stream(stream, *, max_bytes: int) -> bytes:
    """Read an untrusted stream without ever accepting more than max_bytes."""

    chunks: list[bytes] = []
    total = 0
    while True:
        remaining_with_sentinel = max_bytes - total + 1
        block = stream.read(min(_READ_CHUNK_BYTES, remaining_with_sentinel))
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise ObjectStorageError("私有对象超过声明大小")
        chunks.append(block)
    return b"".join(chunks)


class LocalPrivateObjectStore:
    backend_name = "local"

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        normalized = _validate_object_key(object_key)
        target = (self.root / normalized).resolve()
        if target == self.root or self.root not in target.parents:
            raise ObjectStorageError("对象路径越界")
        return target

    def put_bytes(self, object_key: str, payload: bytes, content_type: str) -> None:
        _validate_payload(payload, content_type)
        target = self._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".upload-",
                dir=target.parent,
                delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        except Exception as exc:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise ObjectStorageError("私有对象写入失败") from exc

    def get_bytes(self, object_key: str, *, max_bytes: int) -> bytes:
        limit = _validate_read_limit(max_bytes)
        target = self._path(object_key)
        try:
            if target.stat().st_size > limit:
                raise ObjectStorageError("私有对象超过声明大小")
            with target.open("rb") as handle:
                return _read_bounded_stream(handle, max_bytes=limit)
        except FileNotFoundError as exc:
            raise ObjectNotFoundError("私有对象不存在") from exc
        except ObjectStorageError:
            raise
        except OSError as exc:
            raise ObjectStorageError("私有对象读取失败") from exc

    def delete(self, object_key: str) -> None:
        try:
            self._path(object_key).unlink(missing_ok=True)
        except OSError as exc:
            raise ObjectStorageError("私有对象删除失败") from exc


class S3PrivateObjectStore:
    """S3 兼容私有桶适配器；不生成桶级公开 URL。"""

    backend_name = "s3"

    def __init__(self) -> None:
        if not settings.S3_BUCKET:
            raise ObjectStorageError("S3_BUCKET 未配置")
        if not settings.S3_ACCESS_KEY_ID or not settings.S3_SECRET_ACCESS_KEY:
            raise ObjectStorageError("S3 私有凭证未配置")
        if settings.S3_PROVIDER == "tencent_cos":
            validate_tencent_cos_configuration(
                endpoint_url=settings.S3_ENDPOINT_URL,
                bucket=settings.S3_BUCKET,
                region=settings.S3_REGION,
                addressing_style=settings.S3_ADDRESSING_STYLE,
                server_side_encryption=settings.S3_SERVER_SIDE_ENCRYPTION,
            )
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as exc:  # pragma: no cover - 依赖缺失仅在部署配置出现
            raise ObjectStorageError("S3 适配依赖未安装") from exc
        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=BotoConfig(
                s3={"addressing_style": settings.S3_ADDRESSING_STYLE}
            ),
        )

    def put_bytes(self, object_key: str, payload: bytes, content_type: str) -> None:
        key = _validate_object_key(object_key)
        _validate_payload(payload, content_type)
        request = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": payload,
            "ContentType": content_type,
        }
        if settings.S3_SERVER_SIDE_ENCRYPTION == "AES256":
            request["ServerSideEncryption"] = "AES256"
        try:
            self.client.put_object(**request)
        except Exception as exc:  # noqa: BLE001 - SDK 异常类型随供应商变化
            raise ObjectStorageError("S3 私有对象写入失败") from exc

    def get_bytes(self, object_key: str, *, max_bytes: int) -> bytes:
        key = _validate_object_key(object_key)
        limit = _validate_read_limit(max_bytes)
        body = None
        payload: bytes | None = None
        read_error: ObjectStorageError | None = None
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            if not isinstance(response, dict):
                raise ObjectStorageError("S3 私有对象响应无效")
            if "Body" not in response or response["Body"] is None:
                raise ObjectStorageError("S3 私有对象响应缺少内容流")
            body = response["Body"]
            content_length = response.get("ContentLength")
            if (
                isinstance(content_length, bool)
                or not isinstance(content_length, int)
                or content_length < 0
            ):
                raise ObjectStorageError("S3 私有对象声明大小无效")
            if content_length > limit:
                raise ObjectStorageError("私有对象超过声明大小")
            payload = _read_bounded_stream(body, max_bytes=limit)
        except ObjectStorageError as exc:
            read_error = exc
        except Exception as exc:  # noqa: BLE001
            read_error = ObjectStorageError("S3 私有对象读取失败")
            read_error.__cause__ = exc
        finally:
            if body is not None:
                try:
                    body.close()
                except Exception as exc:  # noqa: BLE001
                    if read_error is None:
                        read_error = ObjectStorageError("S3 私有对象关闭失败")
                        read_error.__cause__ = exc
        if read_error is not None:
            raise read_error
        if payload is None:
            raise ObjectStorageError("S3 私有对象读取失败")
        return payload

    def delete(self, object_key: str) -> None:
        key = _validate_object_key(object_key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise ObjectStorageError("S3 私有对象删除失败") from exc


@lru_cache
def get_object_store() -> PrivateObjectStore:
    return get_object_store_for_backend(settings.OBJECT_STORE_BACKEND)


@lru_cache
def get_object_store_for_backend(backend: str) -> PrivateObjectStore:
    if backend == "s3":
        return S3PrivateObjectStore()
    if backend == "local":
        return LocalPrivateObjectStore(settings.object_storage_local_root)
    raise ObjectStorageError("未知对象存储后端")
