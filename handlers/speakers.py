from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

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
BLACKLIST_PATHS = {"/", "/corporate", "/club", "/events"}
BLACKLIST_QUERY_TOKENS = {"offset=", "own=", "page=", "per-page="}
INTENT_MARKERS = {
    "лекц",
    "лектор",
    "спикер",
    "выступл",
    "встреч",
    "мастер-класс",
    "вебинар",
    "анонс",
    "talk",
}


def _matches_region(text: str, region: str) -> bool:
    if region == "Россия":
        return True
    markers = REGION_TEXT_MARKERS.get(region, [])
    haystack = text.lower()
    return any(marker in haystack for marker in markers)


def _matches_intent(text: str) -> bool:
    haystack = text.lower()
    return any(marker in haystack for marker in INTENT_MARKERS)


def _build_queries(season: str, region_hint: str, sports: list[str]) -> list[str]:
    primary_sports = " ".join(sports[:2]) if sports else ""
    all_sports = " ".join(sports)
    queries = [
        f"{season} {region_hint} {all_sports} спикер лектор лекция интервью",
        f"{season} {region_hint} {primary_sports} спикер лекция",
        f"{region_hint} {primary_sports} тренер эксперт выступление",
        f"{region_hint} лекторий спорт лекция",
        f"{region_hint} спортивный клуб школа бег лыжи лекция",
        f"{region_hint} федерация триатлон велоспорт спикер",
        f"{region_hint} telegram канал анонс лекций {primary_sports}",
        f"site:t.me {region_hint} {primary_sports} лекция спикер",
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        q = " ".join(query.split())
        if q and q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def _merge_unique_sources(source_groups: list[list]) -> list:
    merged = []
    seen_links: set[str] = set()
    for group in source_groups:
        for source in group:
            if source.link in seen_links:
                continue
            seen_links.add(source.link)
            merged.append(source)
    return merged


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_blacklisted_source_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/") or "/"
    query = parsed.query.lower()
    if path in BLACKLIST_PATHS:
        return True
    if any(token in query for token in BLACKLIST_QUERY_TOKENS):
        return True
    return False


def _select_diverse_sources(
    sources: list,
    *,
    max_total: int = 12,
    max_per_domain: int = 2,
) -> list:
    selected = []
    per_domain: dict[str, int] = {}
    for source in sources:
        domain = _domain_of(source.link)
        count = per_domain.get(domain, 0)
        if count >= max_per_domain:
            continue
        selected.append(source)
        per_domain[domain] = count + 1
        if len(selected) >= max_total:
            break
    return selected


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
            query_variants = _build_queries(
                season=season_config.name,
                region_hint=hint,
                sports=season_config.sports,
            )
            query_results = []
            for query in query_variants:
                logger.info("Search query: %s", query)
                found = await search_web(query=query, settings=settings)
                logger.info("Search results for query: %s", len(found))
                if found:
                    query_results.append(found)
            sources = _merge_unique_sources(query_results)
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

        filtered_sources = [
            source for source in sources if not _is_blacklisted_source_url(source.link)
        ]
        logger.info(
            "Blacklist-filtered sources: %s -> %s",
            len(sources),
            len(filtered_sources),
        )
        if filtered_sources:
            sources = filtered_sources

        intent_sources = [
            source
            for source in sources
            if _matches_intent(f"{source.title} {source.snippet}")
        ]
        logger.info("Intent-filtered sources: %s -> %s", len(sources), len(intent_sources))
        if intent_sources:
            sources = intent_sources

        diversified_sources = _select_diverse_sources(
            sources,
            max_total=12,
            max_per_domain=2,
        )
        logger.info(
            "Diversified sources: %s -> %s",
            len(sources),
            len(diversified_sources),
        )
        sources = diversified_sources

        candidate_sources = sources
        if region != "Россия":
            prefiltered_sources = [
                source
                for source in sources
                if _matches_region(f"{source.title} {source.snippet}", region)
            ]
            logger.info(
                "Region prefilter by title/snippet: %s -> %s",
                len(sources),
                len(prefiltered_sources),
            )
            if prefiltered_sources:
                candidate_sources = prefiltered_sources

        # Enrich only region-relevant candidates so GPT gets richer evidence.
        enriched = await enrich_results(candidate_sources, max_pages=4)
        filtered_enriched = [
            source
            for source in enriched
            if _matches_region(
                f"{source.get('title', '')} {source.get('snippet', '')} {source.get('page_text', '')}",
                region,
            )
            and _matches_intent(
                f"{source.get('title', '')} {source.get('snippet', '')} {source.get('page_text', '')}"
            )
        ]
        if region != "Россия":
            logger.info(
                "Region strict filter after enrich: %s -> %s",
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
