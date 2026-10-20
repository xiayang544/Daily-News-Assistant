"""集中读取环境变量配置。密钥一律走环境变量，不硬编码。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：app/ 的上一级
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        # LLM
        self.deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
        self.deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # 联网搜索
        self.search_provider: str = os.getenv("SEARCH_PROVIDER", "tavily").lower()
        self.tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
        self.brave_api_key: str = os.getenv("BRAVE_API_KEY", "")

        # 邮件推送（开发环境可用 Mailpit：docker run -p 1025:1025 -p 8025:8025 axllent/mailpit）
        self.smtp_host: str = os.getenv("SMTP_HOST", "")        # 留空则不实际发信，推送记录为 skipped
        self.smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user: str = os.getenv("SMTP_USER", "")
        self.smtp_pass: str = os.getenv("SMTP_PASS", "")
        self.smtp_from: str = os.getenv("SMTP_FROM", "Daily News Assistant <news@example.com>")
        self.smtp_security: str = os.getenv("SMTP_SECURITY", "auto").lower()  # ssl | starttls | none | auto（按端口猜）

        # 调度与存储
        self.schedule_hour: int = int(os.getenv("SCHEDULE_HOUR", "8"))  # 用户本地时间该点触发
        self.default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Shanghai")
        self.db_path: Path = BASE_DIR / os.getenv("DB_PATH", "data/news.db")
        self.briefings_dir: Path = BASE_DIR / "data" / "briefings"
        self.news_sources_path: Path = BASE_DIR / "config" / "news_sources.txt"

        # Agent 循环限制：最大轮数与时间预算，防无限循环
        self.agent_max_iterations: int = int(os.getenv("AGENT_MAX_ITERATIONS", "12"))
        self.agent_time_budget: int = int(os.getenv("AGENT_TIME_BUDGET", "300"))  # 秒

        self.briefings_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def validate_search(self) -> str | None:
        """返回缺失配置的报错信息；配置齐全返回 None。"""
        if self.search_provider == "tavily" and not self.tavily_api_key:
            return "未配置 TAVILY_API_KEY（在 .env 中设置，见 .env.example）"
        if self.search_provider == "brave" and not self.brave_api_key:
            return "未配置 BRAVE_API_KEY（在 .env 中设置，或将 SEARCH_PROVIDER 改为 tavily）"
        return None


settings = Settings()
