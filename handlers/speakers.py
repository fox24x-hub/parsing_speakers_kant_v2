from __future__ import annotations

import json

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message


from config.settings import Settings
from gpt_client import get_speakers_from_gpt
from keyboards import topics_keyboard
from speaker_search import SearchRequestError, parse_find_speakers_args

router = Router()


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет! Я бот KANT — помогу найти спикеров по сезонам и регионам. "
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

    season = season_config.name          # "зима" / "лето"
    location_scope = region              # пока 1:1
    sports = ["лыжи", "сноуборд"] if season == "зима" else ["бег", "трейл", "триатлон"]

    try:
        result = await get_speakers_from_gpt(
            season=season,
            location_scope=location_scope,
            user_query=message.text,
            settings=settings,
        )
    except Exception:
        await message.answer("Ошибка при запросе к GPT. Попробуйте позже.")
        return

    speakers = result.get("speakers", [])
    if not speakers:
        await message.answer(
            f"Спикеров для сезона «{result.get('season', season)}» "
            f"и региона «{result.get('location_scope', location_scope)}» пока нет в списке."
        )
        await message.answer(
            "Ответ GPT (JSON):\n" + json.dumps(result, ensure_ascii=False, indent=2)
        )
        return

    lines = [
        f"🎯 Спикеры для сезона «{result.get('season', season)}» "
        f"в регионе «{result.get('location_scope', location_scope)}»:",
        "",
    ]

    for idx, sp in enumerate(speakers, start=1):
        name = sp.get("name", "Без имени")
        sport = sp.get("sport", "Спорт не указан")
        city = sp.get("city", "Город не указан")
        expertise = sp.get("expertise", "Описание не указано")
        url = sp.get("url")

        line = (
            f"{idx}) {name}\n"
            f"   • Вид спорта: {sport}\n"
            f"   • Город: {city}\n"
            f"   • Тема/экспертиза: {expertise}"
        )
        if url:
            line += f"\n   • Профиль: {url}"

        lines.append(line)
        lines.append("")

    text = "\n".join(lines)
    await message.answer(text)

    await message.answer(
        "Ответ GPT (JSON):\n" + json.dumps(result, ensure_ascii=False, indent=2)
    )
