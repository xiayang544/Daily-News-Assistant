"""FastAPI 入口：用户/订阅/简报/Agent轨迹/推送 API + 静态前端页面。"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .config import BASE_DIR, settings
from .news import SearchError
from .push import PushError
from .scheduler import generate_for_user, retry_delivery, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("main")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if missing := settings.validate_search():
        logger.warning("搜索配置不完整，简报生成将不可用：%s", missing)
    if not settings.smtp_host:
        logger.warning("SMTP 未配置：推送将标记 skipped，可在配置后重试")
    start_scheduler()
    yield


app = FastAPI(title="Daily News Assistant", lifespan=lifespan)


# ---------- 用户管理 ----------

class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    email: str  # 自行校验格式，兼容未装 email-validator 的环境
    timezone: Optional[str] = None


@app.get("/api/users")
def get_users():
    return db.list_users()


@app.post("/api/users", status_code=201)
def post_user(u: UserIn):
    if not _EMAIL_RE.match(u.email):
        raise HTTPException(422, "邮箱格式不正确")
    try:
        return db.create_user(u.name, u.email, u.timezone)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/users/{user_id}")
def get_user(user_id: int):
    user = db.get_user(user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    return user


@app.put("/api/users/{user_id}")
def put_user(user_id: int, u: UserIn):
    if not _EMAIL_RE.match(u.email):
        raise HTTPException(422, "邮箱格式不正确")
    try:
        updated = db.update_user(user_id, u.name, u.email, u.timezone)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if updated is None:
        raise HTTPException(404, "用户不存在")
    return updated


@app.delete("/api/users/{user_id}", status_code=204)
def del_user(user_id: int):
    if not db.delete_user(user_id):
        raise HTTPException(404, "用户不存在")


# ---------- 订阅管理 ----------

class SubscriptionIn(BaseModel):
    topics: str = ""
    keywords: str = ""
    enabled: bool = True


@app.get("/api/subscriptions/{user_id}")
def get_subscription(user_id: int):
    sub = db.get_subscription(user_id)
    if sub is None:
        raise HTTPException(404, "用户不存在")
    return sub


@app.put("/api/subscriptions/{user_id}")
def put_subscription(user_id: int, s: SubscriptionIn):
    updated = db.update_subscription(user_id, s.topics, s.keywords, s.enabled)
    if updated is None:
        raise HTTPException(404, "用户不存在")
    return updated


# ---------- 简报 ----------

class GenerateIn(BaseModel):
    user_id: int


@app.post("/api/briefings/generate")
def generate(req: GenerateIn):
    """手动触发一次 Agent 简报生成（同步执行，通常需 1-3 分钟）。

    同一天重复生成会覆盖当天简报；定时任务则跳过当天已生成的（幂等）。
    """
    user = db.get_user(req.user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if not settings.deepseek_api_key:
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY，无法生成简报")
    if missing := settings.validate_search():
        raise HTTPException(400, missing)
    try:
        return generate_for_user(user)
    except SearchError as e:
        raise HTTPException(502, f"搜索失败: {e}") from e


@app.get("/api/briefings")
def list_briefings(user_id: Optional[int] = None, date: Optional[str] = None, limit: int = 50):
    """历史简报列表；date 按 brief_date 过滤（YYYY-MM-DD）。"""
    rows = db.list_briefings(user_id, limit=500)
    if date:
        rows = [r for r in rows if r["brief_date"] == date]
    return rows[:limit]


@app.get("/api/briefings/{briefing_id}")
def get_briefing(briefing_id: int):
    b = db.get_briefing(briefing_id)
    if b is None:
        raise HTTPException(404, "简报不存在")
    b["deliveries"] = db.list_deliveries_for_briefing(briefing_id)
    return b


# ---------- Agent 执行记录 ----------

@app.get("/api/agent-runs/{run_id}")
def get_agent_run(run_id: int):
    run = db.get_agent_run(run_id)
    if run is None:
        raise HTTPException(404, "执行记录不存在")
    return run


# ---------- 推送记录与重试 ----------

@app.get("/api/deliveries/{delivery_id}")
def get_delivery(delivery_id: int):
    d = db.get_delivery(delivery_id)
    if d is None:
        raise HTTPException(404, "推送记录不存在")
    return d


@app.post("/api/deliveries/{delivery_id}/retry")
def retry(delivery_id: int):
    """重试失败/跳过的推送（复用已生成简报，不重新跑 Agent）。"""
    try:
        return retry_delivery(delivery_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except PushError as e:
        raise HTTPException(502, str(e)) from e


# ---------- 前端 ----------

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")
