"""[PATCH] 统一响应封装与全局异常处理。

新增文件：为所有 API 提供统一的 { code, message, data } 响应格式，
以及全局异常处理中间件，替代各路由手动拼装错误响应。
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class BizError(Exception):
    """业务异常基类。"""

    def __init__(self, code: int, message: str, data=None):
        self.code = code
        self.message = message
        self.data = data


def success(data=None, message: str = "ok"):
    """成功响应封装。"""
    return {"code": 0, "message": message, "data": data}


async def biz_error_handler(request: Request, exc: BizError):
    """业务异常处理器。"""
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": exc.data},
    )


async def validation_handler(request: Request, exc: RequestValidationError):
    """参数校验异常处理器。"""
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "参数校验失败",
            "data": exc.errors(),
        },
    )


async def generic_handler(request: Request, exc: Exception):
    """通用异常兜底处理器。"""
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "data": str(exc) if request.app.debug else None,
        },
    )
