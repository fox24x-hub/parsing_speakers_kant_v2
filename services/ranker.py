from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config.settings import Settings

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = (
    "Ты оцениваешь кандидатов в спикеры спортивного лектория KANT. "
    "Критерии оценки:\n"
    "- Реальный практический опыт в спорте (не только тренерство)\n"
    "- Публичность: есть интервью, соцсети, медиа\n"
    "- Соответствие региону\n"
    "- Потенциал для живой лекции (не онлайн-эксперт без аудитории)\n\n"
    "Верни ТОЛЬКО валидный JSON без Markdown:\n"
    '{"score": <целое 0-100>, "explanation": "<1-2 предложения>"}'
)


async def rank_candidate(
    candidate: dict[str, Any],
    *,
    season: str,
    region: str,
    sports: list[str],
    settings: Settings,
) -> tuple[float, str]:
    """
    Оценивает одного кандидата. Возвращает (score, explanation).
    При ошибке возвращает (-1, сообщение об ошибке) — не прерывает поток.
    """
    user_message = (
        f"Сезон: {season}. Регион: {region}. Виды спорта: {', '.join(sports)}.\n\n"
        f"Кандидат:\n{json.dumps(candidate, ensure_ascii=False, indent=2)}"
    )

    payload = {
        "model": _MODEL,
        "max_tokens": 256,
        "temperature": 0,
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

        parsed = json.loads(text)
        score = float(parsed.get("score", 0))
        explanation = str(parsed.get("explanation", ""))
        logger.info("Ranked '%s': %.0f — %s", candidate.get("name"), score, explanation)
        return score, explanation

    except Exception as exc:
        logger.warning("Ranking failed for '%s': %s", candidate.get("name"), exc)
        return -1.0, f"Ошибка ранжирования: {exc}"


async def rank_all(
    candidates: list[dict[str, Any]],
    candidate_ids: list[int],
    *,
    season: str,
    region: str,
    sports: list[str],
    settings: Settings,
    db_path: str,
) -> None:
    """
    Ранжирует всех кандидатов и сохраняет оценки в БД.
    Запускается после save_candidates — candidate_ids соответствуют candidates по индексу.
    """
    from services.db import update_candidate_score  # local import to avoid circular

    for cid, candidate in zip(candidate_ids, candidates):
        score, explanation = await rank_candidate(
            candidate,
            season=season,
            region=region,
            sports=sports,
            settings=settings,
        )
        if score >= 0:
            await update_candidate_score(db_path, cid, score, explanation)
