"""简历相关 Pydantic 模型。"""

from typing import Any, Optional

from pydantic import BaseModel


class ResumeGenerateRequest(BaseModel):
    student_name: str
    dept: str
    email: str
    phone: str
    projects: list[Any] = []
    awards: list[Any] = []
    positions: list[Any] = []
    target_advisor: Optional[str] = None


class ResumeSubmitRequest(BaseModel):
    recruit_id: str
    student_id: str
    resume_id: str
