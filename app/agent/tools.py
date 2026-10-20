"""Agent 工具集。
from __future__ import annotations

工具的 JSON Schema 以 OpenAI function calling 格式提供给 DeepSeek，
具体调用哪个工具、调用几次、何时停止，均由 LLM 在循环中自主决定。

文件类工具出于安全考虑限制在项目根目录内操作。
"""

import subprocess
from pathlib import Path
from typing import Any, Callable

from ..config import BASE_DIR
from ..news import SearchError, web_search

# 工具输出回传给 LLM 前的截断长度，防止撑爆上下文
MAX_TOOL_OUTPUT = 4000


class Tool:
    def __init__(self, name: str, description: str, params: dict, fn: Callable[..., str]) -> None:
        self.name = name
        self.description = description
        self.params = params  # JSON Schema 的 parameters 字段
        self.fn = fn

    def schema(self) -> dict[str, Any]:
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
            # 路径越界、文件不存在等：把错误回传给 LLM，由它自行调整
            return f"工具执行失败: {e}"
        return _truncate(str(result))


def _truncate(text: str) -> str:
    if len(text) > MAX_TOOL_OUTPUT:
        return text[:MAX_TOOL_OUTPUT] + f"\n...（输出过长，已截断，共 {len(text)} 字符）"
    return text


def _safe_path(path: str) -> Path:
    """把路径限制在项目根目录内。"""
    p = Path(path)
    resolved = (p if p.is_absolute() else BASE_DIR / p).resolve()
    if not str(resolved).startswith(str(BASE_DIR)):
        raise ValueError(f"路径越界，只允许操作项目目录内: {path}")
    return resolved


# ---------- 作业要求的 5 个基础工具 ----------

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
    hits: list[str] = []
    for f in sorted(p.rglob("*")):
        # 跳过二进制/大文件/依赖目录
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
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "命令超时（60 秒）被终止"
    out = proc.stdout
    if proc.stderr:
        out += ("\n[stderr]\n" + proc.stderr) if out else proc.stderr
    return f"exit code: {proc.returncode}\n{out or '(无输出)'}"


# ---------- 面向新闻任务的联网搜索工具 ----------

def _web_search(query: str, max_results: int = 8) -> str:
    try:
        results = web_search(query, max_results)
    except SearchError as e:
        return f"搜索失败: {e}"
    if not results:
        return f"未搜索到结果: {query}"
    return "\n\n".join(f"{i}. {r['title']}\n   链接: {r['url']}\n   摘要: {r['snippet']}" for i, r in enumerate(results, 1))


TOOLS: list[Tool] = [
    Tool(
        "list_dir",
        "列出指定目录下的文件和子目录。",
        {"type": "object", "properties": {"path": {"type": "string", "description": "相对项目根目录的路径，默认 '.'"}}, "required": []},
        _list_dir,
    ),
    Tool(
        "read_file",
        "读取指定文本文件的内容。",
        {"type": "object", "properties": {"path": {"type": "string", "description": "相对项目根目录的路径"}}, "required": ["path"]},
        _read_file,
    ),
    Tool(
        "search_content",
        "在指定目录下按关键词搜索文件内容，返回命中文件与行号。",
        {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "dir": {"type": "string", "description": "相对项目根目录的目录路径，默认 '.'"},
            },
            "required": ["keyword"],
        },
        _search_content,
    ),
    Tool(
        "write_file",
        "将内容写入指定文件（覆盖写），目录不存在会自动创建。",
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
        "执行 shell 命令（60 秒超时）。用于查看日期、统计等辅助操作。",
        {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}}, "required": ["command"]},
        _bash,
    ),
    Tool(
        "web_search",
        "联网搜索最新新闻。这是获取新闻的主要途径，可按不同关键词多次调用。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询词，如 'AI 大模型 最新进展 今日'"},
                "max_results": {"type": "integer", "description": "返回条数，默认 8"},
            },
            "required": ["query"],
        },
        _web_search,
    ),
]

TOOL_MAP = {t.name: t for t in TOOLS}
