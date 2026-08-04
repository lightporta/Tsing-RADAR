"""D1 清华官方招生目录的本地证据数据模型。

这些模型描述目录事实和来源，不表示实际名额、必然招生或推荐质量。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
ENTITY_ID_PATTERN = r"^[a-z_]+_[0-9a-f]{24}$"
ALLOWED_SOURCE_HOSTS = {
    "yz.tsinghua.edu.cn",
    "yzbm.tsinghua.edu.cn",
}


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必须包含时区")
    return value


def _require_official_url(value: str, field_name: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_SOURCE_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{field_name} 必须是清华官方 HTTPS URL")
    return value


class CatalogType(str, Enum):
    DOCTORAL_REGULAR = "doctoral_regular"
    DOCTORAL_RECOMMENDATION_EXEMPT = "doctoral_recommendation_exempt"


class AdvisorEntityType(str, Enum):
    PERSON = "person"
    ADVISOR_GROUP = "advisor_group"


class RemarkScope(str, Enum):
    SNAPSHOT = "snapshot"
    PROGRAM = "program"
    RESEARCH_DIRECTION = "research_direction"
    OFFERING = "offering"


class CatalogFieldEvidence(BaseModel):
    """单个规范化事实字段对应的公开来源证据。"""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["public_fact"] = "public_fact"
    source_url: str
    captured_at: datetime
    page_content_sha256: str = Field(pattern=SHA256_PATTERN)
    fragment_sha256: str = Field(pattern=SHA256_PATTERN)
    raw_text: str = Field(min_length=1)
    normalized_value: str | list[str]

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_official(cls, value: str) -> str:
        return _require_official_url(value, "source_url")

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "captured_at")


class CatalogSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    catalog_type: CatalogType
    academic_year: Literal[2027] = 2027
    source_entry_url: str
    catalog_url: str
    source_link_title: str = Field(min_length=1)
    captured_at: datetime
    page_content_sha256: dict[str, str]
    department_ids: list[str]
    disclaimer_remark_ids: list[str] = Field(default_factory=list)
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_entry_url", "catalog_url")
    @classmethod
    def urls_must_be_official(cls, value: str, info) -> str:
        return _require_official_url(value, info.field_name)

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "captured_at")

    @field_validator("page_content_sha256")
    @classmethod
    def page_hashes_must_be_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        invalid = [key for key, digest in value.items() if not re.fullmatch(SHA256_PATTERN, digest)]
        if invalid:
            raise ValueError(f"页面哈希无效: {invalid}")
        return value

    @model_validator(mode="after")
    def require_field_provenance(self) -> "CatalogSnapshot":
        required = {
            "snapshot_id",
            "catalog_type",
            "academic_year",
            "catalog_url",
            "source_link_title",
        }
        missing = required - set(self.provenance)
        if missing:
            raise ValueError(f"snapshot 字段缺少 provenance: {sorted(missing)}")
        return self


class Department(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: str = Field(pattern=ENTITY_ID_PATTERN)
    snapshot_id: str
    code: str = Field(pattern=r"^\d{3}$")
    name: str = Field(min_length=1)
    source_url: str
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_official(cls, value: str) -> str:
        return _require_official_url(value, "source_url")

    @model_validator(mode="after")
    def require_field_provenance(self) -> "Department":
        missing = {"code", "name"} - set(self.provenance)
        if missing:
            raise ValueError(f"department 字段缺少 provenance: {sorted(missing)}")
        return self


class Program(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(pattern=ENTITY_ID_PATTERN)
    snapshot_id: str
    department_id: str
    code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    degree_category: Literal["academic", "professional"]
    name: str = Field(min_length=1)
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_field_provenance(self) -> "Program":
        missing = {"code", "degree_category", "name"} - set(self.provenance)
        if missing:
            raise ValueError(f"program 字段缺少 provenance: {sorted(missing)}")
        return self


class ResearchDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction_id: str = Field(pattern=ENTITY_ID_PATTERN)
    snapshot_id: str
    program_id: str
    code: str = Field(pattern=r"^\d{2}$")
    study_mode: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_field_provenance(self) -> "ResearchDirection":
        missing = {"code", "study_mode", "name"} - set(self.provenance)
        if missing:
            raise ValueError(
                f"research_direction 字段缺少 provenance: {sorted(missing)}"
            )
        return self


class AdvisorOrGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisor_or_group_id: str = Field(pattern=ENTITY_ID_PATTERN)
    snapshot_id: str
    department_id: str
    entity_type: AdvisorEntityType
    source_label: str = Field(min_length=1)
    identity_scope: Literal["snapshot_department_source_label"] = (
        "snapshot_department_source_label"
    )
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_field_provenance(self) -> "AdvisorOrGroup":
        missing = {"entity_type", "source_label"} - set(self.provenance)
        if missing:
            raise ValueError(
                f"advisor_or_group 字段缺少 provenance: {sorted(missing)}"
            )
        return self


class Offering(BaseModel):
    """目录中的方向—导师/导师组关系；不表示真实名额或招生承诺。"""

    model_config = ConfigDict(extra="forbid")

    offering_id: str = Field(pattern=ENTITY_ID_PATTERN)
    snapshot_id: str
    direction_id: str
    advisor_or_group_id: str | None = None
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_relation_provenance(self) -> "Offering":
        if "relation" not in self.provenance:
            raise ValueError("offering 缺少 relation provenance")
        return self


class AdmissionRemark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remark_id: str = Field(pattern=ENTITY_ID_PATTERN)
    snapshot_id: str
    scope: RemarkScope
    target_id: str
    text: str = Field(min_length=1)
    explicit_tags: list[
        Literal[
            "recommendation_exempt_only",
            "no_direct_phd",
        ]
    ] = Field(default_factory=list)
    provenance: dict[str, CatalogFieldEvidence]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_remark_provenance(self) -> "AdmissionRemark":
        missing = {"text", "explicit_tags"} - set(self.provenance)
        if missing:
            raise ValueError(f"remark 字段缺少 provenance: {sorted(missing)}")
        return self


class CatalogCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discovered_departments: dict[str, int]
    parsed_departments: dict[str, int]
    empty_departments: dict[str, int]
    programs_without_directions: dict[str, int]
    directions_without_advisors: dict[str, int]
    offerings_without_advisor: dict[str, int]


class CatalogDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    source_entry_url: str
    snapshots: list[CatalogSnapshot]
    departments: list[Department]
    programs: list[Program]
    research_directions: list[ResearchDirection]
    advisors_or_groups: list[AdvisorOrGroup]
    offerings: list[Offering]
    remarks: list[AdmissionRemark]
    coverage: CatalogCoverage
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "generated_at")

    @field_validator("source_entry_url")
    @classmethod
    def source_entry_url_must_be_official(cls, value: str) -> str:
        return _require_official_url(value, "source_entry_url")
