from __future__ import annotations

import json
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.settings import Settings
from keyboards import topics_keyboard, start_moderation_keyboard
from search_client import SearchClientError
from services.scan_service import run_scan
from speaker_search import SearchRequestError, parse_find_speakers_args

router = Router()
logger = logging.getLogger(__name__)


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
        result = await run_scan(
            season_config, region, settings,
            user_id=message.from_user.id if message.from_user else None,
        )
    except SearchClientError as exc:
        await message.answer(str(exc))
        return
    except Exception:
        logger.exception("scan failed")
        await message.answer("Ошибка при поиске. Попробуйте позже.")
        return

    speakers = result.get("speakers", [])
    if not speakers:
        await message.answer(
            f"Спикеров для сезона <{result.get('season', season_config.name)}> "
            f"и региона <{result.get('region', region)}> пока нет в списке."
        )
        await message.answer(
            "Ответ (JSON):\n" + json.dumps(result, ensure_ascii=False, indent=2)
        )
        return

    lines = [
        f"Спикеры для сезона <{result.get('season', season_config.name)}> "
        f"в регионе <{result.get('region', region)}>:",
        "",
    ]
    for idx, sp in enumerate(speakers, start=1):
        line = (
            f"{idx}) {sp.get('name', 'Без имени')}\n"
            f"   Вид спорта: {sp.get('sport', 'Спорт не указан')}\n"
            f"   Локация: {sp.get('location', 'Локация не указана')}\n"
            f"   Тема/экспертиза: {sp.get('expertise', 'Описание не указано')}"
        )
        if sp.get("url"):
            line += f"\n   Профиль: {sp['url']}"
        if sp.get("contact"):
            line += f"\n   Контакт: {sp['contact']}"
        if sp.get("format"):
            line += f"\n   Формат: {sp['format']}"
        lines.append(line)
        lines.append("")

    run_id = result.get("run_id")
    await message.answer("\n".join(lines))
    if run_id:
        await message.answer(
            "Начните модерацию: одобряйте или отклоняйте кандидатов.",
            reply_markup=start_moderation_keyboard(run_id),
        )
