"""联网搜索：Tavily / Brave 两种后端，统一返回 [{title, url, snippet}]。"""
from __future__ import annotations

import httpx

from .config import settings


class SearchError(RuntimeError):
    pass


def web_search(query: str, max_results: int = 8) -> list[dict[str, str]]:
    if settings.search_provider == "tavily":
        return _tavily_search(query, max_results)
    if settings.search_provider == "brave":
        return _brave_search(query, max_results)
    raise SearchError(f"未知的搜索提供商: {settings.search_provider}")


def _tavily_search(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise SearchError(f"Tavily 请求失败: {e}") from e
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in resp.json().get("results", [])
    ]


def _brave_search(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise SearchError(f"Brave 请求失败: {e}") from e
    results = resp.json().get("web", {}).get("results", [])
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in results
    ]
