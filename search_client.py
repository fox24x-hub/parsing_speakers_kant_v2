from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

from config.settings import Settings
from page_extractor import extract_contacts, extract_format_hints, fetch_page_text


class SearchClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    link: str
    display_link: str


def _cache_key(query: str, num: int, cse_id: str) -> str:
    raw = f"{query}|{num}|{cse_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def _ensure_cache_db(path: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path.as_posix()) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        await db.commit()


async def _get_cached(
    *, path: str, cache_key: str, ttl_seconds: int
) -> list[SearchResult] | None:
    now = int(time.time())
    async with aiosqlite.connect(Path(path).as_posix()) as db:
        async with db.execute(
            "SELECT response_json, created_at FROM search_cache WHERE cache_key = ?",
            (cache_key,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            payload, created_at = row
            if now - int(created_at) > ttl_seconds:
                return None
            try:
                items = json.loads(payload)
            except json.JSONDecodeError:
                return None
            return [SearchResult(**item) for item in items]


async def _set_cached(
    *, path: str, cache_key: str, results: list[SearchResult]
) -> None:
    payload = json.dumps([result.__dict__ for result in results], ensure_ascii=False)
    async with aiosqlite.connect(Path(path).as_posix()) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO search_cache (cache_key, response_json, created_at)
            VALUES (?, ?, ?)
            """,
            (cache_key, payload, int(time.time())),
        )
        await db.commit()


def build_domain_query(query: str, domains: list[str]) -> str:
    if not domains:
        return query
    site_filter = " OR ".join(f"site:{domain}" for domain in domains)
    return f"({site_filter}) {query}".strip()


async def google_cse_search(
    *,
    query: str,
    settings: Settings,
    max_results: int | None = None,
    domains: list[str] | None = None,
) -> list[SearchResult]:
    if not settings.google_cse_api_key or not settings.google_cse_id:
        raise SearchClientError("Google CSE не настроен.")

    num = max_results or settings.search_max_results
    if num < 1:
        return []

    await _ensure_cache_db(settings.cache_db_path)
    ttl_seconds = settings.cache_ttl_days * 24 * 3600
    cache_key = _cache_key(query, num, settings.google_cse_id)

    cached = await _get_cached(
        path=settings.cache_db_path, cache_key=cache_key, ttl_seconds=ttl_seconds
    )
    if cached is not None:
        return cached

    domains = domains if domains is not None else settings.allowed_domains
    query_with_domains = build_domain_query(query, domains)

    params = {
        "key": settings.google_cse_api_key,
        "cx": settings.google_cse_id,
        "q": query_with_domains,
        "num": num,
    }
    url = "https://www.googleapis.com/customsearch/v1"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data: dict[str, Any] = response.json()

    items = data.get("items", [])
    results: list[SearchResult] = []
    for item in items:
        results.append(
            SearchResult(
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                link=item.get("link", ""),
                display_link=item.get("displayLink", ""),
            )
        )

    await _set_cached(path=settings.cache_db_path, cache_key=cache_key, results=results)
    return results


async def enrich_results(
    results: list[SearchResult], *, max_pages: int = 4
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for result in results[:max_pages]:
        page_text = ""
        contacts: list[str] = []
        format_hints: list[str] = []
        try:
            page_text = await fetch_page_text(result.link)
            contacts = extract_contacts(page_text)
            format_hints = extract_format_hints(page_text)
        except Exception:
            page_text = ""
            contacts = []
            format_hints = []

        enriched.append(
            {
                "title": result.title,
                "snippet": result.snippet,
                "link": result.link,
                "display_link": result.display_link,
                "page_text": page_text,
                "contacts": contacts,
                "format_hints": format_hints,
            }
        )

    for result in results[max_pages:]:
        enriched.append(
            {
                "title": result.title,
                "snippet": result.snippet,
                "link": result.link,
                "display_link": result.display_link,
                "page_text": "",
                "contacts": [],
                "format_hints": [],
            }
        )
    return enriched
