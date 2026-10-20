"""APScheduler 定时任务：每天定时为所有订阅用户生成简报并推送。"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db
from .agent.loop import run_agent
from .config import settings
from .push import push_briefing

logger = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def generate_for_user(user: dict) -> dict:
    """为单个用户生成简报 → 入库 → 推送。供定时任务与手动触发共用。"""
    result = run_agent(user)
    briefing = db.save_briefing(
        user_id=user["id"],
        title=result["title"],
        content=result["content"],
        file_path=result["file_path"],
    )
    try:
        push_briefing(
            result["title"], result["content"],
            webhook_url=user.get("webhook_url"), channel=user.get("push_channel"),
        )
    except Exception as e:  # 推送失败不影响简报本身（已入库）
        logger.warning("推送失败（简报已保存）: %s", e)
    return briefing


def daily_job() -> None:
    logger.info("定时任务触发，开始为所有用户生成简报")
    for user in db.list_users():
        try:
            briefing = generate_for_user(user)
            logger.info("已为用户 %s 生成简报 #%s", user["name"], briefing["id"])
        except Exception as e:
            logger.error("为用户 %s 生成简报失败: %s", user["name"], e)
    logger.info("本轮定时任务完成，时间 %s", datetime.now().isoformat(timespec="seconds"))


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # 分钟避开整点，错峰触发
    _scheduler.add_job(
        daily_job,
        CronTrigger(hour=settings.schedule_hour, minute=7, timezone="Asia/Shanghai"),
        id="daily_briefing",
        max_instances=1,
    )
    _scheduler.start()
    logger.info("定时调度已启动：每天 %02d:07 自动生成简报", settings.schedule_hour)
    return _scheduler
