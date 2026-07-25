"""通用依赖（SSO 校验占位）。"""

from fastapi import Header, HTTPException

from app.core.config import settings


async def verify_admin(admin_token: str = Header(None, alias="X-Admin-Token")) -> None:
    """管理员校验依赖。"""
    if admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="管理员权限校验失败")


async def get_current_student(x_student_token: str = Header(None)) -> str:
    """获取当前登录学生（SSO 占位）。

    生产对接：GET /api/tsinghua/auth/verify?token={jwt}
    """
    if not x_student_token:
        return "anonymous"
    # 占位：直接返回 token，实际应解析 JWT 获取学号
    return x_student_token
