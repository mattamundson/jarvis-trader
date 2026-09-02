"""Regression tests for the 2026-08-18 analytics/trades latency fixes.

The suite is intentionally offline. It protects two performance/correctness
contracts:

1. ``signal_outcomes_router._daily_bars`` caches successful daily-bar fetches.
2. ``trades_router.get_trades_journal`` uses a narrow SELECT containing only
   real ``paper_trades`` columns and caches responses by filter/limit key.

The second contract is also a correctness guard: selecting a model-only field
that is absent from SQLite makes the live journal endpoint fail with
``no such column``.
"""

from __future__ import annotations

import asyncio

from routers import signal_outcomes_router as S
from routers import trades_router as T


class _FakeDataManager:
    """Record get_bars calls and return a scripted DataFrame/None."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.df = None

    async def get_bars(self, symbol, lookback_days, timeframe, is_futures):
        self.calls.append((symbol, lookback_days, timeframe, is_futures))
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

    second = asyncio.run(S._daily_bars("MES"))
    assert second == first
    assert len(dm.calls) == 1

    S._bars_cache.clear()
    S._data_manager = None


def test_daily_bars_cache_expires_after_ttl() -> None:
    import pandas as pd

    dm = _FakeDataManager()
    dm.df = pd.DataFrame(
        [{"timestamp": "2026-07-01", "high": 1.0, "low": 0.5, "close": 0.8}]
    )
    S._data_manager = dm
    S._bars_cache.clear()

    asyncio.run(S._daily_bars("MES"))
    assert len(dm.calls) == 1

    symbol, entry = next(iter(S._bars_cache.items()))
    S._bars_cache[symbol] = (entry[0] - S.BARS_CACHE_TTL_SECONDS - 1.0, entry[1])
    asyncio.run(S._daily_bars("MES"))
    assert len(dm.calls) == 2

    S._bars_cache.clear()
    S._data_manager = None


def test_daily_bars_fail_open_keeps_previous_cache() -> None:
    """A failed upstream fetch must not clobber a previously good cache entry."""
    import pandas as pd

    dm = _FakeDataManager()
    dm.df = pd.DataFrame(
        [{"timestamp": "2026-07-01", "high": 1.0, "low": 0.5, "close": 0.8}]
    )
    S._data_manager = dm
    S._bars_cache.clear()

    first = asyncio.run(S._daily_bars("MES"))
    assert len(first) == 1

    dm.df = None
    second = asyncio.run(S._daily_bars("MES"))
    assert second == first

    S._bars_cache.clear()
    S._data_manager = None


# Live paper_trades schema columns relevant to the journal regression. Keep this
# broader than the journal SELECT so the test catches phantom columns without
# forcing the endpoint to SELECT every stored field.
REAL_PAPER_TRADES_COLUMNS = frozenset(
    {
        "id",
        "trade_id",
        "symbol",
        "side",
        "quantity",
        "entry_price",
        "exit_price",
        "entry_time",
        "exit_time",
        "pnl",
        "status",
        "strategy_params",
        "notes",
        "regime",
        "structure_position",
        "bias",
        "composite_score",
        "stc_contrib",
        "orb_contrib",
        "vwap_contrib",
        "risk_pct_used",
        "stop_loss",
        "take_profit",
        "account_id",
        "idempotency_key",
        "stop_order_id",
        "target_order_id",
        "bracket_status",
        "slippage_ticks",
        "mae_pct",
        "mfe_pct",
        "mae_usd",
        "mfe_usd",
        "epoch",
        "quote_source",
        "strategy_id",
    }
)


class _FakeDb:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.query_count = 0
        self._conn = _FakeConn(self)

    def _connect(self):
        self._conn.opened += 1
        return self._conn


class _FakeConn:
    def __init__(self, db: _FakeDb) -> None:
        self.db = db
        self.opened = 0
        self._query = ""

    def execute(self, query, params):
        self.db.query_count += 1
        self._query = query
        return self

    @property
    def description(self):
        selected = self._query.split("SELECT ", 1)[1].split(" FROM ", 1)[0]
        names = [column.strip() for column in selected.split(",")]
        missing = [name for name in names if name not in REAL_PAPER_TRADES_COLUMNS]
        assert not missing, f"router SELECTs columns missing from paper_trades: {missing}"
        return [(name, None, None, None, None, None, None) for name in names]

    def fetchall(self):
        return self.db.rows

    def close(self):
        return None


def _journal_row(*, quantity: float = 1.0) -> tuple:
    """Return one row matching the 20 real columns the journal should SELECT."""
    return (
        1,
        "t1",
        "MES",
        "buy",
        quantity,
        5000.0,
        5010.0,
        "2026-07-01T15:00:00+00:00",
        "2026-07-01T16:00:00+00:00",
        20.0,
        "closed",
        None,
        "note",
        "trend",
        None,
        None,
        0.75,
        1,
        0,
        0,
    )


def test_journal_narrow_columns_and_cache() -> None:
    import database

    fake = _FakeDb([_journal_row(quantity=2.0), _journal_row(quantity=2.0)])
    T._journal_cache.clear()

    original_get_db = database.get_db
    database.get_db = lambda: fake  # type: ignore[assignment]
    try:
        entries = T.get_trades_journal(limit=2)
        assert len(entries) == 2
        assert entries[0].trade_id == "t1"
        assert fake.query_count == 1

        selected = fake._conn._query.split("FROM", 1)[0]
        assert "*" not in selected

        # Model-only fields have no backing paper_trades column; Pydantic fills
        # their Optional defaults rather than forcing phantom SQL columns.
        assert entries[0].regime_tier is None
        assert entries[0].deciding_stage is None
        assert entries[0].bull_score is None
        assert entries[0].bear_score is None
        assert entries[0].debate_confidence is None
        assert entries[0].timeframe is None

        entries2 = T.get_trades_journal(limit=2)
        assert len(entries2) == 2
        assert fake.query_count == 1
    finally:
        database.get_db = original_get_db
        T._journal_cache.clear()


def test_journal_cache_respects_limit_key() -> None:
    import database

    fake = _FakeDb([_journal_row()])
    T._journal_cache.clear()

    original_get_db = database.get_db
    database.get_db = lambda: fake  # type: ignore[assignment]
    try:
        T.get_trades_journal(limit=1)
        assert fake.query_count == 1

        T.get_trades_journal(limit=2)
        assert fake.query_count == 2
    finally:
        database.get_db = original_get_db
        T._journal_cache.clear()
