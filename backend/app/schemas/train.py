"""[PATCH] 训练触发 Pydantic 模型。

修改点：
- 移除 admin_token 字段（改由 X-Admin-Token Header 传递）
"""


class TrainConfig:
    """训练配置参数（admin_token 改为 Header 传递）。"""
    pass
