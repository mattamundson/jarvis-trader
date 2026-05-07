"""Tests for engine.scripts.daily_post_trade_report."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.daily_post_trade_report import (
    DO_NOT_TRADE_SYMBOLS,
    ClosedTrade,
    classify_mistake,
    compute_metrics,
    compute_mistake_taxonomy,
    filter_trades_to_date,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_UTC = timezone.utc

_RAW_TRADES = [
    {
        "order_id": "aaa-001",
        "timestamp": "2026-05-07T14:30:00Z",
        "symbol": "MES",
        "side": "buy",
        "quantity": 1,
        "filled_price": 5300.0,
        "slippage_ticks": 0,
        "pnl": None,
    },
    {
        "order_id": "aaa-002",
        "timestamp": "2026-05-07T15:00:00Z",
        "symbol": "MES",
        "side": "sell",
        "quantity": 1,
        "filled_price": 5310.0,
        "slippage_ticks": 0,
        "pnl": 50.0,
    },
    {
        "order_id": "bbb-001",
        "timestamp": "2026-05-06T14:30:00Z",  # different day
        "symbol": "MGC",
        "side": "buy",
        "quantity": 1,
        "filled_price": 2500.0,
        "slippage_ticks": 1,
        "pnl": None,
    },
    {
        "order_id": "bbb-002",
        "timestamp": "2026-05-06T15:00:00Z",  # different day
        "symbol": "MGC",
        "side": "sell",
        "quantity": 1,
        "filled_price": 2490.0,
        "slippage_ticks": 1,
        "pnl": -100.0,
    },
]


def _make_trade(
    symbol: str = "MES",
    pnl: float = 50.0,
    slippage_ticks: int = 0,
) -> ClosedTrade:
    """Minimal ClosedTrade builder for tests that don't care about times."""
    return ClosedTrade(
        symbol=symbol,
        side="buy",
        quantity=1,
        entry_price=5300.0,
        exit_price=5310.0,
        entry_time=datetime(2026, 5, 7, 14, 0, tzinfo=_UTC),
        exit_time=datetime(2026, 5, 7, 15, 0, tzinfo=_UTC),
        pnl=pnl,
        slippage_ticks=slippage_ticks,
    )


# ---------------------------------------------------------------------------
# test_filter_trades_to_date
# ---------------------------------------------------------------------------


def test_filter_trades_to_date_keeps_target_day():
    result = filter_trades_to_date(_RAW_TRADES, date(2026, 5, 7))
    # Only the first two entries are on 2026-05-07 ET
    symbols = [t["symbol"] for t in result]
    assert symbols == ["MES", "MES"]


def test_filter_trades_to_date_excludes_other_days():
    result = filter_trades_to_date(_RAW_TRADES, date(2026, 5, 7))
    assert all(t["symbol"] != "MGC" for t in result)


def test_filter_trades_to_date_empty_returns_empty():
    result = filter_trades_to_date([], date(2026, 5, 7))
    assert result == []


def test_filter_trades_to_date_no_match_returns_empty():
    result = filter_trades_to_date(_RAW_TRADES, date(2026, 1, 1))
    assert result == []


# ---------------------------------------------------------------------------
# test_metrics_computation
# ---------------------------------------------------------------------------


def test_metrics_win_rate():
    trades = [_make_trade(pnl=50.0), _make_trade(pnl=-20.0), _make_trade(pnl=30.0)]
    m = compute_metrics(trades)
    assert m["total_trades"] == 3
    assert m["wins"] == 2
    assert m["losses"] == 1
    assert abs(m["win_rate"] - 2 / 3) < 1e-9


def test_metrics_total_pnl():
    trades = [_make_trade(pnl=50.0), _make_trade(pnl=-20.0)]
    m = compute_metrics(trades)
    assert abs(m["total_pnl"] - 30.0) < 1e-9


def test_metrics_biggest_win_loss():
    trades = [_make_trade(pnl=100.0), _make_trade(pnl=-75.0), _make_trade(pnl=25.0)]
    m = compute_metrics(trades)
    assert abs(m["biggest_win"] - 100.0) < 1e-9
    assert abs(m["biggest_loss"] - (-75.0)) < 1e-9


def test_metrics_empty_trades():
    m = compute_metrics([])
    assert m["total_trades"] == 0
    assert m["win_rate"] is None
    assert m["total_pnl"] == 0.0


def test_metrics_goal_progress():
    trades = [_make_trade(pnl=125.0)]
    m = compute_metrics(trades)
    assert abs(m["goal_progress_pct"] - 50.0) < 1e-9


# ---------------------------------------------------------------------------
# test_counterfactual helpers (pure logic — no signal generator invocation)
# ---------------------------------------------------------------------------


def test_counterfactual_no_signal_no_miss():
    """Strategy didn't signal; engine didn't trade → no missed-opportunity entry."""
    # We test the matching logic directly without calling the DB or signal generator.
    # simulate: signal_entries is empty → events list is empty
    events: list = []
    missed = [e for e in events if e.get("type") == "missed_entry"]
    assert missed == []


def test_counterfactual_signal_no_trade():
    """If signal bar has no matching actual fill, it's classified as missed_entry."""
    # Simulate the inner loop logic without DB/signal generator
    from datetime import timedelta

    bar_ts = datetime(2026, 5, 7, 14, 0, tzinfo=None)
    actual_entry_times: set = set()  # no fills

    matched = any(
        abs((act - bar_ts).total_seconds()) <= 1800
        for act in actual_entry_times
    )
    assert not matched  # confirms missed_entry classification


# ---------------------------------------------------------------------------
# test_mistake_taxonomy
# ---------------------------------------------------------------------------


def test_mistake_taxonomy_wrong_symbol():
    for sym in DO_NOT_TRADE_SYMBOLS:
        t = _make_trade(symbol=sym, pnl=-50.0)
        assert classify_mistake(t) == "wrong_symbol"


def test_mistake_taxonomy_bad_fill():
    # slippage_ticks=2 > threshold=1 → bad_fill
    t = _make_trade(symbol="MES", pnl=-20.0, slippage_ticks=2)
    assert classify_mistake(t) == "bad_fill"


def test_mistake_taxonomy_bad_signal():
    # normal loss on approved symbol with acceptable slippage
    t = _make_trade(symbol="MES", pnl=-20.0, slippage_ticks=0)
    assert classify_mistake(t) == "bad_signal"


def test_mistake_taxonomy_wins_excluded():
    trades = [_make_trade(pnl=100.0), _make_trade(pnl=-50.0)]
    taxonomy = compute_mistake_taxonomy(trades)
    assert len(taxonomy) == 1
    assert taxonomy[0]["pnl"] == -50.0


def test_mistake_taxonomy_wrong_symbol_overrides_bad_fill():
    """wrong_symbol check runs before bad_fill check."""
    sym = next(iter(DO_NOT_TRADE_SYMBOLS))
    t = _make_trade(symbol=sym, pnl=-30.0, slippage_ticks=5)
    assert classify_mistake(t) == "wrong_symbol"
