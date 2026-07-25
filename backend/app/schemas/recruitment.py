"""招募相关 Pydantic 模型。"""

from pydantic import BaseModel


class RecruitmentCreateRequest(BaseModel):
    publisher_id: str
    type: str
    title: str
    req: str
    major: str
    deadline: str
    is_urgent: bool = False


class RecruitmentItem(BaseModel):
    recruit_id: str
    publisher_name: str
    publisher_type: str
    type: str
    title: str
    req: str
    major: str
    deadline: str
    is_urgent: bool
    dept: str
