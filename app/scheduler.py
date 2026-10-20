"""APScheduler 定时任务。

调度策略：每小时检查一次，对每位"订阅中"的用户，若其本地时间到达
触发时刻（SCHEDULE_HOUR）且当天（用户本地日期）尚未生成简报，则执行。
由此支持每用户独立时区，并天然防重复生成。

任务状态机：agent_runs.running → success/failed；
推送独立记录 deliveries.pending → sent/failed/skipped，
生成成功但发送失败时只重试推送，不重新生成。
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db
from .agent.loop import run_agent
from .config import settings
from .push import PushError, send_briefing_email

logger = logging.getLogger("scheduler")

_scheduler = None


def generate_for_user(user: dict, brief_date: str | None = None) -> dict:
    """为单个用户生成简报 → 记录 agent 轨迹 → 入库 → 邮件推送。

    brief_date 为用户本地日期（YYYY-MM-DD），供定时任务传入；
    手动触发时传 None 则用服务器本地日期。
    """
    tz = ZoneInfo(user.get("timezone") or settings.default_timezone)
    brief_date = brief_date or datetime.now(tz).strftime("%Y-%m-%d")

    run_id = db.start_agent_run(user["id"])
    try:
        result = run_agent(user)
    except Exception as e:
        db.finish_agent_run(run_id, "failed", [], error=str(e))
        raise

    db.finish_agent_run(run_id, "success", result["trace"])
    briefing = db.save_briefing(
        user_id=user["id"],
        brief_date=brief_date,
        title=result["title"],
        content=result["content"],
        file_path=result["file_path"],
        agent_run_id=run_id,
    )
    briefing["user_email"] = user["email"]
    deliver(briefing)
    return briefing


def deliver(briefing: dict) -> int:
    """发送一封简报邮件并记录推送结果，返回 delivery id。"""
    delivery_id = db.create_delivery(briefing["id"], channel="email")
    try:
        send_briefing_email(briefing["user_email"], briefing["title"], briefing["content"])
    except PushError as e:
        # SMTP 未配置或发送失败：标记后可重试，不影响简报本身（已入库）
        status = "skipped" if "SMTP 未配置" in str(e) else "failed"
        db.finish_delivery(delivery_id, status, error=str(e))
        logger.warning("推送 %s（简报 #%s 已保存）: %s", status, briefing["id"], e)
    else:
        db.finish_delivery(delivery_id, "sent")
        logger.info("简报 #%s 已邮件推送至 %s", briefing["id"], briefing["user_email"])
    return delivery_id


def retry_delivery(delivery_id: int) -> dict:
    """重试一次失败的推送（复用已生成的简报，不重新跑 Agent）。"""
    delivery = db.get_delivery(delivery_id)
    if delivery is None:
        raise ValueError(f"推送记录 #{delivery_id} 不存在")
    if delivery["status"] == "sent":
        return delivery  # 幂等：已发送的不重复发
    briefing = db.get_briefing(delivery["briefing_id"])
    if briefing is None:
        raise ValueError("对应简报不存在")
    try:
        send_briefing_email(briefing["user_email"], briefing["title"], briefing["content"])
    except PushError as e:
        db.finish_delivery(delivery_id, "failed", error=str(e))
        raise
    db.finish_delivery(delivery_id, "sent")
    return db.get_delivery(delivery_id)


def hourly_job() -> None:
    """每小时检查：到达用户本地触发时刻且当天未生成的，执行生成。"""
    for user in db.list_users():
        if not user.get("enabled"):
            continue
        tz = ZoneInfo(user.get("timezone") or settings.default_timezone)
        local_now = datetime.now(tz)
        if local_now.hour != settings.schedule_hour:
            continue
        brief_date = local_now.strftime("%Y-%m-%d")
        if db.has_briefing_on(user["id"], brief_date):
            continue  # 幂等：当天已生成则跳过
        logger.info("为用户 %s（%s 本地 %s）触发每日简报生成", user["name"], tz, brief_date)
        try:
            generate_for_user(user, brief_date=brief_date)
        except Exception as e:
            logger.error("为用户 %s 生成简报失败: %s", user["name"], e)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler()
    # 每小时第 7 分钟检查（错开整点），按各用户本地时刻触发
    _scheduler.add_job(
        hourly_job,
        CronTrigger(minute=7, timezone="Asia/Shanghai"),
        id="hourly_briefing_check",
        max_instances=1,
    )
    _scheduler.start()
    logger.info("定时调度已启动：每小时检查，用户本地时间 %02d:00 触发生成", settings.schedule_hour)
    return _scheduler
