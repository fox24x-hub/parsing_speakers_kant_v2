from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeasonConfig:
    name: str
    sports: list[str]


SEASONS = {
    "зима": SeasonConfig(name="зима", sports=["лыжи", "сноуборд"]),
    "лето": SeasonConfig(
        name="лето",
        sports=["бег", "трейлранинг", "велоспорт", "плавание", "триатлон"],
    ),
}

REGIONS = {
    "екб": "Екатеринбург",
    "екатеринбург": "Екатеринбург",
    "урфо": "УрФО",
    "россия": "Россия",
}


class SearchRequestError(ValueError):
    pass


def normalize_season(raw: str) -> SeasonConfig:
    key = raw.strip().lower()
    if key not in SEASONS:
        raise SearchRequestError("Сезон должен быть: зима или лето.")
    return SEASONS[key]


def normalize_region(raw: str) -> str:
    key = raw.strip().lower()
    if key not in REGIONS:
        raise SearchRequestError("Регион должен быть: Екатеринбург, УрФО или Россия.")
    return REGIONS[key]


def parse_find_speakers_args(text: str) -> tuple[SeasonConfig, str]:
    parts = text.strip().split()
    if len(parts) < 3:
        raise SearchRequestError("Формат: /find_speakers <сезон> <регион>.")
    season = normalize_season(parts[1])
    region = normalize_region(" ".join(parts[2:]))
    return season, region
