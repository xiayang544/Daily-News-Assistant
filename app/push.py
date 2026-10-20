"""简报邮件推送：SMTP（开发环境可用 Mailpit 模拟收信）。

SMTP_HOST 未配置时不实际发信，推送记录标记 skipped，
简报仍可在 Web 页面查看，之后配置好 SMTP 可重试推送。
"""
from __future__ import annotations

import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from .config import settings

logger = logging.getLogger("push")


class PushError(RuntimeError):
    pass


def send_briefing_email(to_email: str, title: str, markdown_content: str) -> None:
    """把简报以邮件发出。未配置 SMTP 时抛出 PushError 说明原因。"""
    if not settings.smtp_host:
        raise PushError("SMTP 未配置（.env 中设置 SMTP_HOST 等，开发环境可用 Mailpit）")

    subject = title
    body = (
        f"{markdown_content}\n\n"
        f"--\n来自每日 AI 新闻助手 · 回复本邮件无效\n"
        f"完整历史简报见 Web 页面\n"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("每日 AI 新闻助手", _addr(settings.smtp_from)))
    msg["To"] = to_email

    try:
        # Mailpit 等本地模拟服务无 STARTTLS 也无认证，按配置降级
        if settings.smtp_starttls and settings.smtp_port != 2525:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                try:
                    s.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_pass)
                s.sendmail(_addr(settings.smtp_from), [to_email], msg.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_pass)
                s.sendmail(_addr(settings.smtp_from), [to_email], msg.as_string())
    except (smtplib.SMTPException, OSError) as e:
        raise PushError(f"邮件发送失败: {e}") from e


def _addr(from_header: str) -> str:
    """从 "Name <a@b.c>" 提取纯地址；无尖括号则原样返回。"""
    if "<" in from_header and ">" in from_header:
        return from_header[from_header.index("<") + 1:from_header.index(">")]
    return from_header
