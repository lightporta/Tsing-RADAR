"""训练触发 Pydantic 模型。"""

from pydantic import BaseModel


class TrainTriggerRequest(BaseModel):
    admin_token: str
