"""SQLite 数据访问层，启动时执行 schema.sql 建表（六张核心表）。"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .config import BASE_DIR, settings

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def init_db() -> None:
    """执行 schema.sql 建表（幂等）。"""
    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    get_conn().executescript(schema)
    get_conn().commit()


# ---------- users ----------

def create_user(name: str, email: str, timezone: Optional[str] = None) -> dict:
    try:
        cur = get_conn().execute(
            "INSERT INTO users (name, email, timezone) VALUES (?, ?, ?)",
            (name, email, timezone or settings.default_timezone),
        )
    except sqlite3.IntegrityError as e:
        raise ValueError(f"邮箱已被使用: {email}") from e
    get_conn().commit()
    # 新用户默认带一份空订阅
    get_conn().execute("INSERT INTO subscriptions (user_id) VALUES (?)", (cur.lastrowid,))
    get_conn().commit()
    return get_user(cur.lastrowid)


def update_user(user_id: int, name: str, email: str, timezone: Optional[str] = None) -> Optional[dict]:
    try:
        cur = get_conn().execute(
            "UPDATE users SET name = ?, email = ?, timezone = ? WHERE id = ?",
            (name, email, timezone or settings.default_timezone, user_id),
        )
    except sqlite3.IntegrityError as e:
        raise ValueError(f"邮箱已被使用: {email}") from e
    get_conn().commit()
    return get_user(user_id) if cur.rowcount else None


def delete_user(user_id: int) -> bool:
    cur = get_conn().execute("DELETE FROM users WHERE id = ?", (user_id,))
    get_conn().commit()
    return bool(cur.rowcount)


def get_user(user_id: int) -> Optional[dict]:
    row = get_conn().execute(
        "SELECT u.*, s.topics, s.keywords, s.enabled "
        "FROM users u LEFT JOIN subscriptions s ON s.user_id = u.id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def list_users() -> list:
    rows = get_conn().execute(
        "SELECT u.*, s.topics, s.keywords, s.enabled "
        "FROM users u LEFT JOIN subscriptions s ON s.user_id = u.id ORDER BY u.id"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- subscriptions ----------

def get_subscription(user_id: int) -> Optional[dict]:
    row = get_conn().execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_subscription(user_id: int, topics: str, keywords: str, enabled: bool) -> Optional[dict]:
    cur = get_conn().execute(
        "UPDATE subscriptions SET topics = ?, keywords = ?, enabled = ?, "
        "updated_at = datetime('now', 'localtime') WHERE user_id = ?",
        (topics, keywords, 1 if enabled else 0, user_id),
    )
    get_conn().commit()
    return get_subscription(user_id) if cur.rowcount else None


def subscription_enabled(user_id: int) -> bool:
    row = get_conn().execute("SELECT enabled FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row and row["enabled"])


# ---------- news_items（原始新闻池，URL 唯一去重）----------

def upsert_news_item(title: str, url: str, source: str, published_at: Optional[str], content: str) -> None:
    get_conn().execute(
        "INSERT INTO news_items (title, url, source, published_at, content) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(url) DO NOTHING",
        (title, url, source, published_at, content),
    )
    get_conn().commit()


def find_news_by_title(keyword: str, limit: int = 20) -> list:
    rows = get_conn().execute(
        "SELECT title, url, source, published_at FROM news_items WHERE title LIKE ? LIMIT ?",
        (f"%{keyword}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- agent_runs（工具调用轨迹）----------

def start_agent_run(user_id: int) -> int:
    cur = get_conn().execute(
        "INSERT INTO agent_runs (user_id, start_time) VALUES (?, datetime('now', 'localtime'))",
        (user_id,),
    )
    get_conn().commit()
    return cur.lastrowid


def finish_agent_run(run_id: int, status: str, trace: list, error: Optional[str] = None) -> None:
    get_conn().execute(
        "UPDATE agent_runs SET end_time = datetime('now', 'localtime'), status = ?, trace = ?, error = ? WHERE id = ?",
        (status, _dumps(trace), error, run_id),
    )
    get_conn().commit()


def get_agent_run(run_id: int) -> Optional[dict]:
    row = get_conn().execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["trace"] = _loads(run.get("trace") or "[]")
    return run


def _dumps(trace: list) -> str:
    import json
    return json.dumps(trace, ensure_ascii=False)


def _loads(text: str) -> list:
    import json
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return []


# ---------- briefings ----------

def save_briefing(user_id: int, brief_date: str, title: str, content: str,
                  file_path: Optional[str] = None, agent_run_id: Optional[int] = None) -> dict:
    """同一天重复生成时覆盖旧简报（UNIQUE(user_id, brief_date)）。"""
    get_conn().execute(
        "INSERT INTO briefings (user_id, brief_date, title, content, file_path, agent_run_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'success') "
        "ON CONFLICT(user_id, brief_date) DO UPDATE SET "
        "title = excluded.title, content = excluded.content, file_path = excluded.file_path, "
        "agent_run_id = excluded.agent_run_id, status = 'success', "
        "created_at = datetime('now', 'localtime')",
        (user_id, brief_date, title, content, file_path, agent_run_id),
    )
    get_conn().commit()
    row = get_conn().execute(
        "SELECT * FROM briefings WHERE user_id = ? AND brief_date = ?", (user_id, brief_date)
    ).fetchone()
    return dict(row)


def get_briefing(briefing_id: int) -> Optional[dict]:
    row = get_conn().execute(
        "SELECT b.*, u.name AS user_name, u.email AS user_email FROM briefings b "
        "JOIN users u ON u.id = b.user_id WHERE b.id = ?", (briefing_id,)
    ).fetchone()
    return dict(row) if row else None


def list_briefings(user_id: Optional[int] = None, limit: int = 50) -> list:
    if user_id:
        rows = get_conn().execute(
            "SELECT b.*, u.name AS user_name FROM briefings b JOIN users u ON u.id = b.user_id "
            "WHERE b.user_id = ? ORDER BY b.brief_date DESC, b.id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    else:
        rows = get_conn().execute(
            "SELECT b.*, u.name AS user_name FROM briefings b JOIN users u ON u.id = b.user_id "
            "ORDER BY b.brief_date DESC, b.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def has_briefing_on(user_id: int, brief_date: str) -> bool:
    row = get_conn().execute(
        "SELECT 1 FROM briefings WHERE user_id = ? AND brief_date = ? AND status = 'success'",
        (user_id, brief_date),
    ).fetchone()
    return row is not None


# ---------- deliveries（推送记录，幂等可重试）----------

def create_delivery(briefing_id: int, channel: str = "email") -> int:
    cur = get_conn().execute(
        "INSERT INTO deliveries (briefing_id, channel) VALUES (?, ?)", (briefing_id, channel)
    )
    get_conn().commit()
    return cur.lastrowid


def finish_delivery(delivery_id: int, status: str, error: Optional[str] = None) -> None:
    get_conn().execute(
        "UPDATE deliveries SET status = ?, error = ?, "
        "sent_at = CASE WHEN ? = 'sent' THEN datetime('now', 'localtime') ELSE sent_at END WHERE id = ?",
        (status, error, status, delivery_id),
    )
    get_conn().commit()


def get_delivery(delivery_id: int) -> Optional[dict]:
    row = get_conn().execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
    return dict(row) if row else None


def list_deliveries_for_briefing(briefing_id: int) -> list:
    rows = get_conn().execute(
        "SELECT * FROM deliveries WHERE briefing_id = ? ORDER BY id DESC", (briefing_id,)
    ).fetchall()
    return [dict(r) for r in rows]
