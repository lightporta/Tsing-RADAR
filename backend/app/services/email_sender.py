"""导师服务邮件发送：console（默认，验证码打日志）或 SMTP。

- MAIL_MODE=console：验证码只打印到服务端日志（开发/测试默认，不真正发送），
  测试通过 caplog 断言验证码内容。
- MAIL_MODE=smtp：走 smtplib.SMTP_SSL 发送（生产，须配置 MAIL_HOST/PORT/USER/PASSWORD）。
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_code_email(*, email: str, code: str, purpose: str) -> None:
    """发送邮箱验证码；console 模式仅打日志（测试断言据此）。"""
    if settings.MAIL_MODE == "console":
        logger.info(
            "MENTOR_EMAIL_CODE purpose=%s email=%s code=%s",
            purpose,
            email,
            code,
        )
        return
    if settings.MAIL_MODE != "smtp":
        raise RuntimeError(f"不支持的 MAIL_MODE: {settings.MAIL_MODE}")
    if not settings.MAIL_HOST or not settings.MAIL_USER or not settings.MAIL_PASSWORD:
        raise RuntimeError("SMTP 模式必须配置 MAIL_HOST/MAIL_USER/MAIL_PASSWORD")
    subject = "Tsing-RADAR 导师服务验证码"
    body = (
        f"您的导师服务验证码为：{code}\n"
        f"验证码 {settings.MENTOR_CODE_TTL_SECONDS // 60} 分钟内有效，"
        "请勿转发给他人。\n"
        f"用途：{purpose}"
    )
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = settings.MAIL_FROM
    message["To"] = email
    message["Date"] = formatdate(localtime=True)
    with smtplib.SMTP_SSL(
        settings.MAIL_HOST,
        settings.MAIL_PORT,
        timeout=15,
    ) as server:
        server.login(settings.MAIL_USER, settings.MAIL_PASSWORD)
        server.sendmail(settings.MAIL_USER, [email], message.as_string())
