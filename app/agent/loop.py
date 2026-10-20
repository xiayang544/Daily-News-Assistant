"""Agent 核心循环：DeepSeek function calling。

流程完全由 LLM 驱动——每轮把工具清单交给模型，模型自主决定调用哪个工具、
调用几次、何时给出最终回答。代码侧只负责执行工具并把结果回填，
并施加最大轮数与时间预算防止无限循环。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from openai import OpenAI

from ..config import settings
from .tools import TOOL_MAP, TOOLS

SYSTEM_PROMPT = """你是每日 AI 新闻简报助手。任务：根据用户的订阅偏好，收集新闻并产出一份 Markdown 简报。

工作方式（由你自主决定具体步骤与顺序，以下是要求而非流程）：
1. 新闻采集混合使用两类工具：
   - fetch_rss：稳定获取已配置 RSS 源的新闻（源清单可用 read_file 读取 config/news_sources.txt）
   - search_news：按用户话题/关键词主动检索，补充 RSS 未覆盖的内容
   两类各用多少、先搜哪个话题、是否补充搜索，由你根据中间结果自行判断。
2. 可用 get_article 核实某条重要新闻的原文，或用 search_content 检索 data/briefings/ 下的历史简报，避免与往期重复。
3. 严格防幻觉：简报中的每一条新闻都必须来自工具返回的真实结果，必须保留原始 URL、来源名称和发布时间（如有）。不允许凭记忆或推测编造任何新闻事实。若某话题确实没有新闻，直接说明覆盖不足，不要凑数。
4. 用 write_file 把简报写入 `data/briefings/{user_id}/{YYYY-MM-DD}.md`。
5. 简报格式：
   - 标题：`# AI 日报 · YYYY-MM-DD · {用户名}专属`
   - 每条新闻：`## 标题`，2-3 句话概括要点，附 `> 来源: <来源名> | 时间: <发布时间> | <URL>`
   - 结尾一节 `## 今日小结`，3 句以内总结当天趋势
   - 总条数 5-10 条，优先最近 24 小时，扩大时间范围时明确标注日期
6. 写完文件后，用一两句话总结你调用了哪些工具、做了什么，即可结束。

今天的日期以实际执行时为准，可先用 bash 执行 date 确认。"""


def _build_user_prompt(user: dict) -> str:
    topics = user.get("topics") or "AI 领域整体动态"
    keywords = user.get("keywords") or "无"
    return (
        f"用户 #{user['id']} {user['name']} 的订阅偏好：\n"
        f"- 关注话题：{topics}\n"
        f"- 关键词：{keywords}\n"
        f"请现在开始为这位用户收集今天的 AI 新闻并生成简报。"
    )


def run_agent(user: dict) -> dict:
    """跑一轮完整 Agent 循环，返回 {title, content, file_path, trace}。

    简报正文优先取 Agent 落盘的 markdown 文件；若模型没写文件，
    兜底使用最终回复文本。
    """
    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY（在 .env 中设置，见 .env.example）")

    client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(user)},
    ]
    trace = []
    deadline = time.monotonic() + settings.agent_time_budget

    for round_no in range(1, settings.agent_max_iterations + 1):
        if time.monotonic() > deadline:
            trace.append({"round": round_no, "note": f"达到时间预算 {settings.agent_time_budget}s，强制结束"})
            break
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            tools=[t.schema() for t in TOOLS],
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            # 模型认为可以收工了
            trace.append({"round": round_no, "role": "assistant", "content": msg.content or ""})
            break

        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            tool = TOOL_MAP.get(call.function.name)
            if tool is None:
                result = f"没有名为 {call.function.name} 的工具"
            else:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as e:
                    result = f"参数不是合法 JSON: {e}"
                else:
                    result = tool(**args)
            trace.append({
                "round": round_no,
                "tool": call.function.name,
                "args": call.function.arguments,
                "result": result[:500],
            })
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    else:
        trace.append({"note": f"达到最大轮数 {settings.agent_max_iterations}，强制结束"})

    # 从落盘文件读取最终简报
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = settings.briefings_dir / str(user["id"]) / f"{today}.md"
    if file_path.is_file():
        content = file_path.read_text(encoding="utf-8")
        title = content.splitlines()[0].lstrip("# ").strip() or f"AI 日报 · {today}"
    else:
        content = next(
            (t["content"] for t in reversed(trace) if t.get("role") == "assistant" and t.get("content")),
            "",
        )
        title = f"AI 日报 · {today}"

    if not content.strip():
        raise RuntimeError("Agent 未能产出简报内容（未写文件且最终回复为空）")

    return {
        "title": title,
        "content": content,
        "file_path": str(file_path) if file_path.is_file() else None,
        "trace": trace,
    }
