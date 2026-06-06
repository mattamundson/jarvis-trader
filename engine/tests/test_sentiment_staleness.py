"""Tests for Task 4 — futures-sentiment staleness observability.

get_futures_sentiment_staleness reports the age + quality of the Corey
#market-updates feed (the sole sanctioned futures-sentiment source) so a frozen
feed — which previously degraded MES/MNQ/MCL/MGC decisions silently — is visible
in /health. The decision path itself is already protected: corey_auction_analyst
caps confidence at 0.4 on data_quality=='stale' and falls through to neutral
beyond 7 days; this adds the missing "is the feed down?" signal.
"""
import sqlite3
from datetime import date, timedelta

import pytest

from database.migrations import run_migrations
from discord.commentary_processor import (
    CoreyCommentaryProcessor,
    get_futures_sentiment_staleness,
)


def _seed(path: str, days_ago: int, channel: str = "market-updates", mid: str = "m1"):
    ts = (date.today() - timedelta(days=days_ago)).isoformat() + "T12:00:00+00:00"
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO discord_corey_commentary (message_id, timestamp, content, channel) "
        "VALUES (?,?,?,?)",
        (mid, ts, "hello", channel),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "j.db")
    c = sqlite3.connect(p)
    run_migrations(c)
    c.close()
    return p


def test_unknown_when_empty(db):
    r = get_futures_sentiment_staleness(db)
    assert r["quality"] == "unknown"
    assert r["age_days"] is None
    assert r["threshold_days"] == CoreyCommentaryProcessor.STALE_DAYS


def test_fresh_today(db):
    _seed(db, 0)
    r = get_futures_sentiment_staleness(db)
    assert r["quality"] == "fresh"
    assert r["age_days"] == 0


def test_stale_when_old(db):
    _seed(db, 11)
    r = get_futures_sentiment_staleness(db)
    assert r["quality"] == "stale"
    assert r["age_days"] == 11


def test_boundary_at_threshold_is_fresh(db):
    _seed(db, CoreyCommentaryProcessor.STALE_DAYS)  # exactly threshold -> still fresh
    r = get_futures_sentiment_staleness(db)
    assert r["quality"] == "fresh"


def test_ignores_general_channel(db):
    _seed(db, 0, channel="general", mid="g1")  # newer but wrong channel
    _seed(db, 11, channel="market-updates", mid="mu1")
    r = get_futures_sentiment_staleness(db)
    assert r["age_days"] == 11
    assert r["quality"] == "stale"


def test_missing_table_is_unknown(tmp_path):
    p = str(tmp_path / "bare.db")
    sqlite3.connect(p).close()  # empty DB, no table
    r = get_futures_sentiment_staleness(p)  # must not raise
    assert r["quality"] == "unknown"
