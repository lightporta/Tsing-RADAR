"""A5 私有文档与站内投递模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, StrictBool


class DocumentItem(BaseModel):
    document_id: str
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    document_kind: str
    scan_status: str
    scan_scope: str
    scan_checked_at: datetime | None
    text_preview: str
    created_at: datetime | None


class ApplicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruit_id: str
    document_id: str
    confirm_in_app_only: StrictBool


class DocumentDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_delete: StrictBool


class ApplicationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class ApplicationItem(BaseModel):
    app_id: str
    recruit_id: str
    document_id: str | None
    status: str
    delivery: str
    created_at: datetime | None
    updated_at: datetime | None
