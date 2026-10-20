"""简报推送：钉钉 / 飞书 / 企业微信 自定义机器人 webhook。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

import httpx

from .config import settings


class PushError(RuntimeError):
    pass


def push_briefing(title: str, content: str, webhook_url: str | None = None, channel: str | None = None) -> None:
    """把简报推送到 IM。webhook/channel 未配置时静默跳过（只留 Web 页面查看）。"""
    channel = (channel or settings.push_channel).lower()
    webhook = webhook_url or settings.push_webhook_url
    if not channel or not webhook:
        return

    if channel == "dingtalk":
        _push_dingtalk(webhook, title, content)
    elif channel == "feishu":
        _push_feishu(webhook, title, content)
    elif channel == "wecom":
        _push_wecom(webhook, title, content)
    else:
        raise PushError(f"未知的推送渠道: {channel}（支持 dingtalk / feishu / wecom）")


def _post(webhook: str, payload: dict) -> None:
    try:
        resp = httpx.post(webhook, json=payload, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise PushError(f"推送请求失败: {e}") from e
    data = resp.json()
    # 三家的错误码字段不一致，统一检查
    code = data.get("errcode", data.get("code"))
    if code not in (0, None):
        raise PushError(f"推送被拒绝: {data}")


def _push_dingtalk(webhook: str, title: str, content: str) -> None:
    if settings.dingtalk_secret:
        webhook = _signed_url(webhook, settings.dingtalk_secret)
    _post(webhook, {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"# {title}\n\n{content}"},
    })


def _push_feishu(webhook: str, title: str, content: str) -> None:
    # 飞书自定义机器人走 post 富文本消息（一行一个 text 块）
    _post(webhook, {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [[{"tag": "text", "text": line} for line in content.splitlines() if line.strip()]],
                }
            }
        },
    })


def _push_wecom(webhook: str, title: str, content: str) -> None:
    # 企业微信 markdown 上限 4096 字节，超长截断
    text = f"# {title}\n\n{content}"
    if len(text.encode()) > 4000:
        text = text.encode()[:4000].decode(errors="ignore") + "\n\n...（内容过长已截断，完整简报见 Web 页面）"
    _post(webhook, {"msgtype": "markdown", "markdown": {"content": text}})


def _signed_url(webhook: str, secret: str) -> str:
    """钉钉机器人'加签'模式的 URL 计算。"""
    ts = str(round(time.time() * 1000))
    sign = base64.b64encode(hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()).decode()
    return f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sign)}"
