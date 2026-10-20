"""Agent 工具集（八个）。

前五个为题目指定工具：list_dir / read_file / search_content / write_file / bash；
另三个面向新闻任务：search_news / fetch_rss / get_article。

安全约束：
- 文件类工具限制在项目目录内，且禁止读写 .env 与数据库文件（密钥保护）
- bash 只允许白名单内的只读类命令，禁止重定向/替换/执行解释器
- 工具输出回传 LLM 前截断，防止撑爆上下文

工具调用顺序由 LLM 在 Agent 循环中自主决定（见 loop.py）。
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

from ..config import BASE_DIR
from ..news import SearchError, fetch_rss, get_article, search_news

# 工具输出回传给 LLM 前的截断长度
MAX_TOOL_OUTPUT = 4000

# bash 命令白名单：只允许只读/查询类命令
BASH_WHITELIST = {
    "date", "echo", "ls", "pwd", "grep", "find", "wc", "head", "tail",
    "sort", "uniq", "stat", "cat", "diff", "column",
}
# bash 中禁止出现的字符与模式（重定向写文件、命令替换等）
BASH_FORBIDDEN_RE = re.compile(r"[><`]|\$\(|\|\||&&|;")

# 文件工具禁止访问的敏感路径片段
SENSITIVE_PATH_RE = re.compile(r"\.env|news\.db|\.git/")


class Tool:
    def __init__(self, name: str, description: str, params: dict, fn: Callable) -> None:
        self.name = name
        self.description = description
        self.params = params
        self.fn = fn

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params,
            },
        }

    def __call__(self, **kwargs: Any) -> str:
        try:
            result = self.fn(**kwargs)
        except TypeError as e:
            return f"参数错误: {e}"
        except (ValueError, OSError) as e:
            # 路径越界、源不存在等：把错误回传给 LLM，由它自行调整
            return f"工具执行失败: {e}"
        return _truncate(str(result))


def _truncate(text: str) -> str:
    if len(text) > MAX_TOOL_OUTPUT:
        return text[:MAX_TOOL_OUTPUT] + f"\n...（输出过长，已截断，共 {len(text)} 字符）"
    return text


def _safe_path(path: str) -> Path:
    """把路径限制在项目根目录内，并拦截 .env 等敏感文件。"""
    p = Path(path)
    resolved = (p if p.is_absolute() else BASE_DIR / p).resolve()
    if not str(resolved).startswith(str(BASE_DIR)):
        raise ValueError(f"路径越界，只允许操作项目目录内: {path}")
    if SENSITIVE_PATH_RE.search(str(resolved)):
        raise ValueError(f"敏感文件禁止访问: {path}")
    return resolved


def _format_items(items: list) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        published = f" | 发布时间: {it['published_at']}" if it.get("published_at") else ""
        lines.append(f"{i}. {it['title']}\n   链接: {it['url']}\n   来源: {it['source']}{published}\n   摘要: {it['content'][:200]}")
    return "\n\n".join(lines) if lines else "（无结果）"


# ---------- 题目指定的 5 个基础工具 ----------

def _list_dir(path: str = ".") -> str:
    p = _safe_path(path)
    if not p.is_dir():
        return f"不是目录: {path}"
    entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
    lines = [f"{'[目录]' if e.is_dir() else '[文件]'} {e.name}" for e in entries]
    return "\n".join(lines) or "(空目录)"


def _read_file(path: str) -> str:
    p = _safe_path(path)
    if not p.is_file():
        return f"文件不存在: {path}"
    return p.read_text(encoding="utf-8", errors="replace")


def _search_content(keyword: str, dir: str = ".") -> str:
    p = _safe_path(dir)
    if not p.is_dir():
        return f"不是目录: {dir}"
    hits = []
    for f in sorted(p.rglob("*")):
        if f.suffix in {".db", ".pyc", ".png", ".jpg", ".ico"} or ".git" in f.parts or ".venv" in f.parts:
            continue
        if not f.is_file() or f.stat().st_size > 1_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if keyword in line:
                hits.append(f"{f.relative_to(BASE_DIR)}:{i}: {line.strip()}")
                if len(hits) >= 50:
                    return "\n".join(hits) + "\n...（命中过多，已截断）"
    return "\n".join(hits) or f"未找到包含 {keyword!r} 的内容"


def _write_file(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {p.relative_to(BASE_DIR)}（{len(content)} 字符）"


def _bash(command: str) -> str:
    stripped = command.strip()
    if BASH_FORBIDDEN_RE.search(stripped):
        return "命令被拒绝：不允许重定向、命令替换或多命令连接"
    try:
        tokens = shlex.split(stripped)
    except ValueError as e:
        return f"命令解析失败: {e}"
    if not tokens:
        return "(空命令)"
    if tokens[0] not in BASH_WHITELIST:
        return f"命令 {tokens[0]!r} 不在白名单内，可用命令：{ '、'.join(sorted(BASH_WHITELIST)) }"
    try:
        proc = subprocess.run(tokens, cwd=BASE_DIR, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "命令超时（30 秒）被终止"
    out = proc.stdout
    if proc.stderr:
        out += ("\n[stderr]\n" + proc.stderr) if out else proc.stderr
    return f"exit code: {proc.returncode}\n{out or '(无输出)'}"


# ---------- 面向新闻任务的 3 个采集工具 ----------

def _search_news(query: str, days: int = 1) -> str:
    try:
        items = search_news(query, days=days)
    except SearchError as e:
        return f"搜索失败: {e}"
    return f"关键词 {query!r} 最近 {days} 天的搜索结果：\n\n" + _format_items(items)


def _fetch_rss(source: str) -> str:
    items = fetch_rss(source)
    return f"RSS 源 {source!r} 的最新条目：\n\n" + _format_items(items)


def _get_article(url: str) -> str:
    art = get_article(url)
    return f"标题: {art['title']}\nURL: {art['url']}\n\n正文（纯文本，已截断）：\n{art['content']}"


TOOLS = [
    Tool(
        "list_dir",
        "列出指定目录下的文件和子目录。可用于查看 config/（新闻源配置）、data/briefings/（历史简报）等。",
        {"type": "object", "properties": {"path": {"type": "string", "description": "相对项目根目录的路径，默认 '.'"}}, "required": []},
        _list_dir,
    ),
    Tool(
        "read_file",
        "读取指定文本文件的内容。例如 config/news_sources.txt 可查看可用的 RSS 新闻源清单。",
        {"type": "object", "properties": {"path": {"type": "string", "description": "相对项目根目录的路径"}}, "required": ["path"]},
        _read_file,
    ),
    Tool(
        "search_content",
        "在指定目录下按关键词搜索文件内容，返回命中文件与行号。可用于检索历史简报，避免重复收录旧新闻。",
        {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词，如某条新闻标题关键词"},
                "dir": {"type": "string", "description": "相对项目根目录的目录路径，默认 '.'，检索历史建议用 data/briefings"},
            },
            "required": ["keyword"],
        },
        _search_content,
    ),
    Tool(
        "write_file",
        "将内容写入指定文件（覆盖写），目录不存在会自动创建。最终简报请写入 data/briefings/{user_id}/{YYYY-MM-DD}.md。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根目录的路径"},
                "content": {"type": "string", "description": "写入的完整内容"},
            },
            "required": ["path", "content"],
        },
        _write_file,
    ),
    Tool(
        "bash",
        "执行受限 shell 命令（只读类白名单，30 秒超时）。可用于 date 确认当天日期、grep 检索历史等。",
        {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的命令，如 'date +%Y-%m-%d'"}}, "required": ["command"]},
        _bash,
    ),
    Tool(
        "search_news",
        "联网搜索最近几天的新闻，返回标题/链接/来源/发布时间/摘要。围绕用户关注的话题和关键词搜索，可多次调用不同关键词。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询词，如 'AI 大模型 最新进展'"},
                "days": {"type": "integer", "description": "时间范围（天），默认 1；新闻不足时可扩大到 3 或 7"},
            },
            "required": ["query"],
        },
        _search_news,
    ),
    Tool(
        "fetch_rss",
        "从 RSS 订阅源抓取最新新闻。源名见 config/news_sources.txt（可用 read_file 查看），也接受直接的 RSS URL。",
        {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "RSS 源名（如 'Hacker News'、'机器之心'）或 URL"}},
            "required": ["source"],
        },
        _fetch_rss,
    ),
    Tool(
        "get_article",
        "抓取新闻原文页面并提取正文纯文本，用于核实新闻内容或补充摘要细节。",
        {"type": "object", "properties": {"url": {"type": "string", "description": "新闻原文 URL"}}, "required": ["url"]},
        _get_article,
    ),
]

TOOL_MAP = {t.name: t for t in TOOLS}
