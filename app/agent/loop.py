"""Agent 核心循环：DeepSeek function calling。
from __future__ import annotations

流程完全由 LLM 驱动——每轮把工具清单交给模型，模型自主决定调用哪个工具、
调用几次、何时给出最终回答。代码侧只负责执行工具并把结果回填。
"""

import json
from datetime import datetime
from typing import Any

from openai import OpenAI

from ..config import settings
from .tools import TOOL_MAP, TOOLS

MAX_ITERATIONS = 30

SYSTEM_PROMPT = """你是每日 AI 新闻简报助手。你的任务：根据用户的订阅偏好，收集今天的 AI 新闻并产出一份 Markdown 简报。

工作要求：
1. 用 web_search 工具联网搜索新闻。先围绕用户关注的话题逐个搜索（每个话题 1-2 次不同关键词，可加"最新/今天/新闻"等限定词），搜索次数由你根据信息量自行决定。
2. 从搜索结果中筛选出与用户话题/关键词真正相关、且有信息量的新闻，剔除软文和重复内容。宁缺毋滥。
3. 用 write_file 工具把简报写入 `data/briefings/{user_id}/{YYYY-MM-DD}.md`（date 用今天的实际日期）。
4. 简报格式要求：
   - 标题：`# AI 日报 · YYYY-MM-DD · {用户名}专属`
   - 每条新闻：`## 标题`，下面用 2-3 句话概括要点，并附原文链接 `> 来源: <url>`
   - 结尾加一节 `## 今日小结`，用 3 句以内总结当天趋势
   - 总条数控制在 5-10 条
5. 写完文件后，用一句自然语言总结你做了什么即可结束，不要在回复里重复简报全文。

注意：今天的日期以你实际执行时为准，可先用 bash 执行 `date` 确认。"""


def _build_user_prompt(user: dict[str, Any]) -> str:
    topics = user.get("topics") or "AI 领域整体动态"
    keywords = user.get("keywords") or "无"
    return (
        f"用户 #{user['id']} {user['name']} 的订阅偏好：\n"
        f"- 关注话题：{topics}\n"
        f"- 关键词：{keywords}\n"
        f"请现在开始为这位用户收集今天（{datetime.now().strftime('%Y-%m-%d')}）的 AI 新闻并生成简报。"
    )


def run_agent(user: dict[str, Any]) -> dict[str, Any]:
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
    trace: list[dict[str, Any]] = []

    for _ in range(MAX_ITERATIONS):
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            tools=[t.schema() for t in TOOLS],
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            # 模型认为可以收工了
            trace.append({"role": "assistant", "content": msg.content or ""})
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
            trace.append({"tool": call.function.name, "args": call.function.arguments, "result": result[:500]})
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )
    else:
        trace.append({"role": "assistant", "content": "（达到最大迭代次数，强制结束）"})

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

    return {
        "title": title,
        "content": content,
        "file_path": str(file_path) if file_path.is_file() else None,
        "trace": trace,
    }
