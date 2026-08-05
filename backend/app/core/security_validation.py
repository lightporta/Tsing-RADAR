"""生产安全配置校验；错误只包含字段名，不记录密钥材料。"""

from __future__ import annotations

import base64
import binascii
import hmac

from app.core.config import Settings

_PLACEHOLDERS = {
    "local-development-only-change-me",
    "local-artifact-signing-change-me",
    "change-me",
    "changeme",
    "secret",
    "admin",
    "local-admin-only-change-me",
}


def decode_secret_material(name: str, value: str | None) -> bytes:
    if value is None or not value or value != value.strip() or any(
        character.isspace() for character in value
    ):
        raise RuntimeError(f"生产模式必须配置非空白 {name}")
    if value.lower() in _PLACEHOLDERS:
        raise RuntimeError(f"生产模式不得使用占位 {name}")
    try:
        if value.startswith("base64:"):
            material = base64.b64decode(
                value.removeprefix("base64:"),
                altchars=b"-_",
                validate=True,
            )
        elif value.startswith("hex:"):
            material = bytes.fromhex(value.removeprefix("hex:"))
        else:
            # 普通 Unicode 密钥明确按 UTF-8 字节计算，不按字符数计算。
            material = value.encode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise RuntimeError(f"{name} 编码无效") from exc
    if len(material) < 32:
        raise RuntimeError(f"{name} 解码后至少需要 32 字节")
    return material


def validate_production_secrets(app_settings: Settings) -> None:
    if getattr(app_settings, "QXD_TRIAL_SINGLE_USER_MODE", False):
        raise RuntimeError("生产模式不得启用清小搭单人试聊兼容模式")
    materials = {
        "ADMIN_TOKEN": decode_secret_material(
            "ADMIN_TOKEN",
            app_settings.ADMIN_TOKEN,
        ),
        "SESSION_HMAC_SECRET": decode_secret_material(
            "SESSION_HMAC_SECRET",
            app_settings.SESSION_HMAC_SECRET,
        ),
        "ARTIFACT_SIGNING_SECRET": decode_secret_material(
            "ARTIFACT_SIGNING_SECRET",
            app_settings.ARTIFACT_SIGNING_SECRET,
        ),
    }
    if app_settings.QXD_API_KEY or app_settings.QXD_END_USER_SIGNING_SECRET:
        materials["QXD_API_KEY"] = decode_secret_material(
            "QXD_API_KEY",
            app_settings.QXD_API_KEY,
        )
        materials["QXD_END_USER_SIGNING_SECRET"] = decode_secret_material(
            "QXD_END_USER_SIGNING_SECRET",
            app_settings.QXD_END_USER_SIGNING_SECRET,
        )
    names = list(materials)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if hmac.compare_digest(materials[left], materials[right]):
                raise RuntimeError(f"{left} 与 {right} 必须使用不同密钥")
