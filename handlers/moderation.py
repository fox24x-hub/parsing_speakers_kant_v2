from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.settings import Settings
from keyboards import candidate_keyboard
from services.db import (
    approve_candidate,
    get_approved_speakers,
    get_latest_run_id,
    get_pending_candidates,
    reject_candidate,
)

router = Router()
logger = logging.getLogger(__name__)


def _format_candidate(sp: dict, idx: int, total: int) -> str:
    lines = [f"Кандидат {idx}/{total}"]
    score = sp.get("score")
    if score is not None and score >= 0:
        lines.append(f"Оценка AI: {int(score)}/100")
        if sp.get("score_explanation"):
            lines.append(f"  {sp['score_explanation']}")
    lines.append(f"Имя: {sp.get('name', '—')}")
    if sp.get("sport"):
        lines.append(f"Вид спорта: {sp['sport']}")
    if sp.get("location"):
        lines.append(f"Локация: {sp['location']}")
    if sp.get("expertise"):
        lines.append(f"Экспертиза: {sp['expertise']}")
    if sp.get("url"):
        lines.append(f"Профиль: {sp['url']}")
    if sp.get("contact"):
        lines.append(f"Контакт: {sp['contact']}")
    if sp.get("format"):
        lines.append(f"Формат: {sp['format']}")
    return "\n".join(lines)


async def _show_next(
    run_id: int,
    settings: Settings,
    answer_fn,           # callable(text, reply_markup=...)
    edit_fn=None,        # callable(text, reply_markup=...) — для редактирования сообщения
) -> None:
    pending = await get_pending_candidates(settings.speakers_db_path, run_id)
    if not pending:
        await answer_fn("Все кандидаты просмотрены.")
        return
    sp = pending[0]
    text = _format_candidate(sp, 1, len(pending))
    markup = candidate_keyboard(sp["id"], run_id)
    fn = edit_fn or answer_fn
    await fn(text, reply_markup=markup)


@router.message(Command("next"))
async def next_handler(message: Message, settings: Settings) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        await message.answer("Не удалось определить пользователя.")
        return
    run_id = await get_latest_run_id(settings.speakers_db_path, user_id)
    if not run_id:
        await message.answer("Нет активных прогонов. Запустите /find_speakers сначала.")
        return
    await _show_next(
        run_id, settings,
        answer_fn=lambda t, **kw: message.answer(t, **kw),
    )


@router.message(Command("shortlist"))
async def shortlist_handler(message: Message, settings: Settings) -> None:
    approved = await get_approved_speakers(settings.speakers_db_path)
    if not approved:
        await message.answer("Шортлист пуст. Одобрите кандидатов через /next.")
        return
    lines = [f"Шортлист ({len(approved)} чел.):", ""]
    for idx, sp in enumerate(approved, 1):
        line = f"{idx}) {sp.get('name', '—')}"
        if sp.get("sport"):
            line += f" | {sp['sport']}"
        if sp.get("location"):
            line += f" | {sp['location']}"
        if sp.get("url"):
            line += f"\n   {sp['url']}"
        lines.append(line)
    await message.answer("\n".join(lines))


@router.callback_query(lambda c: c.data and c.data.startswith("mod:"))
async def moderation_callback(query: CallbackQuery, settings: Settings) -> None:
    parts = (query.data or "").split(":")
    # parts[0] == "mod", parts[1] == action, parts[2] == id/run_id, parts[3] == run_id (optional)
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]

    if action == "nx":
        run_id = int(parts[2])
        await query.answer()
        pending = await get_pending_candidates(settings.speakers_db_path, run_id)
        if not pending:
            await query.message.edit_text("Все кандидаты просмотрены.")
            return
        sp = pending[0]
        text = _format_candidate(sp, 1, len(pending))
        markup = candidate_keyboard(sp["id"], run_id)
        await query.message.edit_text(text, reply_markup=markup)
        return

    if action in ("ap", "sl", "rj") and len(parts) >= 4:
        candidate_id = int(parts[2])
        run_id = int(parts[3])
        user_id = query.from_user.id if query.from_user else None

        if action == "rj":
            await reject_candidate(settings.speakers_db_path, candidate_id)
            label = "Отклонён"
        else:
            await approve_candidate(settings.speakers_db_path, candidate_id, approved_by=user_id)
            label = "В шортлисте" if action == "sl" else "Одобрен"

        await query.answer(label)

        # автоматически показываем следующего
        pending = await get_pending_candidates(settings.speakers_db_path, run_id)
        if not pending:
            await query.message.edit_text(f"{label}. Все кандидаты просмотрены.")
            return
        sp = pending[0]
        text = _format_candidate(sp, 1, len(pending))
        markup = candidate_keyboard(sp["id"], run_id)
        await query.message.edit_text(text, reply_markup=markup)
        return

    await query.answer()
