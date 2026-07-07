"""Regression tests for PortfolioTracker.get_performance()['today_pnl'].

Bug (north-star R3 / ROI #7): get_performance() exposed only total_pnl (the
all-time closed sum) and no today_pnl key. FuturesModule.get_daily_pnl() does
`perf.get("today_pnl", perf.get("total_pnl", 0))`, so a "daily" number silently
reported lifetime P&L -- which propagated to /portfolio/summary.total_daily_pnl
(it showed $2,331 "daily" = all-time realized $1,290 + unrealized $1,042).

today_pnl must sum only the realized P&L of trades CLOSED today (UTC), keyed off
the exit_time YYYY-MM-DD prefix. The risk path is unaffected: it reads the
date-filtered DB method db.get_daily_pnl(start_date=..., end_date=...), not this.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from portfolio.tracker import PortfolioTracker


@pytest.fixture()
def tracker(tmp_path: Path) -> PortfolioTracker:
    # store_path-only -> _db is None -> get_performance uses in-memory _closed.
    return PortfolioTracker(store_path=tmp_path / "audit.jsonl")


def test_today_pnl_key_present_and_zero_when_empty(tracker: PortfolioTracker) -> None:
    perf = tracker.get_performance()
    assert "today_pnl" in perf
    assert perf["today_pnl"] == 0.0


def test_today_pnl_equals_total_when_all_closes_today(tracker: PortfolioTracker) -> None:
    a = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    tracker.close_trade(a, exit_price=7125.0)
    b = tracker.open_trade(symbol="MGC", action="buy", quantity=1, price=4080.0)
    tracker.close_trade(b, exit_price=4090.0)

    perf = tracker.get_performance()
    assert perf["num_trades"] == 2
    # both closed "now" (today UTC) -> today == all-time
    assert perf["today_pnl"] == pytest.approx(perf["total_pnl"])
    assert perf["today_pnl"] != 0.0


def test_today_pnl_excludes_prior_day_closes(tracker: PortfolioTracker) -> None:
    # Trade A closed today; trade B back-dated to yesterday.
    a = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    tracker.close_trade(a, exit_price=7125.0)
    b = tracker.open_trade(symbol="MGC", action="buy", quantity=1, price=4080.0)
    tracker.close_trade(b, exit_price=4090.0)

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    # back-date the SECOND closed trade (b) to yesterday
    tracker._closed[1].exit_time = yesterday

    a_pnl = tracker._closed[0].pnl
    perf = tracker.get_performance()

    # total still counts both; today counts only A
    assert perf["total_pnl"] == pytest.approx(
        round(sum(t.pnl for t in tracker._closed), 4)
    )
    assert perf["today_pnl"] == pytest.approx(round(a_pnl, 4))
    assert perf["today_pnl"] != perf["total_pnl"]


def test_today_pnl_zero_when_no_closes_today(tracker: PortfolioTracker) -> None:
    a = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    tracker.close_trade(a, exit_price=7125.0)
    tracker._closed[0].exit_time = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()

    perf = tracker.get_performance()
    assert perf["total_pnl"] != 0.0  # the trade still counts all-time
    assert perf["today_pnl"] == 0.0  # but nothing closed today
