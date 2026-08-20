"""A5 私有文档与站内投递模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


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


DocumentFactField = Literal[
    "name",
    "email",
    "phone",
    "dept",
    "grade",
    "gpa",
    "research_interest",
    "research_experience",
    "interest_tags",
    "awards",
    "positions",
]


class DocumentLocalAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_private_parse: StrictBool


class DocumentParsedFact(BaseModel):
    field: DocumentFactField
    label: str
    value: str | list[str]
    source_excerpt: str


class DocumentLocalAnalysisResponse(BaseModel):
    document_id: str
    facts: list[DocumentParsedFact]
    retention: Literal["not_stored"]
    external_model_called: Literal[False]


class DocumentSelectedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: DocumentFactField
    selected_text: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def trim_selected_text(self):
        self.selected_text = self.selected_text.strip()
        if not self.selected_text:
            raise ValueError("选定文本不能为空")
        return self


class DocumentInterpretationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_single_use: StrictBool
    selections: list[DocumentSelectedText] = Field(min_length=1, max_length=11)

    @model_validator(mode="after")
    def enforce_selection_budget(self):
        if len({item.field for item in self.selections}) != len(self.selections):
            raise ValueError("同一字段只能选择一次")
        if sum(len(item.selected_text) for item in self.selections) > 6000:
            raise ValueError("选定文本总长度不能超过 6000 字")
        return self


class DocumentInterpretationResponse(BaseModel):
    interpretation: str
    provider: Literal["glm"]
    retention: Literal["not_stored"]
