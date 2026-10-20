-- Daily News Assistant 建表脚本（SQLite）
PRAGMA foreign_keys = ON;

-- 用户：身份 + 邮箱（推送对象）+ 时区
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,               -- 邮箱唯一
    timezone    TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 订阅偏好：一人一份
CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    topics      TEXT    NOT NULL DEFAULT '',           -- 关注话题，逗号分隔
    keywords    TEXT    NOT NULL DEFAULT '',           -- 关键词，逗号分隔
    enabled     INTEGER NOT NULL DEFAULT 1,           -- 1 订阅中 / 0 已暂停（暂停后停止自动生成与推送）
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 原始新闻池：所有采集到的新闻，用于去重与追溯
CREATE TABLE IF NOT EXISTS news_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    url          TEXT    NOT NULL UNIQUE,              -- URL 唯一，天然去重
    source       TEXT    NOT NULL DEFAULT '',          -- 来源名称（RSS 源名 / 搜索引擎）
    published_at TEXT,                                 -- 原文发布时间
    content      TEXT    NOT NULL DEFAULT '',          -- 摘要或正文
    fetched_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Agent 执行记录：保存真实工具调用轨迹，证明调用顺序由模型自主决定
CREATE TABLE IF NOT EXISTS agent_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_time TEXT    NOT NULL,
    end_time   TEXT,
    status     TEXT    NOT NULL DEFAULT 'running',     -- running / success / failed
    trace      TEXT    NOT NULL DEFAULT '[]',          -- JSON 数组：每轮工具调用与结果
    error      TEXT
);

-- 简报：状态 pending → running → success / failed
CREATE TABLE IF NOT EXISTS briefings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brief_date   TEXT    NOT NULL,                     -- 用户本地日期 YYYY-MM-DD，与 user_id 联合防重复生成
    title        TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    file_path    TEXT,
    agent_run_id INTEGER REFERENCES agent_runs(id),
    status       TEXT    NOT NULL DEFAULT 'success',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (user_id, brief_date)
);

-- 推送记录：生成成功但发送失败时，可只重试推送而不重新生成
CREATE TABLE IF NOT EXISTS deliveries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_id INTEGER NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    channel     TEXT    NOT NULL DEFAULT 'email',
    status      TEXT    NOT NULL DEFAULT 'pending',    -- pending / sent / failed / skipped
    error       TEXT,
    sent_at     TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_briefings_user_date ON briefings(user_id, brief_date DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user ON agent_runs(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_deliveries_briefing ON deliveries(briefing_id);
