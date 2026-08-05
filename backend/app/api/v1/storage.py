"""对象存储路由（v2.2 新增）。

对应 Annotation 1 门禁「真实私有 S3 读写…」「对象读取硬上限」「一次性 Web 下载授权」
「真实 ClamAV 可用性及失败关闭探测」的离线实现。

提供三条路由：
- POST /api/storage/upload：鉴权 + 暂存 + BoundedReader + builtin 扫描 + 落存储 + 落库；
- GET  /api/storage/download：签名令牌校验 + BoundedReader + Cache-Control: no-store +
  对象级授权 + scan_status 必须 clean；
- DELETE /api/storage/objects/{object_id}：所有者删除。

失败关闭：扫描失败/不可用时，scan_status 保持 pending/quarantined，对象不可下载。
真实 S3 与真实 ClamAV 属于未关闭门禁，需用户单独授权。
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_student
from app.db.session import SessionLocal
from app.models.storage_object import StorageObject
from app.services.scanner import get_scanner
from app.services.security import BoundedReader
from app.services.signing import InvalidToken, issue_download_token, verify_download_token
from app.services.storage import get_storage
from app.core.config import settings

router = APIRouter()


def _persist(obj: StorageObject) -> None:
    db = SessionLocal()
    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
    finally:
        db.close()


def _get_owned_object(object_id: str, owner_subject: str) -> StorageObject:
    db = SessionLocal()
    try:
        obj = db.query(StorageObject).filter_by(object_id=object_id).first()
        if obj is None:
            raise HTTPException(status_code=404, detail="对象不存在")
        if obj.owner_subject != owner_subject:
            raise HTTPException(status_code=403, detail="无权访问该对象")
        return obj
    finally:
        db.close()


@router.post("/storage/upload")
async def upload(
    file: UploadFile = File(...),
    owner_subject: str = Depends(get_current_student),
):
    """上传私有文件（PDF/DOCX/TXT/MD），返回 object_id 与一次性下载令牌。

    流程：暂存到临时文件 → BuiltinScanner 结构检查 → LocalStorageBackend 落盘
    （写入时再用 BoundedReader 强制上限）→ 落库 scan_status=clean（仅当扫描通过）。
    扫描失败 → scan_status=quarantined，对象不可下载。
    """
    # 1) 暂存到临时文件（带 BoundedReader 防止一次性读入内存）
    suffix = os.path.splitext(file.filename or "")[1]
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    consumed = 0
    try:
        with os.fdopen(tmp_fd, "wb") as out:
            reader = BoundedReader(file.file, max_bytes=settings.MAX_UPLOAD_BYTES)
            try:
                for chunk in reader.read_chunks():
                    out.write(chunk)
                    consumed += len(chunk)
            except ValueError as exc:
                out.close()
                # 超限：对象不上传、不入库（失败关闭）
                raise HTTPException(status_code=413, detail=str(exc))

        # 2) builtin 结构检查（非病毒扫描）
        result = get_scanner().scan(tmp_path, filename=file.filename or "", mime=file.content_type or "")
        if not result.is_clean:
            # 扫描失败：不落存储，记录 quarantined 元数据以便审计
            obj = StorageObject(
                owner_subject=owner_subject,
                bucket=settings.STORAGE_BUCKET,
                object_key="(rejected)",
                original_filename=file.filename or "",
                declared_size=str(consumed),
                mime=file.content_type or "",
                scan_status="quarantined",
            )
            _persist(obj)
            raise HTTPException(status_code=422, detail=f"扫描未通过：{result.reason}")

        # 3) 落存储（LocalStorageBackend.put 内部再用 BoundedReader 上限）
        object_key, size = get_storage().put(tmp_path, mime=file.content_type or "")
        obj = StorageObject(
            owner_subject=owner_subject,
            bucket=settings.STORAGE_BUCKET,
            object_key=object_key,
            original_filename=file.filename or "",
            declared_size=str(size),
            mime=file.content_type or "",
            scan_status="clean",
        )
        _persist(obj)

        token = issue_download_token(obj.object_id)
        return {
            "object_id": obj.object_id,
            "size": size,
            "scan_status": "clean",
            "download_token": token,
            "download_url": f"/api/storage/download?token={token}",
        }
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.get("/storage/download")
def download(token: str, owner_subject: str = Depends(get_current_student)):
    """凭一次性签名令牌下载对象。

    校验：令牌有效且未过期 → object_id 匹配 → 对象存在且归属当前主体 →
    scan_status 必须为 clean（失败关闭）→ BoundedReader 强制 MAX_DOWNLOAD_BYTES。
    响应头注入 Cache-Control: no-store，防止代理/浏览器缓存下载内容。
    """
    try:
        # 先从令牌解出 object_id，再做归属校验
        tok_obj = token.split(".")[0]
    except Exception:
        raise HTTPException(status_code=400, detail="令牌格式错误")

    obj = _get_owned_object(tok_obj, owner_subject)

    try:
        verify_download_token(token, obj.object_id)
    except InvalidToken as exc:
        raise HTTPException(status_code=403, detail=f"下载令牌无效：{exc}")

    if obj.scan_status != "clean":
        raise HTTPException(status_code=403, detail=f"对象不可下载（scan_status={obj.scan_status}）")

    meta = get_storage().open(obj.object_key)

    def iter_bounded():
        with open(meta.path, "rb") as f:
            reader = BoundedReader(f, max_bytes=settings.MAX_DOWNLOAD_BYTES)
            try:
                for chunk in reader.read_chunks():
                    yield chunk
            except ValueError:
                # 超过声明大小或硬上限：中止并审计
                return

    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    return StreamingResponse(
        iter_bounded(),
        media_type=meta.mime or "application/octet-stream",
        headers=headers,
    )


@router.delete("/storage/objects/{object_id}")
def delete_object(object_id: str, owner_subject: str = Depends(get_current_student)):
    """对象所有者删除对象（存储 + 元数据）。"""
    obj = _get_owned_object(object_id, owner_subject)

    db = SessionLocal()
    try:
        # 先删存储对象，再删元数据；存储删除失败时保留元数据以便重试
        if obj.object_key and obj.object_key != "(rejected)":
            try:
                get_storage().delete(obj.object_key)
            except FileNotFoundError:
                pass
        db.delete(db.merge(obj))
        db.commit()
    finally:
        db.close()
    return {"object_id": object_id, "status": "deleted"}
