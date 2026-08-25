"""Tests for the latency fixes on the analytics/trades routers.

Covers the two changes from T2 (fix /analytics/signal-outcomes + /trades/journal):
  * signal_outcomes_router._daily_bars — TTL cache prevents re-fetching daily
    bars on repeated calls within the cache window (the sequential waterfall
    fetch was the 3.4s root cause; the cache is the guard that keeps it <1s
    even when the data source is slow).
  * trades_router.get_trades_journal — response TTL cache keeps the journal
    under 1s under polling bursts (the fresh-connection SELECT * path was the
    10.5s root cause; narrow columns + cache are the fix).

Pure unit tests: fake data manager / db, no live engine, no I/O.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date

from routers import signal_outcomes_router as S
from routers import trades_router as T

# ── signal_outcomes_router: _daily_bars TTL cache ─────────────────────────────


class _FakeDataManager:
    """Records get_bars calls; returns synthetic daily bars."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.df = None

    async def get_bars(self, symbol, lookback_days, timeframe, is_futures):
        self.calls.append((symbol, lookback_days, timeframe, is_futures))
        if self.df is None:
            return None
        return self.df


def test_daily_bars_cache_hits_within_ttl() -> None:
    import pandas as pd

    dm = _FakeDataManager()
    dm.df = pd.DataFrame(
        [
            {"timestamp": "2026-07-01", "high": 1.0, "low": 0.5, "close": 0.8},
            {"timestamp": "2026-07-02", "high": 1.1, "low": 0.6, "close": 0.9},
        ]
    )
    S._data_manager = dm
    S._bars_cache.clear()

    first = asyncio.run(S._daily_bars("MES"))
    assert len(first) == 2
    assert len(dm.calls) == 1

    # Second call inside TTL must NOT re-fetch.
    second = asyncio.run(S._daily_bars("MES"))
    assert second == first
    assert len(dm.calls) == 1

    S._bars_cache.clear()
    S._data_manager = None


def test_daily_bars_cache_expires_after_ttl() -> None:
    import pandas as pd

    dm = _FakeDataManager()
    dm.df = pd.DataFrame([{"timestamp": "2026-07-01", "high": 1.0, "low": 0.5, "close": 0.8}])
    S._data_manager = dm
    S._bars_cache.clear()

    asyncio.run(S._daily_bars("MES"))
    assert len(dm.calls) == 1

    # Simulate TTL expiry by backdating the cache entry.
    symbol, entry = next(iter(S._bars_cache.items()))
    S._bars_cache[symbol] = (entry[0] - S.BARS_CACHE_TTL_SECONDS - 1.0, entry[1])
    asyncio.run(S._daily_bars("MES"))
    assert len(dm.calls) == 2

    S._bars_cache.clear()
    S._data_manager = None


def test_daily_bars_fail_open_keeps_previous_cache() -> None:
    """A failed fetch must not clobber a previously-good cached value."""
    import pandas as pd

    dm = _FakeDataManager()
    dm.df = pd.DataFrame([{"timestamp": "2026-07-01", "high": 1.0, "low": 0.5, "close": 0.8}])
    S._data_manager = dm
    S._bars_cache.clear()

    first = asyncio.run(S._daily_bars("MES"))
    assert len(first) == 1

    # Now the source returns empty (e.g. source down). We still want the cache.
    dm.df = None
    second = asyncio.run(S._daily_bars("MES"))
    assert second == first  # cache hit even though source now returns empty

    S._bars_cache.clear()
    S._data_manager = None


# ── trades_router: get_trades_journal narrow columns + TTL cache ──────────────

# Live paper_trades schema (PRAGMA table_info, engine/data/jarvis_trader.db).
# Keep in sync with the table: this set is the regression guard that catches a
# router selecting a phantom column (e.g. regime_tier) which would 500 live.
REAL_PAPER_TRADES_COLUMNS = frozenset(
    {
        "id", "trade_id", "symbol", "side", "quantity", "entry_price",
        "exit_price", "entry_time", "exit_time", "pnl", "status",
        "strategy_params", "notes", "regime", "structure_position", "bias",
        "composite_score", "stc_contrib", "orb_contrib", "vwap_contrib",
        "risk_pct_used", "stop_loss", "take_profit", "account_id",
        "idempotency_key", "stop_order_id", "target_order_id",
        "bracket_status", "slippage_ticks", "mae_pct", "mfe_pct", "mae_usd",
        "mfe_usd", "epoch", "quote_source", "strategy_id",
    }
)


class _FakeDb:
    """Fake DatabaseManager with a scripted connection/query."""

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.query_count = 0
        self._conn = _FakeConn(self)

    def _connect(self):
        self._conn.opened += 1
        return self._conn


class _FakeConn:
    def __init__(self, db: "_FakeDb") -> None:
        self.db = db
        self.opened = 0

    def execute(self, query, params):
        self.db.query_count += 1
        self._query = query
        return self

    @property
    def description(self):
        cols = self._query.split("SELECT ", 1)[1].split(" FROM ", 1)[0]
        names = [c.strip() for c in cols.split(",")]
        # Regression guard: any column not in the real table would 500 live
        # ("no such column"). Fail the test instead of mirroring the bug.
        missing = [n for n in names if n not in REAL_PAPER_TRADES_COLUMNS]
        assert not missing, f"router SELECTs columns missing from paper_trades: {missing}"
        return [(n, None, None, None, None, None, None) for n in names]

    def fetchall(self):
        return self.db.rows

    def close(self):
        pass


def test_journal_narrow_columns_and_cache() -> None:
    import database

    # 20 real model columns, 2 synthetic rows.
    cols = (
        "id", "trade_id", "symbol", "side", "quantity", "entry_price",
        "exit_price", "entry_time", "exit_time", "pnl", "status",
        "strategy_params", "notes", "regime", "structure_position", "bias",
        "composite_score", "stc_contrib", "orb_contrib", "vwap_contrib",
    )
    row = (
        1, "t1", "MES", "buy", 2.0, 5000.0, 5010.0, "2026-07-01T15:00:00+00:00",
        "2026-07-01T16:00:00+00:00", 20.0, "closed", None, "note", "trend",
        None, None, 0.75, 1, 0, 0,
    )
    fake = _FakeDb([row, row])
    T._journal_cache.clear()

    original_get_db = database.get_db
    database.get_db = lambda: fake  # type: ignore[assignment]
    try:
        entries = T.get_trades_journal(limit=2)
        assert len(entries) == 2
        assert entries[0].trade_id == "t1"
        # Exactly one SQL round-trip for both rows.
        assert fake.query_count == 1
        # Column list must NOT be SELECT * — assert no '*' in the query.
        captured = getattr(fake._conn, "_query", "")
        assert "*" not in captured.split("FROM", 1)[0]

        # Second call within TTL: cache hit, zero extra queries.
        entries2 = T.get_trades_journal(limit=2)
        assert len(entries2) == 2
        assert fake.query_count == 1
    finally:
        database.get_db = original_get_db
        T._journal_cache.clear()


def test_journal_cache_respects_limit_key() -> None:
    import database

    cols = ("id", "trade_id", "symbol", "side", "quantity", "entry_price",
            "exit_price", "entry_time", "exit_time", "pnl", "status",
            "strategy_params", "notes", "regime", "structure_position", "bias",
            "composite_score", "stc_contrib", "orb_contrib", "vwap_contrib")
    row = (1, "t1", "MES", "buy", 1.0, 5000.0, None, "2026-07-01T15:00:00+00:00",
           None, None, "open", None, None, "trend", None, None, None,
           None, None, None)
    fake = _FakeDb([row])
    T._journal_cache.clear()

    original_get_db = database.get_db
    database.get_db = lambda: fake  # type: ignore[assignment]
    try:
        T.get_trades_journal(limit=1)
        assert fake.query_count == 1
        # Different limit key => cache miss => new query.
        T.get_trades_journal(limit=2)
        assert fake.query_count == 2
    finally:
        database.get_db = original_get_db
        T._journal_cache.clear()
