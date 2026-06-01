"""Schema migration + row claim/lock for deep_analyzer."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIGRATION_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS discord_analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmark_id     TEXT NOT NULL REFERENCES discord_bookmarks(message_id),
    artifact_type   TEXT    NOT NULL,
    summary         TEXT    NOT NULL,
    structured_json TEXT    NOT NULL,
    vault_path      TEXT,
    gbrain_chunk_ids TEXT,
    model_used      TEXT,
    cost_usd        REAL    DEFAULT 0,
    error_text      TEXT,
    retries         INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_discord_analyses_bookmark
    ON discord_analyses(bookmark_id);

CREATE INDEX IF NOT EXISTS idx_discord_analyses_created
    ON discord_analyses(created_at);
"""

CLAIM_STALE_SECONDS = 600  # 10 minutes


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def migrate(db_path: Path | str) -> None:
    """Apply additive schema migration. Idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        for col, ddl in [
            ("analyzed_at", "ALTER TABLE discord_bookmarks ADD COLUMN analyzed_at TIMESTAMP"),
            ("claimed_at", "ALTER TABLE discord_bookmarks ADD COLUMN claimed_at TIMESTAMP"),
            ("analysis_id", "ALTER TABLE discord_bookmarks ADD COLUMN analysis_id INTEGER"),
        ]:
            if not _has_column(conn, "discord_bookmarks", col):
                conn.execute(ddl)
        conn.executescript(MIGRATION_SQL)
        conn.commit()
        logger.info("deep_analyzer.storage: migration applied to %s", db_path)
    finally:
        conn.close()


def pick_unanalyzed(db_path: Path | str, limit: int = 5) -> list[dict[str, Any]]:
    """Return up to `limit` unanalyzed and unclaimed (or stale-claimed) rows."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM discord_bookmarks
            WHERE analyzed_at IS NULL
              AND (claimed_at IS NULL
                   OR claimed_at < datetime('now', '-{CLAIM_STALE_SECONDS} seconds'))
            ORDER BY posted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def claim_rows(db_path: Path | str, message_ids: list[str]) -> int:
    """Mark rows as claimed_at = now(). Returns rowcount."""
    if not message_ids:
        return 0
    placeholders = ",".join("?" * len(message_ids))
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            f"UPDATE discord_bookmarks SET claimed_at = datetime('now') "
            f"WHERE message_id IN ({placeholders})",
            message_ids,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def insert_analysis(
    db_path: Path | str,
    *,
    bookmark_id: str,
    artifact_type: str,
    summary: str,
    structured_json: dict,
    vault_path: str | None = None,
    gbrain_chunk_ids: list[str] | None = None,
    model_used: str | None = None,
    cost_usd: float = 0.0,
    error_text: str | None = None,
    retries: int = 0,
) -> int:
    """Insert an analysis row. Returns the new id."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO discord_analyses
              (bookmark_id, artifact_type, summary, structured_json, vault_path,
               gbrain_chunk_ids, model_used, cost_usd, error_text, retries)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bookmark_id,
                artifact_type,
                summary,
                json.dumps(structured_json),
                vault_path,
                json.dumps(gbrain_chunk_ids or []),
                model_used,
                cost_usd,
                error_text,
                retries,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def mark_analyzed(db_path: Path | str, bookmark_id: str, analysis_id: int) -> None:
    """Finalize a row — sets analyzed_at = now() and links analysis_id."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE discord_bookmarks SET analyzed_at = datetime('now'), analysis_id = ? "
            "WHERE message_id = ?",
            (analysis_id, bookmark_id),
        )
        conn.commit()
    finally:
        conn.close()


def daily_cost_usd(db_path: Path | str) -> float:
    """SUM of today's cost_usd."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM discord_analyses "
            "WHERE date(created_at) = date('now')"
        ).fetchone()
        return float(row[0])
    finally:
        conn.close()
