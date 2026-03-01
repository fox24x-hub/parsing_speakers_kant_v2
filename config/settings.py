from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    webhook_url: str
    port: int
    google_cse_api_key: str
    google_cse_id: str
    serper_api_key: str
    search_provider: str
    search_max_results: int
    cache_db_path: str
    cache_ttl_days: int
    allowed_domains: list[str]


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        bot_token=os.environ.get("BOT_TOKEN", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        webhook_url=os.environ.get("WEBHOOK_URL", ""),
        port=int(os.environ.get("PORT", "8080")),
        google_cse_api_key=os.environ.get("GOOGLE_CSE_API_KEY", ""),
        google_cse_id=os.environ.get("GOOGLE_CSE_ID", ""),
        serper_api_key=os.environ.get("SERPER_API_KEY", ""),
        search_provider=os.environ.get("SEARCH_PROVIDER", "google"),
        search_max_results=int(os.environ.get("SEARCH_MAX_RESULTS", "8")),
        cache_db_path=os.environ.get("CACHE_DB_PATH", "data/search_cache.db"),
        cache_ttl_days=int(os.environ.get("CACHE_TTL_DAYS", "7")),
        allowed_domains=[
            domain.strip()
            for domain in os.environ.get(
                "ALLOWED_DOMAINS", "youtube.com,vk.com,sports.ru"
            ).split(",")
            if domain.strip()
        ],
    )
