"""Tests for deep_analyzer.storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from discord.deep_analyzer import storage


def test_migrate_adds_columns_to_discord_bookmarks(tmp_db: Path):
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)")}
    conn.close()
    assert "analyzed_at" in cols
    assert "claimed_at" in cols
    assert "analysis_id" in cols


def test_migrate_creates_discord_analyses_table(tmp_db: Path):
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "discord_analyses" in tables


def test_migrate_is_idempotent(tmp_db: Path):
    storage.migrate(tmp_db)
    storage.migrate(tmp_db)  # second run must not raise
    conn = sqlite3.connect(tmp_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)")}
    conn.close()
    assert "analyzed_at" in cols


def test_pick_unanalyzed_returns_ids(seeded_db: Path):
    storage.migrate(seeded_db)
    rows = storage.pick_unanalyzed(seeded_db, limit=10)
    assert len(rows) == 3
    assert {r["message_id"] for r in rows} == {"m1", "m2", "m3"}


def test_pick_unanalyzed_respects_limit(seeded_db: Path):
    storage.migrate(seeded_db)
    rows = storage.pick_unanalyzed(seeded_db, limit=2)
    assert len(rows) == 2


def test_pick_unanalyzed_skips_recently_claimed(seeded_db: Path):
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.execute(
        "UPDATE discord_bookmarks SET claimed_at = datetime('now') WHERE message_id = 'm1'"
    )
    conn.commit()
    conn.close()
    rows = storage.pick_unanalyzed(seeded_db, limit=10)
    ids = {r["message_id"] for r in rows}
    assert "m1" not in ids
    assert ids == {"m2", "m3"}


def test_pick_unanalyzed_reclaims_stale(seeded_db: Path):
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    # 11 minutes ago — stale (threshold is 10 min)
    conn.execute(
        "UPDATE discord_bookmarks SET claimed_at = datetime('now', '-11 minutes') WHERE message_id = 'm1'"
    )
    conn.commit()
    conn.close()
    rows = storage.pick_unanalyzed(seeded_db, limit=10)
    assert "m1" in {r["message_id"] for r in rows}


def test_daily_cost_returns_sum(seeded_db: Path):
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.executemany(
        "INSERT INTO discord_analyses (bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'text', 's', '{}', ?)",
        [(0.50,), (0.30,)],
    )
    conn.commit()
    conn.close()
    assert storage.daily_cost_usd(seeded_db) == pytest.approx(0.80)
