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

        # 推送
        self.push_channel: str = os.getenv("PUSH_CHANNEL", "").lower()  # dingtalk | feishu | wecom
        self.push_webhook_url: str = os.getenv("PUSH_WEBHOOK_URL", "")
        self.dingtalk_secret: str = os.getenv("DINGTALK_SECRET", "")

        # 调度与存储
        self.schedule_hour: int = int(os.getenv("SCHEDULE_HOUR", "8"))
        self.db_path: Path = BASE_DIR / os.getenv("DB_PATH", "data/news.db")
        self.briefings_dir: Path = BASE_DIR / "data" / "briefings"

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
