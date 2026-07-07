"""
Regression tests for the 2026-05-11 commentary extraction silent-failure bug.

Root cause: _load_from_cache returned poisoned rows (data_quality='none' with
message_count > 0). These rows were written during an Anthropic billing outage
on 2026-05-12 and permanently suppressed re-extraction for 2026-05-11, even
after billing was restored. 28 messages of explicit bullish commentary were
present but get_session_bias always returned neutral because the poisoned row
was served from cache without re-attempting the LLM.

Fix: _load_from_cache evicts any row where data_quality='none' AND
message_count > 0, treating it as a prior LLM failure that should be retried.

These tests pin that contract. They also guard:
- Visible WARNING log on any neutral-degradation event
- Correct CT-timezone-aware date window (timestamps stored as -05:00 offset)
- Both market-updates and general channels feeding the extractor

All tests use a temp-file DB (not :memory:) so the processor and test code
share the same SQLite connection pool — required because each sqlite3.connect
call on ':memory:' opens a fresh ephemeral DB.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from discord.commentary_processor import CoreyCommentaryProcessor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Representative May 11 bullish content (captures the gap-fill scenario,
# buyer dominance, 7452/7480 price targets visible in the drawdown analysis)
MAY_11_MESSAGES = [
    {
        "content": (
            "MES gap fill scenario above 5820 - buyers initiating from overnight low. "
            "Expect price to work toward 5865 if we accept above 5840. "
            "TPO profile shows strong buyer dominance; initiative buying continuing from "
            "yesterday's value area. Target 7452 first, then extension to 7480 on volume."
        ),
        "timestamp": "2026-05-11T08:23:38.142-05:00",
        "channel": "market-updates",
        "author_id": "564449478174703646",
    },
    {
        "content": (
            "Buyers holding above POC - bullish continuation setup if IB holds. "
            "Strong bid presence. Auction higher likely into afternoon session. "
            "Above VAH = acceptance and breakout target 7480 confirmed."
        ),
        "timestamp": "2026-05-11T08:23:47.457-05:00",
        "channel": "market-updates",
        "author_id": "564449478174703646",
    },
    {
        "content": (
            "Gap fill complete, initiative buying resumes. Buyers clearly in control. "
            "Long bias above 5840 support - upside target 5865 / 5890. "
            "IB bias above VAH, bullish breakout scenario active."
        ),
        "timestamp": "2026-05-11T09:00:12.814-05:00",
        "channel": "general",
        "author_id": "564449478174703646",
    },
    {
        "content": (
            "Demand zone held perfectly. Buyers defending 5840 strongly. "
            "Bullish structure intact - breakout above IB high expected if price "
            "accepts above 5855. Strong upside conviction."
        ),
        "timestamp": "2026-05-11T10:15:30.000-05:00",
        "channel": "general",
        "author_id": "564449478174703646",
    },
]

BEARISH_MESSAGES = [
    {
        "content": (
            "Sellers initiating below POC. Breakdown below VAL - auction lower expected. "
            "Short bias. Supply zone holding at 5800. Distribution pattern forming. "
            "Downside target 5760 if 5790 fails."
        ),
        "timestamp": "2026-05-08T08:30:00.000-05:00",
        "channel": "market-updates",
        "author_id": "564449478174703646",
    },
    {
        "content": (
            "Rejection at resistance - sellers in control. Fade the bounce. "
            "Below VAH means we stay bearish. Offer side dominating. "
            "Downside scenario: break 5790 -> 5760 -> 5740."
        ),
        "timestamp": "2026-05-08T09:00:00.000-05:00",
        "channel": "general",
        "author_id": "564449478174703646",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_temp_db(rows: list[dict]) -> str:
    """
    Write a temp SQLite file pre-seeded with discord_corey_commentary rows.
    Returns the file path. Caller is responsible for cleanup (os.unlink).

    Uses a real file (not :memory:) so the processor and test code share
    the same DB — each sqlite3.connect(':memory:') opens a separate ephemeral
    DB, which means the processor can't see rows seeded by the test.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_corey_commentary (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id      TEXT    UNIQUE NOT NULL,
                timestamp       TEXT    NOT NULL,
                content         TEXT    NOT NULL,
                channel         TEXT    NOT NULL,
                author_id       TEXT    NOT NULL DEFAULT '564449478174703646',
                created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
            )
        """
        )
        for i, r in enumerate(rows):
            conn.execute(
                "INSERT OR IGNORE INTO discord_corey_commentary "
                "(message_id, timestamp, content, channel, author_id) VALUES (?,?,?,?,?)",
                (
                    f"msg_{i}",
                    r["timestamp"],
                    r["content"],
                    r["channel"],
                    r.get("author_id", "564449478174703646"),
                ),
            )
        conn.commit()
    return path


def _seed_poisoned_cache(db_path: str, target_date: str, message_count: int = 28) -> None:
    """Insert a poisoned cache row (data_quality='none', message_count > 0)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS corey_session_bias (
                date TEXT PRIMARY KEY,
                session_type TEXT NOT NULL,
                directional_bias TEXT NOT NULL,
                key_levels_json TEXT NOT NULL DEFAULT '[]',
                ib_bias TEXT NOT NULL DEFAULT 'not_mentioned',
                triggers_json TEXT NOT NULL DEFAULT '[]',
                conviction REAL NOT NULL DEFAULT 0.0,
                corey_quote TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                data_quality TEXT NOT NULL DEFAULT 'none',
                computed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO corey_session_bias
            (date, session_type, directional_bias, key_levels_json,
             ib_bias, triggers_json, conviction, corey_quote,
             message_count, data_quality, computed_at)
            VALUES (?, 'uncertain', 'neutral', '[]',
                    'not_mentioned', '[]', 0.0, '', ?, 'none',
                    '2026-05-12T04:55:35')
            """,
            (target_date, message_count),
        )
        conn.commit()


def _make_success_client(bias: str = "bullish") -> MagicMock:
    """
    Build an httpx.AsyncClient mock whose .post() returns a valid LLM JSON response.

    The response object must be a plain MagicMock (not AsyncMock) because the
    code calls resp.json() synchronously after await client.post(...).
    """
    import json as _json

    llm_text = _json.dumps(
        {
            "session_type": "trend_day",
            "directional_bias": bias,
            "key_levels": [5840.0, 5865.0, 7452.0, 7480.0],
            "ib_bias": "above_ib",
            "specific_triggers": ["long above 5840 if IB holds", "target 7480"],
            "conviction": 0.85,
            "corey_quote": "Buyers clearly in control above 5840",
        }
    )
    payload = {"content": [{"text": llm_text}]}
    # resp must NOT be AsyncMock — resp.json() is called synchronously in the code
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()  # no-op

    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _make_failing_client(exc: Exception) -> MagicMock:
    """Build an httpx.AsyncClient mock whose .post() raises exc."""
    client = AsyncMock()
    client.post.side_effect = exc
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


# ---------------------------------------------------------------------------
# Test 1 — 2026-05-11 regression: poisoned cache is evicted, LLM re-runs
# ---------------------------------------------------------------------------


async def test_2026_05_11_regression_evicts_poisoned_cache_and_extracts_bullish():
    """
    Regression: a poisoned cache row (data_quality='none', message_count=28)
    for 2026-05-11 must be evicted and re-extracted as bullish.

    Before the fix: _load_from_cache returned the poisoned row immediately,
    bypassing _llm_extract entirely. directional_bias was always 'neutral'.

    After the fix: the poisoned row is evicted, _llm_extract is called with
    the 4 fixture messages, and directional_bias reflects the bullish content.
    """
    db_path = _make_temp_db(MAY_11_MESSAGES)
    try:
        _seed_poisoned_cache(db_path, "2026-05-11", message_count=28)

        proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db_path)

        with patch(
            "discord.commentary_processor.httpx.AsyncClient",
            return_value=_make_success_client("bullish"),
        ):
            result = await proc.get_session_bias(date(2026, 5, 11))

        assert result.directional_bias == "bullish", (
            f"Expected 'bullish' after poisoned cache eviction, got '{result.directional_bias}'. "
            f"data_quality={result.data_quality}, message_count={result.message_count}. "
            "Root cause: _load_from_cache returned stale 'none' row from 2026-05-12 billing outage."
        )
        assert result.data_quality in (
            "fresh",
            "stale",
        ), f"Expected fresh/stale after successful LLM, got '{result.data_quality}'"
        assert result.message_count == len(MAY_11_MESSAGES)
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 2 — WARNING log emitted whenever extraction degrades to neutral
# ---------------------------------------------------------------------------


async def test_extractor_logs_warning_when_returning_neutral(caplog):
    """
    Any LLM failure that causes data_quality='none' must emit a WARNING-level
    log. Silent degradation is the bug — visible logs let ops catch it.
    """
    import httpx

    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    fake_resp = MagicMock(status_code=400)
    http_400 = httpx.HTTPStatusError(
        "credit balance too low", request=MagicMock(), response=fake_resp
    )

    with caplog.at_level(logging.WARNING, logger="discord.commentary_processor"):
        with patch(
            "discord.commentary_processor.httpx.AsyncClient",
            return_value=_make_failing_client(http_400),
        ):
            result = await proc._llm_extract(date(2026, 5, 11), [MAY_11_MESSAGES[0]])

    assert result.data_quality == "none"
    assert result.directional_bias == "neutral"

    warning_records = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "DEGRADED TO NEUTRAL" in r.message
    ]
    assert warning_records, (
        "Expected at least one WARNING log containing 'DEGRADED TO NEUTRAL' when "
        f"extraction fails. Logs captured: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Date window correctly picks up CT-timestamped rows for the date
# ---------------------------------------------------------------------------


async def test_date_window_matches_ct_stored_timestamps():
    """
    Timestamps are stored with -05:00 (CT) offset in the DB.
    SQLite DATE('2026-05-11T08:23:38.142-05:00') returns '2026-05-11'.
    The _fetch_commentary query uses DATE(timestamp) = date_str, which
    correctly matches CT-offset rows without any UTC conversion.

    Pins that all 4 May 11 fixture messages (stored 08:23-10:15 CT) are
    fetched when requesting date(2026, 5, 11).
    """
    db_path = _make_temp_db(MAY_11_MESSAGES)
    try:
        proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db_path)
        rows = proc._fetch_commentary(date(2026, 5, 11))

        assert len(rows) == len(MAY_11_MESSAGES), (
            f"Expected {len(MAY_11_MESSAGES)} rows for 2026-05-11, got {len(rows)}. "
            "Timezone handling may be broken - check DATE(timestamp) with -05:00 offset."
        )

        # Verify rows are returned ASC (oldest first)
        timestamps = [r["timestamp"] for r in rows]
        assert timestamps == sorted(timestamps), "Rows should be in ASC timestamp order"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 4 — Both market-updates and general channels are fetched
# ---------------------------------------------------------------------------


async def test_handles_both_market_updates_and_general_channels():
    """
    Corey posts in both market-updates (exact match) and general
    (filter: channel='general' AND author_id=TATHEDOG). Both must feed the extractor.

    Fixture has 2 market-updates rows and 2 general rows - all 4 fetched.
    """
    db_path = _make_temp_db(MAY_11_MESSAGES)
    try:
        proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db_path)
        rows = proc._fetch_commentary(date(2026, 5, 11))

        market_updates = [r for r in rows if r["channel"] == "market-updates"]
        general = [r for r in rows if r["channel"] == "general"]

        assert (
            len(market_updates) >= 2
        ), f"Expected >= 2 market-updates rows, got {len(market_updates)}"
        assert len(general) >= 2, f"Expected >= 2 general (tathedog) rows, got {len(general)}"
        assert len(rows) == len(
            MAY_11_MESSAGES
        ), f"Expected all {len(MAY_11_MESSAGES)} messages, got {len(rows)}"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 5 — Genuine no-data cache row (message_count=0) is NOT evicted
# ---------------------------------------------------------------------------


async def test_genuine_no_data_cache_row_is_not_evicted():
    """
    A cached row with data_quality='none' AND message_count=0 means there really
    was no Corey commentary for that date. This is a valid stable answer and must
    NOT be evicted - evicting it would cause needless DB scans every pipeline call.
    """
    db_path = _make_temp_db([])  # empty - no commentary rows
    try:
        _seed_poisoned_cache(db_path, "2026-03-15", message_count=0)

        proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db_path)
        result = proc._load_from_cache(date(2026, 3, 15))

        assert result is not None, (
            "Cache row with message_count=0 should be returned as-is (genuine no-data day). "
            "Evicting it causes needless re-scans for dates with no commentary."
        )
        assert result.data_quality == "none"
        assert result.message_count == 0
        assert result.directional_bias == "neutral"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 6 — Bearish detection on a different date
# ---------------------------------------------------------------------------


async def test_bearish_commentary_detected_correctly():
    """
    Confirm extraction works for a bearish day. Uses May 8 bearish fixture.
    Guards against a regression where the LLM path only returns bullish.
    """
    db_path = _make_temp_db(BEARISH_MESSAGES)
    try:
        proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db_path)

        with patch(
            "discord.commentary_processor.httpx.AsyncClient",
            return_value=_make_success_client("bearish"),
        ):
            result = await proc._llm_extract(date(2026, 5, 8), BEARISH_MESSAGES)

        assert (
            result.directional_bias == "bearish"
        ), f"Expected 'bearish' for bearish fixture, got '{result.directional_bias}'"
        assert result.data_quality in ("fresh", "stale")
        assert result.message_count == len(BEARISH_MESSAGES)
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
