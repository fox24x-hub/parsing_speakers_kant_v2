from __future__ import annotations

import json
import logging
import os
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    season      TEXT    NOT NULL,
    region      TEXT    NOT NULL,
    sports      TEXT    NOT NULL,   -- JSON array
    status      TEXT    NOT NULL DEFAULT 'running',  -- running | done | failed
    user_id     INTEGER
);

CREATE TABLE IF NOT EXISTS raw_candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    sport       TEXT,
    location    TEXT,
    expertise   TEXT,
    url         TEXT,
    contact     TEXT,
    format      TEXT,
    score            REAL,   -- 0-100, выставляется AI ranker
    score_explanation TEXT,  -- объяснение оценки от AI ranker
    source_json      TEXT    -- исходный dict от LLM, как JSON
);

CREATE TABLE IF NOT EXISTS approved_speakers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES raw_candidates(id) ON DELETE CASCADE,
    approved_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    approved_by  INTEGER  -- telegram user_id модератора
);
"""


async def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        # migration: add score_explanation if missing (for existing DBs)
        try:
            await db.execute("ALTER TABLE raw_candidates ADD COLUMN score_explanation TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists
    logger.info("DB initialised at %s", db_path)


async def update_candidate_score(
    db_path: str,
    candidate_id: int,
    score: float,
    explanation: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE raw_candidates SET score=?, score_explanation=? WHERE id=?",
            (score, explanation, candidate_id),
        )
        await db.commit()


async def create_run(
    db_path: str,
    *,
    season: str,
    region: str,
    sports: list[str],
    user_id: int | None = None,
) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "INSERT INTO search_runs (season, region, sports, status, user_id) VALUES (?,?,?,?,?)",
            (season, region, json.dumps(sports, ensure_ascii=False), "running", user_id),
        )
        await db.commit()
        return cur.lastrowid  # type: ignore[return-value]


async def finish_run(db_path: str, run_id: int, *, ok: bool) -> None:
    status = "done" if ok else "failed"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE search_runs SET status=? WHERE id=?",
            (status, run_id),
        )
        await db.commit()


async def save_candidates(
    db_path: str,
    run_id: int,
    speakers: list[dict[str, Any]],
) -> list[int]:
    """Сохраняет список спикеров из LLM и возвращает их id."""
    ids: list[int] = []
    async with aiosqlite.connect(db_path) as db:
        for sp in speakers:
            cur = await db.execute(
                """INSERT INTO raw_candidates
                   (run_id, name, sport, location, expertise, url, contact, format, source_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    sp.get("name", ""),
                    sp.get("sport"),
                    sp.get("location"),
                    sp.get("expertise"),
                    sp.get("url"),
                    sp.get("contact"),
                    sp.get("format"),
                    json.dumps(sp, ensure_ascii=False),
                ),
            )
            ids.append(cur.lastrowid)  # type: ignore[arg-type]
        await db.commit()
    return ids


async def approve_candidate(
    db_path: str,
    candidate_id: int,
    approved_by: int | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO approved_speakers (candidate_id, approved_by) VALUES (?,?)",
            (candidate_id, approved_by),
        )
        await db.commit()


async def reject_candidate(db_path: str, candidate_id: int) -> None:
    """Мягкое отклонение — помечаем score=-1, одобрение не создаём."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE raw_candidates SET score=-1 WHERE id=?",
            (candidate_id,),
        )
        await db.commit()


async def get_pending_candidates(db_path: str, run_id: int) -> list[dict[str, Any]]:
    """Кандидаты из прогона, у которых нет approved и score != -1."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT rc.*
               FROM raw_candidates rc
               LEFT JOIN approved_speakers ap ON ap.candidate_id = rc.id
               WHERE rc.run_id = ?
                 AND ap.id IS NULL
                 AND (rc.score IS NULL OR rc.score >= 0)
               ORDER BY COALESCE(rc.score, -1) DESC, rc.id""",
            (run_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_latest_run_id(db_path: str, user_id: int) -> int | None:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id FROM search_runs WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def get_approved_speakers(db_path: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT rc.*, ap.approved_at, ap.approved_by
               FROM approved_speakers ap
               JOIN raw_candidates rc ON rc.id = ap.candidate_id
               ORDER BY ap.approved_at DESC""",
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
