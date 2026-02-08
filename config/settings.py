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


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        bot_token=os.environ.get("BOT_TOKEN", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        webhook_url=os.environ.get("WEBHOOK_URL", ""),
        port=int(os.environ.get("PORT", "8080")),
    )
