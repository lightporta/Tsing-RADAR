"""[PATCH] 通用依赖（SSO 校验）。

修改点：
- get_current_student 增加匿名访问日志记录
- verify_admin 注释明确为 Header 校验
"""

import logging

from fastapi import Header, HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)


async def verify_admin(admin_token: str = Header(None, alias="X-Admin-Token")) -> None:
    """管理员校验依赖。

    [PATCH] 明确：通过 X-Admin-Token Header 校验，不再从请求体读取。
    """
    if admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="管理员权限校验失败")
    return None


async def get_current_student(x_student_token: str = Header(None)) -> str:
    """获取当前登录学生（SSO 占位）。

    [PATCH] 增加匿名访问日志，便于审计。
    生产对接：GET /api/tsinghua/auth/verify?token={jwt}
    """
    if not x_student_token:
        logger.warning("匿名访问 | path=unknown | 建议：前端注入 X-Student-Token 头")
        return "anonymous"
    # 占位：直接返回 token，实际应解析 JWT 获取学号
    return x_student_token
