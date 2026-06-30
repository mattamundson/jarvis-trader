"""
Tests for get_bias_extraction_health — detects a stalled Corey structured-bias
LLM extraction while raw commentary keeps flowing.

Why this exists: get_futures_sentiment_staleness only checks INGESTION freshness.
On 2026-06-29 the direct-Anthropic account's credit was exhausted; commentary kept
ingesting fine, but every structured session_bias degraded to data_quality='none'
for two days — invisible to /health. This detector compares the latest
market-updates commentary date against the latest date with a fresh/stale cached
bias and flags 'degraded' when extraction falls >= 2 days behind ingestion.
"""

from __future__ import annotations

import sqlite3

from discord.commentary_processor import (
    CoreyCommentaryProcessor,
    get_bias_extraction_health,
)


def _seed(db_path, commentary_dates, bias_rows):
    """commentary_dates: list[str]; bias_rows: list[(date_str, data_quality)]."""
    # corey_session_bias table is created by the processor's __init__.
    CoreyCommentaryProcessor(db_path=str(db_path))
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS discord_corey_commentary ("
            "id INTEGER PRIMARY KEY, message_id TEXT, timestamp TEXT, "
            "content TEXT, channel TEXT, author_id TEXT)"
        )
        for d in commentary_dates:
            conn.execute(
                "INSERT INTO discord_corey_commentary (message_id, timestamp, content, channel) "
                "VALUES (?, ?, ?, 'market-updates')",
                (f"m{d}", f"{d}T08:00:00-05:00", "ES holding above 7475"),
            )
        for d, q in bias_rows:
            conn.execute(
                "INSERT OR REPLACE INTO corey_session_bias "
                "(date, session_type, directional_bias, data_quality) VALUES (?, 'range_day', 'neutral', ?)",
                (d, q),
            )
        conn.commit()


def test_extraction_ok_when_bias_current_with_commentary(tmp_path):
    db = tmp_path / "j.db"
    _seed(db, ["2026-06-30"], [("2026-06-30", "fresh")])
    r = get_bias_extraction_health(str(db))
    assert r["extraction_quality"] == "ok"
    assert r["lag_days"] == 0


def test_extraction_degraded_when_bias_lags_commentary(tmp_path):
    """The exact 2026-06-29 incident: commentary through 06-30, bias stuck at 06-28."""
    db = tmp_path / "j.db"
    _seed(db, ["2026-06-28", "2026-06-29", "2026-06-30"], [("2026-06-28", "fresh")])
    r = get_bias_extraction_health(str(db))
    assert r["extraction_quality"] == "degraded"
    assert r["lag_days"] == 2


def test_extraction_degraded_when_commentary_but_no_bias_ever(tmp_path):
    db = tmp_path / "j.db"
    _seed(db, ["2026-06-30"], [])
    r = get_bias_extraction_health(str(db))
    assert r["extraction_quality"] == "degraded"


def test_extraction_unknown_when_no_commentary(tmp_path):
    db = tmp_path / "j.db"
    _seed(db, [], [])
    r = get_bias_extraction_health(str(db))
    assert r["extraction_quality"] == "unknown"


def test_extraction_health_never_raises_on_missing_db(tmp_path):
    r = get_bias_extraction_health(str(tmp_path / "does_not_exist.db"))
    assert r["extraction_quality"] == "unknown"


def test_extraction_health_ignores_none_quality_bias(tmp_path):
    """A cached 'none' row must NOT count as a successful extraction."""
    db = tmp_path / "j.db"
    _seed(db, ["2026-06-29", "2026-06-30"], [("2026-06-30", "none")])
    r = get_bias_extraction_health(str(db))
    assert r["extraction_quality"] == "degraded"
