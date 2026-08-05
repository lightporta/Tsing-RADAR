"""扫描适配器骨架（v2.2 新增）。

对应 Annotation 1 门禁「真实 ClamAV 可用性及失败关闭探测」。
当前仅提供 BuiltinScanner：做扩展名/MIME/magic/危险结构检查——
这明确**不是病毒扫描**，与文档表述一致。

真实 ClamAV 适配器（ClamAVScanner）为占位骨架，需要授权连接真实扫描服务，
属于未关闭门禁。失败关闭原则：扫描不可用、超时或失败时，对象状态必须保持
pending/quarantined，不得进入 clean。
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

from app.core.config import settings

# 危险扩展名：禁止上传
_BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".sh", ".com", ".scr", ".msi", ".dll", ".js", ".vbs"}
# 允许的扩展名白名单（对应简历/报告场景）
_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# 最小 magic 校验（按文件头）
_MAGIC = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "docx/zip",  # docx 本质是 zip
}


class ScanResult:
    """扫描结果。is_clean=True 才允许进入 clean 状态。"""

    def __init__(self, is_clean: bool, reason: str = "") -> None:
        self.is_clean = is_clean
        self.reason = reason

    def __repr__(self) -> str:
        return f"ScanResult(is_clean={self.is_clean}, reason={self.reason!r})"


class ScannerBackend(Protocol):
    """扫描后端协议。"""

    def scan(self, path: str, *, filename: str, mime: str) -> ScanResult:
        ...


class BuiltinScanner:
    """内置结构检查扫描器（非病毒扫描）。

    检查项：
    1. 扩展名白名单；
    2. 扩展名不在危险黑名单；
    3. magic 头与扩展名一致性（近似）；
    4. 文件非空且未超过 MAX_UPLOAD_BYTES。

    任一失败 → is_clean=False（对象保持不可下载）。
    """

    name = "builtin"

    def scan(self, path: str, *, filename: str, mime: str) -> ScanResult:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            return ScanResult(False, f"扩展名不在白名单：{ext}")
        if ext in _BLOCKED_EXTENSIONS:
            return ScanResult(False, f"危险扩展名：{ext}")

        try:
            size = os.path.getsize(path)
        except OSError as exc:
            return ScanResult(False, f"无法读取文件大小：{exc}")
        if size <= 0:
            return ScanResult(False, "文件为空")
        if size > settings.MAX_UPLOAD_BYTES:
            return ScanResult(False, f"超过上传上限 {settings.MAX_UPLOAD_BYTES} 字节")

        with open(path, "rb") as f:
            head = f.read(8)
        matched = any(head.startswith(magic) for magic in _MAGIC)
        if not matched and ext in {".pdf", ".docx"}:
            return ScanResult(False, f"magic 头与扩展名 {ext} 不一致")

        return ScanResult(True, "builtin 结构检查通过")


class ClamAVScanner:
    """真实 ClamAV 适配器占位（需授权连接真实扫描服务）。

    生产期应连接真实 ClamAV daemon（INSTREAM 或本地 socket），并对标准测试
    病毒样本（如 EICAR）做端到端验证。当前实现一律返回「不可用」，保证失败关闭：
    对象保持 pending/quarantined，不得进入 clean。
    """

    name = "clamav"

    def scan(self, path: str, *, filename: str, mime: str) -> ScanResult:
        # 未授权连接真实服务，按失败关闭处理
        return ScanResult(False, "真实 ClamAV 未配置（未授权连接），按失败关闭")


_scanner: Optional[ScannerBackend] = None


def get_scanner() -> ScannerBackend:
    """获取扫描后端（默认 builtin；生产可切 clamav，需真实服务）。"""
    global _scanner
    if _scanner is None:
        # 当前始终返回 builtin；真实 ClamAV 需授权后在此切换
        _scanner = BuiltinScanner()
    return _scanner
