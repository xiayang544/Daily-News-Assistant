"""新闻采集层：联网搜索（Tavily/Brave）、RSS 抓取、原文页面提取。

所有采集到的条目统一为 {title, url, source, published_at, content} 结构，
并通过 db.upsert_news_item 落入 news_items 表（URL 唯一），供去重与追溯。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from html import unescape
from typing import Any

import feedparser
import httpx

from . import db
from .config import settings


class SearchError(RuntimeError):
    pass


# ---------- 联网搜索 ----------

def search_news(query: str, days: int = 1, max_results: int = 8) -> list:
    """按关键词搜索最近 days 天内的新闻。"""
    if settings.search_provider == "tavily":
        results = _tavily(query, days, max_results)
    elif settings.search_provider == "brave":
        results = _brave(query, days, max_results)
    else:
        raise SearchError(f"未知的搜索提供商: {settings.search_provider}")

    items = []
    for r in results:
        item = {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "source": f"搜索({settings.search_provider})",
            "published_at": r.get("published_at", ""),
            "content": r.get("snippet", ""),
        }
        _remember(item)
        items.append(item)
    return items


def _tavily(query: str, days: int, max_results: int) -> list:
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": False,
        "topic": "news",
    }
    if days and days > 0:
        payload["days"] = days
    try:
        resp = httpx.post("https://api.tavily.com/search", json=payload, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise SearchError(f"Tavily 请求失败: {e}") from e
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("content", ""), "published_at": r.get("published_date", "")}
            for r in resp.json().get("results", [])]


def _brave(query: str, days: int, max_results: int) -> list:
    params = {"q": query, "count": max_results}
    if days and days > 0:
        # Brave freshness：pd/pw/pm 对应过去一天/周/一月，取最接近的档位
        params["freshness"] = "pd" if days <= 1 else ("pw" if days <= 7 else "pm")
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise SearchError(f"Brave 请求失败: {e}") from e
    results = resp.json().get("web", {}).get("results", [])
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("description", ""), "published_at": r.get("age", "")}
            for r in results]


# ---------- RSS ----------

def load_rss_sources() -> dict:
    """读取 config/news_sources.txt，返回 {源名: URL}。"""
    if not settings.news_sources_path.is_file():
        return {}
    sources = {}
    for line in settings.news_sources_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, url = line.split("=", 1)
        sources[name.strip()] = url.strip()
    return sources


def fetch_rss(source: str, max_items: int = 20) -> list:
    """抓取一个 RSS 源。source 为源名（config/news_sources.txt 中定义）或直接的 URL。"""
    sources = load_rss_sources()
    url = sources.get(source, source if source.startswith("http") else "")
    if not url:
        known = "、".join(sources) or "（配置文件为空）"
        raise ValueError(f"未知 RSS 源 {source!r}，可用源：{known}")
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        raise ValueError(f"RSS 解析失败: {url}")
    items = []
    for e in feed.entries[:max_items]:
        published = ""
        if getattr(e, "published", None):
            published = e.published
        elif getattr(e, "updated", None):
            published = e.updated
        item = {
            "title": unescape(e.get("title", "")),
            "url": e.get("link", ""),
            "source": source if source in sources else (feed.feed.get("title", "RSS")),
            "published_at": published,
            "content": _strip_html(e.get("summary", ""))[:500],
        }
        if item["url"]:
            _remember(item)
            items.append(item)
    return items


# ---------- 原文页面 ----------

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def get_article(url: str) -> dict:
    """抓取原文页面，提取纯文本正文（用于核实与补充内容）。"""
    try:
        resp = httpx.get(
            url, timeout=20, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DailyNewsAssistant/1.0)"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ValueError(f"页面抓取失败: {e}") from e
    html = resp.text
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        title = unescape(m.group(1)).strip()
    text = _strip_html(html)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"title": title, "url": str(resp.url), "content": text[:6000]}


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    return re.sub(r"[ \t]{2,}", " ", text)


# ---------- 落库 ----------

def _remember(item: dict) -> None:
    """把采集到的新闻写入 news_items 表（URL 唯一，重复则忽略）。"""
    try:
        db.upsert_news_item(
            title=item["title"] or item["url"],
            url=item["url"],
            source=item.get("source", ""),
            published_at=item.get("published_at") or None,
            content=item.get("content", ""),
        )
    except Exception:
        pass  # 落库失败不影响采集主流程
