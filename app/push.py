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
        # SMTP_SECURITY: ssl(465) | starttls(587) | none(明文/本地 Mailpit)
        security = settings.smtp_security
        if security == "ssl" or (security == "auto" and settings.smtp_port == 465):
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                _login_and_send(s, to_email, msg)
        elif security == "starttls" or (security == "auto" and settings.smtp_port == 587):
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                try:
                    s.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass  # Mailpit 等本地模拟服务不支持 STARTTLS，降级明文
                _login_and_send(s, to_email, msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                _login_and_send(s, to_email, msg)
    except (smtplib.SMTPException, OSError) as e:
        raise PushError(f"邮件发送失败: {e}") from e


def _login_and_send(s: smtplib.SMTP, to_email: str, msg: MIMEText) -> None:
    if settings.smtp_user:
        s.login(settings.smtp_user, settings.smtp_pass)
    s.sendmail(_addr(settings.smtp_from), [to_email], msg.as_string())


def _addr(from_header: str) -> str:
    """从 "Name <a@b.c>" 提取纯地址；无尖括号则原样返回。"""
    if "<" in from_header and ">" in from_header:
        return from_header[from_header.index("<") + 1:from_header.index(">")]
    return from_header
