"""SQLite 数据访问层，启动时执行 schema.sql 建表。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import BASE_DIR, settings

_conn: sqlite3.Connection | None = None


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

def create_user(name: str, topics: str, keywords: str, webhook_url: str | None = None) -> dict[str, Any]:
    cur = get_conn().execute(
        "INSERT INTO users (name, topics, keywords, webhook_url) VALUES (?, ?, ?, ?)",
        (name, topics, keywords, webhook_url),
    )
    get_conn().commit()
    return get_user(cur.lastrowid)


def update_user(user_id: int, name: str, topics: str, keywords: str, webhook_url: str | None) -> dict[str, Any] | None:
    cur = get_conn().execute(
        "UPDATE users SET name = ?, topics = ?, keywords = ?, webhook_url = ? WHERE id = ?",
        (name, topics, keywords, webhook_url, user_id),
    )
    get_conn().commit()
    return get_user(user_id) if cur.rowcount else None


def delete_user(user_id: int) -> bool:
    cur = get_conn().execute("DELETE FROM users WHERE id = ?", (user_id,))
    get_conn().commit()
    return bool(cur.rowcount)


def get_user(user_id: int) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    rows = get_conn().execute("SELECT * FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ---------- briefings ----------

def save_briefing(user_id: int, title: str, content: str, file_path: str | None = None) -> dict[str, Any]:
    cur = get_conn().execute(
        "INSERT INTO briefings (user_id, title, content, file_path) VALUES (?, ?, ?, ?)",
        (user_id, title, content, file_path),
    )
    get_conn().commit()
    row = get_conn().execute("SELECT * FROM briefings WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_briefings(user_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if user_id:
        rows = get_conn().execute(
            "SELECT b.*, u.name AS user_name FROM briefings b JOIN users u ON u.id = b.user_id "
            "WHERE b.user_id = ? ORDER BY b.id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    else:
        rows = get_conn().execute(
            "SELECT b.*, u.name AS user_name FROM briefings b JOIN users u ON u.id = b.user_id "
            "ORDER BY b.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
