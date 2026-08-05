"""[PATCH] 训练触发路由（管理员）。

修改点：
- admin_token 从请求体字段改为 X-Admin-Token Header（使用 Depends(verify_admin)）
- 请求体仅保留训练参数
"""

from fastapi import APIRouter, Depends

from app.core.deps import verify_admin
from app.services.training import train

router = APIRouter()


@router.post("/train/trigger")
def train_trigger(
    _: None = Depends(verify_admin),
):
    """触发模型训练（管理员）：聚合反馈与问卷样本，训练线性 stub，输出训练日志。

    [PATCH] admin_token 从请求体移至 X-Admin-Token Header，使用 Depends(verify_admin)。
    """
    return train()
