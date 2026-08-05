"""A6 私有生成产物、下载授权与显式确认 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ResumeProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=2000)


class ResumeArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_name: str = Field(min_length=1, max_length=80)
    dept: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=50)
    education: str = Field(default="", max_length=500)
    research_interests: list[str] = Field(default_factory=list, max_length=12)
    projects: list[ResumeProject] = Field(default_factory=list, max_length=20)
    awards: list[str] = Field(default_factory=list, max_length=30)
    positions: list[str] = Field(default_factory=list, max_length=30)
    target_advisor: str | None = Field(default=None, max_length=100)
    format: Literal["pdf", "docx"] = "pdf"
    confirm_generation: StrictBool


class MatchReportArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)
    format: Literal["pdf", "docx"] = "pdf"
    confirm_generation: StrictBool


class DownloadGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_private_download: StrictBool


class ArtifactItem(BaseModel):
    document_id: str
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    document_kind: str
    scan_status: str
    scan_scope: Literal["full_antivirus", "structural_signature_only"]
    scan_checked_at: datetime | None
    text_preview: str
    created_at: datetime | None


class DownloadGrantItem(BaseModel):
    download_url: str
    expires_at: datetime
    audience: Literal["web_private"]
