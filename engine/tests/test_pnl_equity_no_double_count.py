"""Regression: portfolio equity must count P&L exactly ONCE.

Root cause (2026-07-02): ``PortfolioTracker._get_starting_balance`` used to
return ``INITIAL_CAPITAL + sum(closed pnl)`` — i.e. current equity, misnamed as
a "starting" balance. Both consumers then added ``total_pnl`` again:

  * ``risk/pnl_monitor._read_memory``:   current = starting + total_pnl
  * ``PortfolioTracker.get_performance_summary``: total_value = equity + total_pnl

=> portfolio_equity = initial + 2*total_pnl  ($20,163.67 vs true $15,081.84).

The fix makes ``_get_starting_balance`` return the pnl-FREE base (INITIAL_CAPITAL)
so the ``starting + total_pnl`` contract yields equity counted once. These tests
fail on the buggy version (starting_balance == initial + total_pnl) and pass
after the fix (starting_balance == initial).
"""

import pytest

from portfolio.tracker import PortfolioTracker


def _make_tracker(tmp_path):
    # No db_manager: pure in-memory closed-trade accounting.
    return PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=None)


def _initial_capital() -> float:
    # Read INITIAL_CAPITAL exactly as _get_starting_balance does, so the
    # assertion matches whatever base the code under test uses.
    try:
        from config import settings  # type: ignore[import]

        return float(getattr(settings, "INITIAL_CAPITAL", 10_000.0) or 10_000.0)
    except Exception:
        return 10_000.0


def _win_round_trip(tracker):
    """Open + close one winning MES round-trip; return the closed-trade P&L."""
    tid = tracker.open_trade("MES", "buy", 1, 5000.0)
    tracker.close_trade(tid, 5020.0)
    return tracker.get_performance()["total_pnl"]


def test_starting_balance_is_pnl_free(tmp_path):
    """starting_balance must equal INITIAL_CAPITAL, NOT initial + realized P&L."""
    tracker = _make_tracker(tmp_path)
    total_pnl = _win_round_trip(tracker)
    assert total_pnl != 0.0, "test needs a non-zero P&L to be meaningful"

    starting = tracker.get_performance()["starting_balance"]
    initial = _initial_capital()
    assert starting == pytest.approx(initial), (
        "starting_balance is a pnl-FREE base; it must equal INITIAL_CAPITAL, not "
        f"initial+pnl (starting={starting}, initial={initial}, total_pnl={total_pnl})"
    )


def test_equity_counts_pnl_once(tmp_path):
    """Equity via the consumer contract (starting + total_pnl) counts P&L once."""
    tracker = _make_tracker(tmp_path)
    total_pnl = _win_round_trip(tracker)

    perf = tracker.get_performance()
    starting = perf["starting_balance"]
    initial = _initial_capital()

    # Mirrors risk/pnl_monitor._read_memory: current = starting + total_pnl
    equity = starting + total_pnl

    assert equity == pytest.approx(initial + total_pnl), "P&L counted once"
    # The double-count bug produced initial + 2*total_pnl — guard the regression.
    assert equity != pytest.approx(
        initial + 2 * total_pnl
    ), "DOUBLE-COUNT regression: equity = initial + 2*total_pnl"
