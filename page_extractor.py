from __future__ import annotations

import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{8,}\d)")

FORMAT_KEYWORDS = [
    "онлайн",
    "оффлайн",
    "офлайн",
    "вебинар",
    "лекция",
    "мастер-класс",
    "семинар",
    "воркшоп",
]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def extract_contacts(text: str) -> list[str]:
    emails = EMAIL_RE.findall(text)
    phones = PHONE_RE.findall(text)
    return _dedupe(emails + phones)


def extract_format_hints(text: str) -> list[str]:
    lowered = text.lower()
    found = [kw for kw in FORMAT_KEYWORDS if kw in lowered]
    return _dedupe(found)


async def fetch_page_text(url: str, *, max_chars: int = 2000) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        html = response.text

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = " ".join(text.split())
    return text[:max_chars]
