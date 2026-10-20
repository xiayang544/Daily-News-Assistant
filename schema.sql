-- Daily News Assistant 建表脚本（SQLite）
PRAGMA foreign_keys = ON;

-- 用户：身份 + 订阅偏好
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,                  -- 身份/昵称
    topics      TEXT    NOT NULL DEFAULT '',       -- 关注话题，逗号分隔，如 "LLM,智能体,开源模型"
    keywords    TEXT    NOT NULL DEFAULT '',       -- 关键词，逗号分隔，用于进一步过滤
    webhook_url TEXT,                              -- 可选：该用户专属推送 webhook（为空则用全局配置）
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 简报：Agent 每次生成的结果
CREATE TABLE IF NOT EXISTS briefings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    content    TEXT    NOT NULL,                   -- Markdown 格式简报正文
    file_path  TEXT,                               -- Agent 通过 write_file 工具落盘的文件
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_briefings_user ON briefings(user_id, created_at DESC);
