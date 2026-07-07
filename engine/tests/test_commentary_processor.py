"""
Tests for CoreyCommentaryProcessor LLM-fallback path.

Bug being guarded: when the LLM call raises (e.g., HTTP 400 credit-balance,
transient httpx error), the prior fallback returned data_quality='fresh'
or 'stale' if rows were present — silently masking failure. Downstream
consumers in engine/analysis/discord_correlation.py filter
data_quality IN ('fresh','stale') and would include the content-empty row
in correlation queries, polluting signal with neutral/zero-conviction noise.

The fix: data_quality must always be 'none' on LLM exception, regardless of
whether rows were fetched. 'none' is the explicit "we have no LLM-extracted
bias for this date" sentinel.

Real-world incident: 2026-05-04 / 2026-05-05 corey_session_bias rows
showed data_quality='fresh' with conviction=0, neutral, content-empty
because the Anthropic API was returning HTTP 400 (credit-balance).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from discord.commentary_processor import (
    TATHEDOG_AUTHOR_ID,
    CoreyCommentaryProcessor,
    _neutral_bias,
)


def _make_failing_async_client(exc: Exception) -> MagicMock:
    """Build an httpx.AsyncClient mock whose .post() raises the given exception."""
    client = AsyncMock()
    client.post.side_effect = exc

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


async def test_llm_extract_returns_data_quality_none_on_http_400():
    """LLM HTTP 400 must yield data_quality='none' even with fresh rows present.

    This is the silent-regression guard. Before the fix, a fresh row + 4xx
    error returned data_quality='fresh' with empty content, which downstream
    correlation queries silently included as neutral signal.
    """
    fresh_rows = [
        {
            "content": "MES holding above 5800 — initiative buyers continuing",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": "market-updates",
        },
    ]

    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    fake_response = MagicMock(status_code=400)
    http_400 = httpx.HTTPStatusError(
        "credit balance too low",
        request=MagicMock(),
        response=fake_response,
    )

    with patch(
        "discord.commentary_processor.httpx.AsyncClient",
        return_value=_make_failing_async_client(http_400),
    ):
        result = await proc._llm_extract(date.today(), fresh_rows)

    assert result.data_quality == "none", (
        f"Expected data_quality='none' on LLM exception, got '{result.data_quality}'. "
        f"This is the silent-regression bug."
    )
    # Other fallback fields should still be the neutral defaults.
    assert result.directional_bias == "neutral"
    assert result.session_type == "uncertain"
    assert result.message_count == len(fresh_rows)
    assert result.conviction == 0.0
    assert result.corey_quote == ""
    assert result.key_levels == []
    assert result.specific_triggers == []


async def test_llm_extract_returns_data_quality_none_on_generic_exception():
    """Any LLM exception path (not just HTTP) must produce data_quality='none'."""
    rows = [
        {
            "content": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": "market-updates",
        },
    ]

    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    with patch(
        "discord.commentary_processor.httpx.AsyncClient",
        return_value=_make_failing_async_client(RuntimeError("network down")),
    ):
        result = await proc._llm_extract(date.today(), rows)

    assert result.data_quality == "none"
    assert result.message_count == 1


async def test_llm_extract_returns_data_quality_none_with_empty_rows():
    """Empty rows + LLM exception still produces 'none' (regression guard for
    the existing branch — this case was already correct pre-fix, but the
    test pins the contract so a future refactor can't reintroduce drift)."""
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    # _llm_extract uses rows[-1] for date computation; with empty rows, the
    # function takes the for_date branch, so this exercises the path where
    # rows is [] but data_quality is still computed before the LLM call.
    with patch(
        "discord.commentary_processor.httpx.AsyncClient",
        return_value=_make_failing_async_client(RuntimeError("boom")),
    ):
        result = await proc._llm_extract(date.today(), [])

    assert result.data_quality == "none"
    assert result.message_count == 0


async def test_get_session_bias_skips_cache_on_llm_failure_with_rows():
    """When LLM fails but commentary rows exist, the failure must NOT be cached.

    Bug: previously, a single Anthropic 400 (credit balance) at the start of the
    day cached data_quality='none' against the date PK, so even after billing
    was restored mid-session the cached neutral persisted until midnight. The
    fix skips the cache write when (data_quality == "none" AND rows > 0); the
    "no rows for the date" branch above still caches because the answer is
    truthful and stable.
    """
    fresh_rows = [
        {
            "content": "MES holding above 5800",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": "market-updates",
        }
    ]
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    with (
        patch.object(proc, "_fetch_commentary", return_value=fresh_rows),
        patch.object(proc, "_save_to_cache") as save_mock,
        patch.object(
            proc, "_llm_extract", new=AsyncMock(side_effect=lambda d, r: _failure_result(d, len(r)))
        ),
    ):
        result = await proc.get_session_bias(date.today())

    assert result.data_quality == "none"
    assert result.message_count == 1
    save_mock.assert_not_called()


async def test_get_session_bias_still_caches_no_rows_branch():
    """Counterpart: the 'no commentary anywhere' branch must still cache.

    Caching here is the right behavior — the answer (no data) is stable for the
    day and avoids repeated DB scans on every pipeline call.
    """
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    with (
        patch.object(proc, "_fetch_commentary", return_value=[]),
        patch.object(proc, "_fetch_recent_commentary", return_value=([], date.today())),
        patch.object(proc, "_save_to_cache") as save_mock,
    ):
        result = await proc.get_session_bias(date.today())

    assert result.data_quality == "none"
    assert result.message_count == 0
    save_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Stale "no-data" cache eviction (backfilled commentary) — bug fix #1.
#
# A none/msgs=0 cache row records "no commentary existed at compute time". But
# #market-updates ingestion can backfill a date hours later (or after a
# multi-day ingestion gap). The old _load_from_cache trusted msgs=0 rows as
# permanently stable, so the directional read was never recovered and corey's
# signal stayed 0.0 forever — starving the IC calibration (corey-IC=0,
# ready=False). These tests pin the recheck-and-evict behavior.
# ---------------------------------------------------------------------------


def _seed_commentary_table(db_path: str) -> None:
    """Create the discord_corey_commentary table matching the live schema fields
    that _fetch_commentary / _count_commentary filter on."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_corey_commentary (
                content   TEXT,
                timestamp TEXT,
                channel   TEXT,
                author_id TEXT
            )
            """
        )
        conn.commit()


def _insert_market_update(db_path: str, for_date: date, content: str = "MES bid") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO discord_corey_commentary (content, timestamp, channel, author_id) "
            "VALUES (?, ?, 'market-updates', NULL)",
            (content, f"{for_date.isoformat()}T14:30:00+00:00"),
        )
        conn.commit()


def test_load_from_cache_evicts_stale_no_data_when_commentary_backfilled(tmp_path):
    """A cached none/msgs=0 row must be evicted once commentary is ingested for
    that date — the row is stale, not 'stable no data'. Eviction returns None so
    get_session_bias re-extracts the real directional bias."""
    db = str(tmp_path / "jarvis_trader.db")
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db)  # creates cache table
    _seed_commentary_table(db)

    d = date(2026, 6, 24)
    # Cache the premature neutral (computed when ingestion hadn't caught up).
    proc._save_to_cache(_neutral_bias(d, message_count=0))
    # Commentary is backfilled afterward.
    _insert_market_update(db, d)

    result = proc._load_from_cache(d)

    assert result is None, "stale none/msgs=0 row should be evicted once commentary exists"
    # Row is gone from the table (forces re-extraction on next get_session_bias).
    with sqlite3.connect(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM corey_session_bias WHERE date = ?", (d.isoformat(),)
        ).fetchone()[0]
    assert n == 0, "evicted row should be deleted from cache"


def test_load_from_cache_keeps_no_data_when_still_empty(tmp_path):
    """Counterpart: a genuinely-empty day (no commentary, e.g. weekend/holiday)
    keeps its cached neutral and is NOT evicted — the answer is stable, and we
    must not thrash the LLM on every pipeline call for a day that will never
    have data."""
    db = str(tmp_path / "jarvis_trader.db")
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db)
    _seed_commentary_table(db)  # table exists but holds no rows for the date

    d = date(2026, 6, 20)
    proc._save_to_cache(_neutral_bias(d, message_count=0))

    result = proc._load_from_cache(d)

    assert result is not None, "stable no-data row must be returned, not evicted"
    assert result.data_quality == "none"
    assert result.message_count == 0
    assert result.directional_bias == "neutral"


def test_load_from_cache_evict_recheck_tolerates_missing_commentary_table(tmp_path):
    """If the commentary table is absent (fresh/standalone DB), the recheck must
    not raise — it degrades to 'still empty' and returns the cached row."""
    db = str(tmp_path / "jarvis_trader.db")
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db)
    # Deliberately do NOT create discord_corey_commentary.

    d = date(2026, 6, 20)
    proc._save_to_cache(_neutral_bias(d, message_count=0))

    result = proc._load_from_cache(d)  # must not raise

    assert result is not None
    assert result.data_quality == "none"


def test_purge_stale_no_data_cache_evicts_only_backfilled_dates(tmp_path):
    """Maintenance sweep: purge_stale_no_data_cache evicts none/msgs=0 rows whose
    date now has commentary, and leaves genuinely-empty dates alone."""
    db = str(tmp_path / "jarvis_trader.db")
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db)
    _seed_commentary_table(db)

    backfilled = date(2026, 6, 24)  # has commentary now
    still_empty = date(2026, 6, 20)  # weekend / no posts
    proc._save_to_cache(_neutral_bias(backfilled, message_count=0))
    proc._save_to_cache(_neutral_bias(still_empty, message_count=0))
    _insert_market_update(db, backfilled)

    evicted = proc.purge_stale_no_data_cache()

    assert evicted == [backfilled.isoformat()]
    with sqlite3.connect(db) as conn:
        remaining = {r[0] for r in conn.execute("SELECT date FROM corey_session_bias").fetchall()}
    assert backfilled.isoformat() not in remaining, "backfilled stale row should be purged"
    assert still_empty.isoformat() in remaining, "genuinely-empty date must be retained"


def test_purge_stale_no_data_cache_ignores_directional_and_poisoned_rows(tmp_path):
    """The sweep only touches none/msgs=0 rows — directional (fresh) rows and
    poisoned (none/msgs>0) rows are out of scope and left for the per-call path."""
    from discord.commentary_processor import CoreySessionBias

    db = str(tmp_path / "jarvis_trader.db")
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=db)
    _seed_commentary_table(db)

    directional = date(2026, 6, 25)
    proc._save_to_cache(
        CoreySessionBias(
            date=directional,
            session_type="range_day",
            directional_bias="bearish",
            key_levels=[],
            ib_bias="below_ib",
            specific_triggers=[],
            conviction=0.65,
            corey_quote="fading the high",
            message_count=62,
            data_quality="fresh",
        )
    )
    _insert_market_update(db, directional)  # commentary present, but row is directional

    evicted = proc.purge_stale_no_data_cache()

    assert evicted == [], "directional/fresh rows must not be purged"
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM corey_session_bias").fetchone()[0]
    assert n == 1


def _failure_result(for_date, n_rows):
    """Build the same neutral-with-none result the real _llm_extract returns on exception."""
    from discord.commentary_processor import CoreySessionBias

    return CoreySessionBias(
        date=for_date,
        session_type="uncertain",
        directional_bias="neutral",
        key_levels=[],
        ib_bias="not_mentioned",
        specific_triggers=[],
        conviction=0.0,
        corey_quote="",
        message_count=n_rows,
        data_quality="none",
    )
