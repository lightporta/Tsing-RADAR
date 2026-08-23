"""A6 上传/生成文件扫描。

``builtin`` 只提供结构与已知危险特征检查；生产模式必须使用 ClamAV。
"""

from __future__ import annotations

import re
import socket
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

from app.core.config import settings

_EICAR_MARKER = (
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
    b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)
_PDF_ACTIVE_MARKERS = (
    b"/javascript",
    b"/launch",
    b"/richmedia",
)
_DOCX_FORBIDDEN_NAMES = (
    "vbaproject.bin",
    "word/embeddings/",
    "word/activex/",
)


class UnsafeContentError(ValueError):
    pass


class ScanUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanResult:
    status: str
    method: str
    checked_at: datetime


def _builtin_policy_scan(payload: bytes, extension: str) -> None:
    lowered = payload.lower()
    if _EICAR_MARKER.lower() in lowered:
        raise UnsafeContentError("文件命中反病毒测试特征")
    if extension == ".pdf" and any(marker in lowered for marker in _PDF_ACTIVE_MARKERS):
        raise UnsafeContentError("PDF 包含未允许的主动内容")
    if extension == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                names = [name.lower() for name in archive.namelist()]
        except zipfile.BadZipFile as exc:
            raise UnsafeContentError("DOCX 容器损坏") from exc
        if any(
            name == forbidden or name.startswith(forbidden)
            for name in names
            for forbidden in _DOCX_FORBIDDEN_NAMES
        ):
            raise UnsafeContentError("DOCX 包含宏、嵌入对象或 ActiveX 内容")


def _clamav_scan(payload: bytes) -> None:
    if not settings.CLAMAV_HOST:
        raise ScanUnavailableError("ClamAV 未配置")
    try:
        with socket.create_connection(
            (settings.CLAMAV_HOST, settings.CLAMAV_PORT),
            timeout=settings.CLAMAV_TIMEOUT_SECONDS,
        ) as connection:
            connection.settimeout(settings.CLAMAV_TIMEOUT_SECONDS)
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(payload), 1024 * 1024):
                chunk = payload[offset : offset + 1024 * 1024]
                connection.sendall(struct.pack(">I", len(chunk)))
                connection.sendall(chunk)
            connection.sendall(struct.pack(">I", 0))
            response = bytearray()
            while b"\0" not in response and len(response) < 4096:
                block = connection.recv(4096)
                if not block:
                    break
                response.extend(block)
    except (OSError, TimeoutError) as exc:
        raise ScanUnavailableError("ClamAV 扫描服务不可用") from exc

    result = bytes(response).split(b"\0", 1)[0].decode("utf-8", "replace")
    if result.endswith(" OK"):
        return
    if re.search(r"\sFOUND$", result):
        raise UnsafeContentError("文件未通过反病毒扫描")
    raise ScanUnavailableError("ClamAV 返回无法识别的扫描结果")


def scan_payload(payload: bytes, extension: str) -> ScanResult:
    _builtin_policy_scan(payload, extension)
    if settings.FILE_SCAN_MODE == "clamav":
        _clamav_scan(payload)
        method = "clamav-instream-plus-structural-v1"
    else:
        method = "builtin-structural-signature-v1-not-full-antivirus"
    return ScanResult(
        status="clean",
        method=method,
        checked_at=datetime.now(timezone.utc),
    )
