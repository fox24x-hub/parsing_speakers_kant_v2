from __future__ import annotations

import logging
import re
from urllib.parse import urlparse
from typing import Any

from config.settings import Settings
from anthropic_client import gpt_search_speakers
from search_client import enrich_results, search_web
from services.db import create_run, finish_run, save_candidates
from services.query_planner import plan_queries
from services.ranker import rank_all
from speaker_search import REGION_QUERY_HINTS, REGION_TEXT_MARKERS, SeasonConfig

logger = logging.getLogger(__name__)

_BLACKLIST_PATHS = {"/", "/corporate", "/club", "/events"}
_BLACKLIST_QUERY_TOKENS = {"offset=", "own=", "page=", "per-page="}
_INTENT_MARKERS = {
    "лекц", "лектор", "спикер", "выступл", "встреч",
    "мастер-класс", "вебинар", "анонс", "talk",
}
_YEARS_AGO_RE = re.compile(r"(\d{1,2})\s+лет?\s+назад")


def _matches_region(text: str, region: str) -> bool:
    if region == "Россия":
        return True
    markers = REGION_TEXT_MARKERS.get(region, [])
    return any(m in text.lower() for m in markers)


def _matches_intent(text: str) -> bool:
    return any(m in text.lower() for m in _INTENT_MARKERS)


def _is_stale(text: str, max_age_years: int) -> bool:
    match = _YEARS_AGO_RE.search(text.lower())
    if not match:
        return False
    try:
        return int(match.group(1)) > max_age_years
    except ValueError:
        return False


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_blocked(url: str, settings: Settings) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower().rstrip("/") or "/"
    query = parsed.query.lower()
    full = url.lower()
    for blocked in settings.blocked_domains:
        b = blocked.lower().removeprefix("www.")
        if host == b or host.endswith(f".{b}"):
            return True
    if any(p in full for p in settings.blocked_patterns):
        return True
    if path in _BLACKLIST_PATHS:
        return True
    if any(t in query for t in _BLACKLIST_QUERY_TOKENS):
        return True
    return False



def _merge_unique(groups: list[list]) -> list:
    seen: set[str] = set()
    merged = []
    for group in groups:
        for s in group:
            if s.link not in seen:
                seen.add(s.link)
                merged.append(s)
    return merged


def _diversify(sources: list, *, max_total: int = 12, max_per_domain: int = 2) -> list:
    per_domain: dict[str, int] = {}
    result = []
    for s in sources:
        d = _domain_of(s.link)
        if per_domain.get(d, 0) >= max_per_domain:
            continue
        result.append(s)
        per_domain[d] = per_domain.get(d, 0) + 1
        if len(result) >= max_total:
            break
    return result


async def run_scan(
    season_config: SeasonConfig,
    region: str,
    settings: Settings,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Full pipeline: search → filter → enrich → LLM extraction → persist to DB.
    Returns {season, region, sports, speakers, run_id}.
    Raises SearchClientError or ValueError on failure.
    """
    db_path = settings.speakers_db_path
    run_id = await create_run(
        db_path,
        season=season_config.name,
        region=region,
        sports=season_config.sports,
        user_id=user_id,
    )

    try:
        result = await _do_scan(season_config, region, settings)
    except Exception:
        await finish_run(db_path, run_id, ok=False)
        raise

    speakers = result.get("speakers", [])
    candidate_ids: list[int] = []
    if speakers:
        candidate_ids = await save_candidates(db_path, run_id, speakers)
    await finish_run(db_path, run_id, ok=True)

    if speakers and candidate_ids:
        await rank_all(
            speakers,
            candidate_ids,
            season=season_config.name,
            region=region,
            sports=season_config.sports,
            settings=settings,
            db_path=db_path,
        )

    result["run_id"] = run_id
    return result


async def _do_scan(
    season_config: SeasonConfig,
    region: str,
    settings: Settings,
) -> dict[str, Any]:
    hints = REGION_QUERY_HINTS.get(region, [region])
    sources = []
    for hint in hints:
        query_variants = await plan_queries(
            season_config.name, hint, season_config.sports, settings
        )
        groups = []
        for query in query_variants:
            logger.info("Search query: %s", query)
            found = await search_web(query=query, settings=settings)
            logger.info("Results: %d", len(found))
            if found:
                groups.append(found)
        sources = _merge_unique(groups)
        if sources:
            break

    if not sources:
        return {"season": season_config.name, "region": region, "sports": season_config.sports, "speakers": []}

    logger.info("Sources found: %d", len(sources))

    filtered = [s for s in sources if not _is_blocked(s.link, settings)]
    logger.info("After blacklist: %d -> %d", len(sources), len(filtered))
    if filtered:
        sources = filtered

    intent = [s for s in sources if _matches_intent(f"{s.title} {s.snippet}")]
    logger.info("After intent filter: %d -> %d", len(sources), len(intent))
    if intent:
        sources = intent

    fresh = [
        s for s in sources
        if not _is_stale(f"{s.title} {s.snippet}", settings.max_source_age_years)
    ]
    logger.info("After freshness filter: %d -> %d", len(sources), len(fresh))
    if fresh:
        sources = fresh

    sources = _diversify(sources, max_total=12, max_per_domain=2)
    logger.info("After diversify: %d", len(sources))

    candidates = sources
    if region != "Россия":
        regional = [s for s in sources if _matches_region(f"{s.title} {s.snippet}", region)]
        logger.info("Regional pre-filter: %d -> %d", len(sources), len(regional))
        if regional:
            candidates = regional

    enriched = await enrich_results(candidates, max_pages=4)

    strict = [
        s for s in enriched
        if _matches_region(
            f"{s.get('title','')} {s.get('snippet','')} {s.get('page_text','')}",
            region,
        )
        and _matches_intent(
            f"{s.get('title','')} {s.get('snippet','')} {s.get('page_text','')}",
        )
    ]
    logger.info("Strict filter after enrich: %d -> %d", len(enriched), len(strict))
    if strict:
        enriched = strict
    else:
        relaxed = [
            s for s in enriched
            if _matches_intent(
                f"{s.get('title','')} {s.get('snippet','')} {s.get('page_text','')}",
            )
        ]
        if relaxed:
            logger.info("Relaxed intent-only filter: %d -> %d", len(enriched), len(relaxed))
            enriched = relaxed

    result = await gpt_search_speakers(
        season=season_config.name,
        region=region,
        sports=season_config.sports,
        sources=enriched,
        settings=settings,
        strict_region=True,
    )
    if not result.get("speakers") and enriched:
        logger.info("Retrying with relaxed region mode")
        result = await gpt_search_speakers(
            season=season_config.name,
            region=region,
            sports=season_config.sports,
            sources=enriched,
            settings=settings,
            strict_region=False,
        )

    return result
