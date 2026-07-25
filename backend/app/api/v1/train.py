"""训练触发路由（管理员）。"""

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.train import TrainTriggerRequest
from app.services.training import train

router = APIRouter()


@router.post("/train/trigger")
def train_trigger(req: TrainTriggerRequest):
    """触发模型训练（管理员）：聚合反馈与问卷样本，训练线性 stub，输出训练日志。"""
    if req.admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="admin_token 无效")
    return train()
