"""清小搭入站 OpenAI-compatible 接口鉴权。"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.identity import Principal, resolve_qxd_principal


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_qxd_bearer(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """校验平台传入的 Bearer credential，不记录或回显密钥。"""
    if not settings.QXD_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="清小搭入站凭证尚未配置",
        )

    if not authorization:
        raise _unauthorized("缺少 Bearer credential")

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Bearer credential 格式无效")

    if not hmac.compare_digest(token.strip(), settings.QXD_API_KEY):
        raise _unauthorized("Bearer credential 无效")


async def get_qxd_principal(
    external_claim: Annotated[
        str | None, Header(alias="X-QXD-End-User-Id")
    ] = None,
    signature: Annotated[
        str | None, Header(alias="X-QXD-End-User-Signature")
    ] = None,
    db: Session = Depends(get_db),
) -> Principal:
    """终端用户 claim 与平台 Bearer 分离验证。"""
    return resolve_qxd_principal(
        db,
        external_claim=external_claim,
        signature=signature,
    )
