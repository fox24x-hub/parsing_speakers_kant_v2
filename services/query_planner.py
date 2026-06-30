from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx

from config.settings import Settings

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "Ты планировщик поисковых запросов для поиска спикеров спортивного лектория KANT (Екатеринбург). "
    "Задача: сгенерировать 6–10 поисковых запросов на русском языке для Google/Serper, "
    "которые найдут реальных спикеров — действующих спортсменов, тренеров, экспертов — "
    "для живых лекций в лектории.\n\n"
    "Правила:\n"
    "1. Запросы должны быть разнообразными: разные формулировки, платформы (t.me, vk.com, dzen.ru), "
    "типы контента (интервью, анонсы, профили).\n"
    "2. Включай актуальные годы для свежести результатов.\n"
    "3. Используй site: операторы для Telegram и ВКонтакте.\n"
    "4. Запросы на русском, без кавычек вокруг фраз.\n"
    "5. Верни ТОЛЬКО валидный JSON-массив строк без Markdown и пояснений:\n"
    '["запрос 1", "запрос 2", ...]'
)


def _fallback_queries(season: str, region_hint: str, sports: list[str]) -> list[str]:
    primary = " ".join(sports[:2]) if sports else ""
    all_s = " ".join(sports)
    y = datetime.utcnow().year
    raw = [
        f"{season} {region_hint} {all_s} спикер лектор лекция интервью {y}",
        f"{season} {region_hint} {primary} спикер лекция {y - 1} {y}",
        f"{region_hint} {primary} тренер эксперт выступление",
        f"{region_hint} лекторий спорт лекция",
        f"{region_hint} спортивный клуб школа бег лыжи лекция",
        f"{region_hint} федерация триатлон велоспорт спикер",
        f"{region_hint} telegram канал анонс лекций {primary}",
        f"site:t.me {region_hint} {primary} лекция спикер",
    ]
    seen: set[str] = set()
    result: list[str] = []
    for q in raw:
        q = " ".join(q.split())
        if q and q not in seen:
            seen.add(q)
            result.append(q)
    return result


async def plan_queries(
    season: str,
    region_hint: str,
    sports: list[str],
    settings: Settings,
) -> list[str]:
    """
    Генерирует поисковые запросы через Sonnet.
    При любой ошибке молча возвращает статические fallback-запросы.
    """
    y = datetime.utcnow().year
    user_message = (
        f"Сезон: {season}. Регион поиска: {region_hint}. "
        f"Виды спорта: {', '.join(sports)}. Текущий год: {y}.\n\n"
        "Сгенерируй поисковые запросы для поиска спикеров лектория."
    )

    payload: dict[str, Any] = {
        "model": _MODEL,
        "max_tokens": 512,
        "temperature": 1,  # выше temperature — более разнообразные запросы
        "system": [
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_message}],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
        "anthropic-beta": "prompt-caching-2024-07-31",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text = block["text"].strip()
                break

        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        queries: list[str] = json.loads(text)
        if not isinstance(queries, list) or not queries:
            raise ValueError("Planner returned empty or non-list")

        # дедупликация
        seen: set[str] = set()
        result: list[str] = []
        for q in queries:
            q = str(q).strip()
            if q and q not in seen:
                seen.add(q)
                result.append(q)

        logger.info("Query planner generated %d queries for %s / %s", len(result), region_hint, season)
        return result

    except Exception as exc:
        logger.warning("Query planner failed (%s), using fallback", exc)
        return _fallback_queries(season, region_hint, sports)
