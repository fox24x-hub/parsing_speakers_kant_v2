from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def topics_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="ЗИМА 🏔", callback_data="season:зима")
    builder.button(text="ЛЕТО ☀️", callback_data="season:лето")
    builder.button(text="Екатеринбург", callback_data="region:екатеринбург")
    builder.button(text="УрФО", callback_data="region:урфо")
    builder.button(text="Россия", callback_data="region:россия")
    builder.adjust(2, 3)
    return builder.as_markup()


def start_moderation_keyboard(run_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Просмотреть кандидатов", callback_data=f"mod:nx:{run_id}")
    return builder.as_markup()


def candidate_keyboard(candidate_id: int, run_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Одобрить", callback_data=f"mod:ap:{candidate_id}:{run_id}")
    builder.button(text="В шортлист", callback_data=f"mod:sl:{candidate_id}:{run_id}")
    builder.button(text="Отклонить", callback_data=f"mod:rj:{candidate_id}:{run_id}")
    builder.button(text="Следующий", callback_data=f"mod:nx:{run_id}")
    builder.adjust(3, 1)
    return builder.as_markup()
