from __future__ import annotations

import json
from typing import Any

import httpx

from config.settings import Settings

# Anthropic API endpoint
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Модели — меняй здесь или вынеси в Settings
MODEL_EXTRACTION = "claude-haiku-4-5-20251001"   # дешевле, быстрее — для extraction/ranking
MODEL_PLANNING = "claude-sonnet-4-6"              # умнее — для query planning (если понадобится)


def _build_system_prompt() -> str:
    """
    Системный промпт вынесен отдельно — он кэшируется.
    Anthropic кэширует prefix контента, поэтому стабильная часть должна идти первой.
    """
    return (
        "Ты точный JSON-экстрактор для поиска спикеров спортивных лекций. "
        "Правила:\n"
        "1. Возвращай ТОЛЬКО валидный JSON — без Markdown, без пояснений, без ```.\n"
        "2. Используй ТОЛЬКО данные из источников в запросе. Не придумывай.\n"
        "3. Если данные не подтверждены источником — не включай их.\n"
        "4. Контакт и формат — только если явно указаны в источниках.\n"
        "5. Если спикеров нет — верни speakers: [].\n\n"
        "Формат ответа:\n"
        '{"season": str, "region": str, "sports": [str], "speakers": ['
        '{"name": str, "sport": str, "location": str, "expertise": str, '
        '"url": str | null, "contact": str | null, "format": str | null}'
        "]}"
    )


def build_user_message(
    season: str,
    region: str,
    sports: list[str],
    sources: list[dict[str, Any]],
    *,
    strict_region: bool = True,
) -> str:
    """
    Пользовательская часть промпта — меняется каждый запрос, не кэшируется.
    """
    sports_list = ", ".join(sports)
    sources_json = json.dumps(sources, ensure_ascii=False, indent=2)

    region_rule = (
        "Если регион спикера не подтверждён источником — не добавляй. "
        if strict_region
        else (
            "Если регион явно не указан — допустимо использовать региональный контекст источника, "
            "но не выдумывай факты. "
        )
    )

    return (
        f"Сезон: {season}. Регион: {region}. Виды спорта: {sports_list}.\n"
        f"{region_rule}\n\n"
        "Источники (JSON-массив: title / snippet / link / display_link / page_text / contacts / format_hints):\n"
        f"{sources_json}"
    )


async def anthropic_search_speakers(
    *,
    season: str,
    region: str,
    sports: list[str],
    sources: list[dict[str, Any]],
    settings: Settings,
    strict_region: bool = True,
) -> dict[str, Any]:
    """
    Основная функция — замена gpt_search_speakers.
    Использует prompt caching для системного промпта (экономия ~90% на input).

    Возвращает dict с полями: season, region, sports, speakers.
    """
    system_prompt = _build_system_prompt()
    user_message = build_user_message(
        season, region, sports, sources, strict_region=strict_region
    )

    # Anthropic messages API payload
    payload = {
        "model": MODEL_EXTRACTION,
        "max_tokens": 2048,
        "temperature": 0,  # у Anthropic temperature=0 — детерминированный JSON
        # Системный промпт с cache_control — Anthropic кэширует этот блок
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},  # кэш до 5 минут
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": user_message,
            }
        ],
    }

    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
        # Включаем prompt caching
        "anthropic-beta": "prompt-caching-2024-07-31",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    # Anthropic возвращает content как список блоков
    content_blocks = data.get("content", [])
    text = ""
    for block in content_blocks:
        if block.get("type") == "text":
            text = block["text"]
            break

    if not text:
        raise ValueError(f"Пустой ответ от Anthropic API: {data}")

    # Чистим на случай если модель всё-таки добавит ```json
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    return json.loads(text)


# ---------------------------------------------------------------------------
# Обратная совместимость — старое имя функции работает без изменений в speakers.py
# ---------------------------------------------------------------------------

async def gpt_search_speakers(
    *,
    season: str,
    region: str,
    sports: list[str],
    sources: list[dict[str, Any]],
    settings: Settings,
    strict_region: bool = True,
) -> dict[str, Any]:
    """
    Алиас для совместимости со старым кодом в speakers.py.
    speakers.py менять не нужно — просто замени файл gpt_client.py на этот.
    """
    return await anthropic_search_speakers(
        season=season,
        region=region,
        sports=sports,
        sources=sources,
        settings=settings,
        strict_region=strict_region,
    )
