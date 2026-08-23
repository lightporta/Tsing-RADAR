"""真实私有简历生成与兼容站内投递模型。"""

from pydantic import BaseModel, ConfigDict, StrictBool

from app.schemas.artifacts import ResumeArtifactRequest

ResumeGenerateRequest = ResumeArtifactRequest


class ResumeSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruit_id: str
    document_id: str
    confirm_in_app_only: StrictBool
