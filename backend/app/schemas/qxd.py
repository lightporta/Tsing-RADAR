"""清小搭 OpenAI-compatible 请求、响应扩展与附件 Schema。"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


class StrictPayload(BaseModel):
    """多模态 payload 禁止未知字段，避免误收 base64 等未支持载荷。"""

    model_config = ConfigDict(extra="forbid")


class TextContentPart(StrictPayload):
    type: Literal["text"]
    text: str


class ImageURLPayload(StrictPayload):
    url: str


class ImageURLContentPart(StrictPayload):
    type: Literal["image_url"]
    image_url: ImageURLPayload


class InputAudioPayload(StrictPayload):
    url: str
    format: Literal["wav", "mp3", "m4a", "webm"]


class InputAudioContentPart(StrictPayload):
    type: Literal["input_audio"]
    input_audio: InputAudioPayload


class FilePayload(StrictPayload):
    url: str | None = None
    file_id: str | None = None
    filename: str

    @model_validator(mode="after")
    def validate_source(self) -> "FilePayload":
        if bool(self.url) == bool(self.file_id):
            raise ValueError("file.url 与 file.file_id 必须且只能提供一个")
        return self


class FileContentPart(StrictPayload):
    type: Literal["file"]
    file: FilePayload


ContentPart = Annotated[
    TextContentPart
    | ImageURLContentPart
    | InputAudioContentPart
    | FileContentPart,
    Field(discriminator="type"),
]


class QXDMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart]


class QXDChatRequest(BaseModel):
    """兼容常见 OpenAI 请求扩展，但对关键字段执行严格校验。"""

    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    messages: list[QXDMessage] = Field(min_length=1)
    stream: StrictBool = False
    max_tokens: int | None = Field(default=None, ge=1)
    user: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_user_message(self) -> "QXDChatRequest":
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("messages 至少需要一条 user 消息")
        return self


AttachmentType = Literal[
    "image",
    "audio",
    "video",
    "pdf",
    "word",
    "excel",
    "ppt",
    "text",
    "archive",
    "file",
]


def _validate_public_http_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("必须是绝对 HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("URL 不得包含用户凭证")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("URL 不得指向本地主机")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return value
    if not address.is_global:
        raise ValueError("URL 不得指向非公网 IP")
    return value


class SodaAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fileUrl: str
    fileName: str = Field(min_length=1)
    fileType: AttachmentType
    mimeType: str = Field(min_length=1)
    fileSize: int | None = Field(default=None, ge=0)
    previewUrl: str | None = None
    expiresAt: datetime | None = None

    @field_validator("fileUrl")
    @classmethod
    def validate_file_url(cls, value: str) -> str:
        return _validate_public_http_url(value)

    @field_validator("previewUrl")
    @classmethod
    def validate_preview_url(cls, value: str | None) -> str | None:
        return _validate_public_http_url(value) if value is not None else None

    @model_validator(mode="after")
    def validate_type_matches_mime(self) -> "SodaAttachment":
        mime = self.mimeType.lower()
        checks = {
            "image": mime.startswith("image/"),
            "audio": mime.startswith("audio/"),
            "video": mime.startswith("video/"),
            "pdf": mime == "application/pdf",
            "word": mime
            in {
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
            "excel": mime
            in {
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            "ppt": mime
            in {
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            },
            "text": mime.startswith("text/"),
            "archive": mime
            in {
                "application/zip",
                "application/x-rar-compressed",
                "application/vnd.rar",
                "application/x-7z-compressed",
            },
            "file": True,
        }
        if not checks[self.fileType]:
            raise ValueError("fileType 与 mimeType 不一致")
        return self


class SodaExtension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachments: list[SodaAttachment] = Field(min_length=1)
