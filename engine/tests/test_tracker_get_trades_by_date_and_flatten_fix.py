"""
Regression tests for 2026-04-23 fixes to PortfolioTracker:

1. get_trades_by_date(date_str) — new method closing the EOD_SUMMARY
   AttributeError (main.py:1136-1138 caller expected it to exist).
2. flatten_all_positions(market_price_fn=..., exit_price=...) — the
   Phase-3 breakeven-close bug surfaced by EOD trades recording $0 P&L
   when the scheduler called with no price.  Fallback still works (for
   backward compat) but now logs ERROR so the condition is visible.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from portfolio.tracker import PortfolioTracker


@pytest.fixture()
def tracker(tmp_path: Path) -> PortfolioTracker:
    store = tmp_path / "audit.jsonl"
    return PortfolioTracker(store_path=store)


# ─── get_trades_by_date ───────────────────────────────────────────────

def test_get_trades_by_date_matches_exit_date_prefix(tracker: PortfolioTracker) -> None:
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    tracker.close_trade(tid, exit_price=7125.0)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hits = tracker.get_trades_by_date(today)

    assert len(hits) == 1
    assert hits[0]["symbol"] == "MES"


def test_get_trades_by_date_returns_realized_pnl_alias(tracker: PortfolioTracker) -> None:
    """EOD summary caller contract: must provide 'realized_pnl' key."""
    tid = tracker.open_trade(symbol="MCL", action="buy", quantity=1, price=93.00)
    tracker.close_trade(tid, exit_price=94.50)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hits = tracker.get_trades_by_date(today)

    assert len(hits) == 1
    row = hits[0]
    assert "realized_pnl" in row
    assert isinstance(row["realized_pnl"], float)
    # MCL multiplier is 100; +1.50 price * 1 contract * 100 = +$150 pnl
    assert row["realized_pnl"] == pytest.approx(150.0, rel=0.01)


def test_get_trades_by_date_filters_other_dates(tracker: PortfolioTracker) -> None:
    tid = tracker.open_trade(symbol="MNQ", action="sell", quantity=1, price=18000.0)
    tracker.close_trade(tid, exit_price=17950.0)

    # Pull closed trade from in-memory _closed list and move its exit_time backward.
    closed_trade = tracker._closed[-1]
    closed_trade.exit_time = "2026-04-20T20:00:00+00:00"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert tracker.get_trades_by_date(today) == []
    assert len(tracker.get_trades_by_date("2026-04-20")) == 1


def test_get_trades_by_date_rejects_malformed_input(tracker: PortfolioTracker) -> None:
    assert tracker.get_trades_by_date("") == []
    assert tracker.get_trades_by_date("not-a-date") == []
    assert tracker.get_trades_by_date(None) == []  # type: ignore[arg-type]


# ─── flatten_all_positions (exit-price fix) ───────────────────────────

def test_flatten_prefers_market_price_fn(tracker: PortfolioTracker) -> None:
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)

    def fake_quote(symbol: str) -> Optional[float]:
        return 7200.0 if symbol == "MES" else None

    closed = tracker.flatten_all_positions(market_price_fn=fake_quote)

    assert len(closed) == 1
    # Price should be the fetcher's 7200, not entry 7100 (so pnl > 0)
    assert closed[0]["exit_price"] == pytest.approx(7200.0)
    assert closed[0]["pnl"] > 0
    assert tid not in tracker._open


def test_flatten_falls_back_to_exit_price_when_fn_returns_none(
    tracker: PortfolioTracker,
) -> None:
    tracker.open_trade(symbol="MCL", action="buy", quantity=1, price=93.00)

    closed = tracker.flatten_all_positions(
        exit_price=94.00,
        market_price_fn=lambda s: None,
    )

    assert len(closed) == 1
    assert closed[0]["exit_price"] == pytest.approx(94.00)


def test_flatten_breakeven_fallback_logs_error(
    tracker: PortfolioTracker,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When no market_price_fn and no exit_price are passed, the fallback to
    entry_price still fires (preserves existing behavior so EOD scheduler
    does not break) — but logs ERROR so the condition is visible in prod.
    This is the 2026-04-23 Phase-3 metrics bug trigger.

    Gross P&L at breakeven is $0, but the flat per-contract commission
    (Phase 2 financial-calc fix) still applies to a real closed contract, so
    the net P&L is -commission, not exactly $0.
    """
    monkeypatch.setenv("COMMISSION_PER_CONTRACT", "1.50")
    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)

    with caplog.at_level(logging.ERROR, logger="portfolio.tracker"):
        closed = tracker.flatten_all_positions()

    assert len(closed) == 1
    assert closed[0]["exit_price"] == pytest.approx(7100.0)  # entry_price fallback
    assert closed[0]["pnl"] == pytest.approx(-1.50)  # breakeven gross, net of commission

    # Error log should explicitly call out the breakeven fallback path
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "breakeven" in combined.lower() or "entry_price" in combined.lower()
