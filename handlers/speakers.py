from __future__ import annotations

import json
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.settings import Settings
from gpt_client import gpt_search_speakers
from keyboards import topics_keyboard
from search_client import SearchClientError, enrich_results, search_web
from speaker_search import (
    REGION_QUERY_HINTS,
    REGION_TEXT_MARKERS,
    SearchRequestError,
    parse_find_speakers_args,
)

router = Router()
logger = logging.getLogger(__name__)


def _matches_region(text: str, region: str) -> bool:
    if region == "Россия":
        return True
    markers = REGION_TEXT_MARKERS.get(region, [])
    haystack = text.lower()
    return any(marker in haystack for marker in markers)


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет! Я бот KANT - помогу найти спикеров по сезонам и регионам. "
        "Используйте /topics или /find_speakers <сезон> <регион>."
    )


@router.message(Command("topics"))
async def topics_handler(message: Message) -> None:
    await message.answer(
        "Выберите сезон и регион или используйте /find_speakers <сезон> <регион>.",
        reply_markup=topics_keyboard(),
    )


@router.callback_query()
async def callback_hint_handler(query: CallbackQuery) -> None:
    if not query.data:
        await query.answer()
        return

    if query.data.startswith("season:"):
        season = query.data.split(":", 1)[1]
        await query.message.answer(
            f"Сезон выбран: {season}. Используйте /find_speakers {season} <регион>."
        )
    elif query.data.startswith("region:"):
        region = query.data.split(":", 1)[1]
        pretty = {
            "екатеринбург": "Екатеринбург",
            "урфо": "УрФО",
            "россия": "Россия",
        }.get(region, region)
        await query.message.answer(
            f"Регион выбран: {pretty}. Используйте /find_speakers <сезон> {pretty}."
        )

    await query.answer()


@router.message(Command("find_speakers"))
async def find_speakers_handler(message: Message, settings: Settings) -> None:
    try:
        season_config, region = parse_find_speakers_args(message.text or "")
    except SearchRequestError as exc:
        await message.answer(str(exc))
        return

    await message.answer("Ищу спикеров, подождите...")

    try:
        hints = REGION_QUERY_HINTS.get(region, [region])
        sources = []
        for hint in hints:
            query = (
                f"{season_config.name} {hint} "
                f"{' '.join(season_config.sports)} "
                "спикер лектор лекция интервью"
            )
            logger.info("Search query: %s", query)
            sources = await search_web(query=query, settings=settings)
            if sources:
                break

        if not sources:
            await message.answer(
                "Не нашёл источников по запросу. Попробуйте уточнить регион или сезон."
            )
            return

        logger.info("Sources found: %s", len(sources))
        for idx, source in enumerate(sources, start=1):
            logger.info("Source %s: %s", idx, source.link)

        enriched = await enrich_results(sources, max_pages=2)
        filtered_enriched = [
            source
            for source in enriched
            if _matches_region(
                f"{source.get('title', '')} {source.get('snippet', '')} {source.get('page_text', '')}",
                region,
            )
        ]
        if region != "Россия":
            logger.info(
                "Region-filtered sources: %s -> %s",
                len(enriched),
                len(filtered_enriched),
            )
        if filtered_enriched:
            enriched = filtered_enriched

        result = await gpt_search_speakers(
            season=season_config.name,
            region=region,
            sports=season_config.sports,
            sources=enriched,
            settings=settings,
        )
    except SearchClientError as exc:
        await message.answer(str(exc))
        return
    except Exception:
        await message.answer("Ошибка при запросе к GPT. Попробуйте позже.")
        return

    speakers = result.get("speakers", [])
    if not speakers:
        await message.answer(
            f"Спикеров для сезона <{result.get('season', season_config.name)}> "
            f"и региона <{result.get('region', region)}> пока нет в списке."
        )
        await message.answer(
            "Ответ GPT (JSON):\n" + json.dumps(result, ensure_ascii=False, indent=2)
        )
        return

    lines = [
        f"Спикеры для сезона <{result.get('season', season_config.name)}> "
        f"в регионе <{result.get('region', region)}>:",
        "",
    ]

    for idx, sp in enumerate(speakers, start=1):
        name = sp.get("name", "Без имени")
        sport = sp.get("sport", "Спорт не указан")
        location = sp.get("location", "Локация не указана")
        expertise = sp.get("expertise", "Описание не указано")
        url = sp.get("url")
        contact = sp.get("contact")
        format_value = sp.get("format")

        line = (
            f"{idx}) {name}\n"
            f"   Вид спорта: {sport}\n"
            f"   Локация: {location}\n"
            f"   Тема/экспертиза: {expertise}"
        )
        if url:
            line += f"\n   Профиль: {url}"
        if contact:
            line += f"\n   Контакт: {contact}"
        if format_value:
            line += f"\n   Формат: {format_value}"

        lines.append(line)
        lines.append("")

    text = "\n".join(lines)
    await message.answer(text)
    await message.answer(
        "Ответ GPT (JSON):\n" + json.dumps(result, ensure_ascii=False, indent=2)
    )
