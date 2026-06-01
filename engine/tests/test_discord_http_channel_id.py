"""Regression tests for the `channel_id` schema patch on `/discord/*` routes.

Covers (per agent-35 design + agent-48 patch):
  - /discord/bookmarks/recent: channel_id is populated AND filterable
  - /discord/bookmarks/search: channel_id is populated AND filterable
  - /discord/signals: channel_id field present (None) and accepted as query param (no-op)
  - /discord/ib-reports: channel_id field present (None) and accepted as query param (no-op)
  - /discord/corey-alerts: channel_id field present (None) and accepted as query param (no-op)
  - /discord/commentary: channel_id field present (None) and accepted as query param (no-op)

The four `slug-keyed` tables (discord_bot_signals, discord_ib_reports,
discord_corey_alerts, discord_corey_commentary) do not yet persist a
`channel_id` column, so the router selects `NULL AS channel_id` and accepts
the query param without applying it (documented as TODO inline). When the
slug->snowflake migration lands, those filters become real.

Test design:
  - Never touches the production DB.
  - Builds a tiny SQLite fixture in tmp_path with the four discord_* tables
    + discord_bookmarks, all seeded with deterministic rows.
  - Overrides the get_db_path dependency on the discord_router APIRouter
    so all queries hit the fixture DB.
  - Uses FastAPI TestClient against an app that mounts the router.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import discord_router

_JARVIS_CHANNEL = "1490851279180660819"
_OTHER_CHANNEL = "1234567890000000000"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed_db(db_path: str) -> None:
    """Create all discord_* tables and insert known fixture rows."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discord_bot_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT,
            direction TEXT,
            signal_type TEXT,
            entry_price REAL,
            target1 REAL, target2 REAL, stop1 REAL, stop2 REAL,
            win_rate REAL, wins INTEGER, losses INTEGER,
            mfe REAL, mae REAL, rr REAL, gain REAL, draw REAL, net REAL,
            last_price REAL, raw_description TEXT,
            source_channel TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS discord_ib_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT,
            ib_open REAL, ib_high REAL, ib_low REAL, ib_close REAL, ib_range REAL,
            ibu50 REAL, ibu100 REAL, ibd50 REAL, ibd100 REAL,
            auction_context TEXT, trade_plan TEXT, raw_content TEXT,
            source_channel TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS discord_corey_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT,
            timestamp TEXT NOT NULL,
            content TEXT, symbol TEXT, direction TEXT, price REAL,
            source_channel TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS discord_corey_commentary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT,
            timestamp TEXT NOT NULL,
            content TEXT,
            channel TEXT,
            author_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS discord_bookmarks (
            message_id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            url TEXT NOT NULL,
            domain TEXT,
            source_type TEXT,
            embed_title TEXT,
            embed_description TEXT,
            content TEXT,
            author_name TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    now = _now_utc()

    # Seed bot signals (slug-keyed, no channel_id column)
    conn.execute(
        "INSERT INTO discord_bot_signals (timestamp, symbol, direction, signal_type, source_channel) "
        "VALUES (?, ?, ?, ?, ?)",
        (_iso(now - timedelta(minutes=10)), "MES", "LONG", "ENTRY", "es"),
    )
    conn.execute(
        "INSERT INTO discord_ib_reports (timestamp, symbol, source_channel) " "VALUES (?, ?, ?)",
        (_iso(now - timedelta(minutes=20)), "MNQ", "nq"),
    )
    conn.execute(
        "INSERT INTO discord_corey_alerts (timestamp, content, symbol, source_channel) "
        "VALUES (?, ?, ?, ?)",
        (_iso(now - timedelta(minutes=30)), "scaling in MES", "MES", "general"),
    )
    conn.execute(
        "INSERT INTO discord_corey_commentary (timestamp, content, channel) " "VALUES (?, ?, ?)",
        (_iso(now - timedelta(minutes=40)), "watching auction levels", "market-updates"),
    )

    # Seed bookmarks across TWO channels — channel_id IS a real column here.
    bookmarks = [
        (
            "bm-1",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=1)),
            "https://x.com/a/1",
            "x.com",
            "x_post",
            "T1",
            "D1",
            "c1",
            "amo",
        ),
        (
            "bm-2",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=2)),
            "https://github.com/x/y",
            "github.com",
            "github",
            "T2",
            "D2",
            "c2",
            "amo",
        ),
        (
            "bm-3",
            _OTHER_CHANNEL,
            _iso(now - timedelta(hours=3)),
            "https://x.com/b/2",
            "x.com",
            "x_post",
            "T3",
            "D3",
            "c3",
            "amo",
        ),
    ]
    conn.executemany(
        "INSERT INTO discord_bookmarks "
        "(message_id, channel_id, posted_at, url, domain, source_type, "
        " embed_title, embed_description, content, author_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        bookmarks,
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Spin up a FastAPI app mounting discord_router against a fixture DB."""
    db_path = str(tmp_path / "test_discord_http.db")
    _seed_db(db_path)

    app = FastAPI()
    app.include_router(discord_router.router)
    # Override the get_db_path dependency to point at our fixture DB.
    app.dependency_overrides[discord_router.get_db_path] = lambda: db_path
    return TestClient(app)


# ---------------------------------------------------------------------------
# Bookmarks routes — channel_id is REAL (column exists, filter works)
# ---------------------------------------------------------------------------


def test_bookmarks_recent_returns_channel_id(client: TestClient) -> None:
    r = client.get("/discord/bookmarks/recent?hours=24")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 3
    for row in rows:
        assert "channel_id" in row
        assert row["channel_id"] in (_JARVIS_CHANNEL, _OTHER_CHANNEL)


def test_bookmarks_recent_filters_by_channel_id(client: TestClient) -> None:
    r = client.get(f"/discord/bookmarks/recent?hours=24&channel_id={_JARVIS_CHANNEL}")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 2
    assert all(row["channel_id"] == _JARVIS_CHANNEL for row in rows)


def test_bookmarks_recent_channel_id_no_match(client: TestClient) -> None:
    r = client.get("/discord/bookmarks/recent?hours=24&channel_id=999999999999999999")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_bookmarks_search_returns_and_filters_channel_id(client: TestClient) -> None:
    # Search for "T" (matches all 3 titles) with channel filter
    r = client.get(f"/discord/bookmarks/search?query=T&days=7&channel_id={_JARVIS_CHANNEL}")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 2
    assert all(row["channel_id"] == _JARVIS_CHANNEL for row in rows)


# ---------------------------------------------------------------------------
# Slug-keyed routes — channel_id is NULL today (TODO: slug->snowflake migration)
# ---------------------------------------------------------------------------


def test_signals_exposes_channel_id_as_null(client: TestClient) -> None:
    """`/discord/signals` should accept ?channel_id= and expose channel_id=null."""
    # Param accepted, no error
    r = client.get(f"/discord/signals?channel_id={_JARVIS_CHANNEL}&limit=10")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 1
    for row in rows:
        assert "channel_id" in row
        assert row["channel_id"] is None


def test_ib_reports_exposes_channel_id_as_null(client: TestClient) -> None:
    r = client.get(f"/discord/ib-reports?channel_id={_JARVIS_CHANNEL}&limit=10")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 1
    for row in rows:
        assert "channel_id" in row
        assert row["channel_id"] is None


def test_corey_alerts_exposes_channel_id_as_null(client: TestClient) -> None:
    r = client.get(f"/discord/corey-alerts?channel_id={_JARVIS_CHANNEL}&limit=10")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 1
    for row in rows:
        assert "channel_id" in row
        assert row["channel_id"] is None


def test_commentary_exposes_channel_id_as_null(client: TestClient) -> None:
    r = client.get(f"/discord/commentary?channel_id={_JARVIS_CHANNEL}&limit=10")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 1
    for row in rows:
        assert "channel_id" in row
        assert row["channel_id"] is None


def test_openapi_advertises_channel_id_param_on_all_six_routes(client: TestClient) -> None:
    """OpenAPI surface must list channel_id as a query parameter on each route."""
    schema = client.get("/openapi.json").json()
    routes_to_check = [
        "/discord/signals",
        "/discord/ib-reports",
        "/discord/corey-alerts",
        "/discord/commentary",
        "/discord/bookmarks/recent",
        "/discord/bookmarks/search",
    ]
    for path in routes_to_check:
        params = schema["paths"][path]["get"]["parameters"]
        names = [p["name"] for p in params]
        assert "channel_id" in names, f"channel_id missing from {path}: {names}"
