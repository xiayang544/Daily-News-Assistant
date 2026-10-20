"""FastAPI 入口：用户/简报 API + 静态前端页面 + 启动时初始化 DB 与定时调度。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional

from pydantic import BaseModel, Field

from . import db
from .config import BASE_DIR, settings
from .news import SearchError
from .scheduler import generate_for_user, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if missing := settings.validate_search():
        logger.warning("搜索配置不完整，简报生成将不可用：%s", missing)
    start_scheduler()
    yield


app = FastAPI(title="Daily News Assistant", lifespan=lifespan)


# ---------- 用户（身份 + 订阅偏好）----------

class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    topics: str = ""
    keywords: str = ""
    webhook_url: Optional[str] = None
    push_channel: Optional[str] = None  # dingtalk | feishu | wecom；None 则跟随全局配置


class GenerateIn(BaseModel):
    user_id: int


@app.get("/api/users")
def get_users():
    return db.list_users()


@app.post("/api/users", status_code=201)
def post_user(u: UserIn):
    return db.create_user(u.name, u.topics, u.keywords, u.webhook_url, u.push_channel)


@app.put("/api/users/{user_id}")
def put_user(user_id: int, u: UserIn):
    updated = db.update_user(user_id, u.name, u.topics, u.keywords, u.webhook_url, u.push_channel)
    if updated is None:
        raise HTTPException(404, "用户不存在")
    return updated


@app.delete("/api/users/{user_id}", status_code=204)
def del_user(user_id: int):
    if not db.delete_user(user_id):
        raise HTTPException(404, "用户不存在")


# ---------- 简报 ----------

@app.get("/api/briefings")
def get_briefings(user_id: Optional[int] = None, limit: int = 50):
    return db.list_briefings(user_id, limit)


@app.get("/api/briefings/{briefing_id}")
def get_briefing(briefing_id: int):
    rows = db.get_conn().execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchall()
    if not rows:
        raise HTTPException(404, "简报不存在")
    return dict(rows[0])


@app.post("/api/generate")
def generate(req: GenerateIn):
    """手动触发一次 Agent 简报生成（同步执行，通常需 1-3 分钟）。"""
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


# ---------- 前端 ----------

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")
