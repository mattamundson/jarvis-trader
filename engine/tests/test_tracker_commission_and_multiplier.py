"""Phase 2 — commission deduction + fail-closed contract multiplier.

Covers two financial-correctness fixes in portfolio/tracker.py:

  2.1  A flat per-contract round-trip commission is subtracted from computed
       close P&L (both close paths), but NOT from a broker-confirmed pnl.
  2.2  An unlisted symbol no longer silently posts a 1x P&L — _resolve_multiplier
       raises UnknownInstrumentMultiplierError unless ALLOW_DEFAULT_MULTIPLIER=1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.tracker import (
    PortfolioTracker,
    UnknownInstrumentMultiplierError,
    _commission_per_contract,
)


@pytest.fixture()
def tracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PortfolioTracker:
    # Pin commission to a known value so assertions are deterministic.
    monkeypatch.setenv("COMMISSION_PER_CONTRACT", "1.50")
    monkeypatch.delenv("ALLOW_DEFAULT_MULTIPLIER", raising=False)
    return PortfolioTracker(store_path=tmp_path / "audit.jsonl")


# ── 2.1 commission ────────────────────────────────────────────────────────────


def test_commission_subtracted_from_computed_close(tracker: PortfolioTracker) -> None:
    # MES mult = 5; (7125-7100)*1*5 = 125 gross; minus 1.50 commission = 123.50
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    trade = tracker.close_trade(tid, exit_price=7125.0)
    assert trade.pnl == pytest.approx(123.50)


def test_commission_scales_with_quantity(tracker: PortfolioTracker) -> None:
    # qty=2 → gross (7125-7100)*2*5 = 250; commission 1.50*2 = 3.00 → 247.00
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=2, price=7100.0)
    trade = tracker.close_trade(tid, exit_price=7125.0)
    assert trade.pnl == pytest.approx(247.00)


def test_commission_applies_to_short_close(tracker: PortfolioTracker) -> None:
    # short: (entry-exit)*qty*mult = (7125-7100)*1*5 = 125 gross; -1.50 = 123.50
    tid = tracker.open_trade(symbol="MES", action="sell", quantity=1, price=7125.0)
    trade = tracker.close_trade(tid, exit_price=7100.0)
    assert trade.pnl == pytest.approx(123.50)


def test_broker_confirmed_pnl_is_not_re_commissioned(tracker: PortfolioTracker) -> None:
    # An explicit pnl is broker-confirmed (already net of fees) → used verbatim.
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    trade = tracker.close_paper_trade(tid, exit_price=7125.0, pnl=200.0)
    assert trade.pnl == pytest.approx(200.0)


def test_commission_default_is_realistic() -> None:
    import os

    os.environ.pop("COMMISSION_PER_CONTRACT", None)
    assert _commission_per_contract() == pytest.approx(1.50)


# ── 2.2 fail-closed multiplier ────────────────────────────────────────────────


def test_unlisted_symbol_raises_on_close(tracker: PortfolioTracker) -> None:
    tid = tracker.open_trade(symbol="ZZZ", action="buy", quantity=1, price=100.0)
    with pytest.raises(UnknownInstrumentMultiplierError):
        tracker.close_trade(tid, exit_price=105.0)


def test_allow_default_multiplier_env_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COMMISSION_PER_CONTRACT", "1.50")
    monkeypatch.setenv("ALLOW_DEFAULT_MULTIPLIER", "1")
    t = PortfolioTracker(store_path=tmp_path / "audit.jsonl")
    tid = t.open_trade(symbol="ZZZ", action="buy", quantity=1, price=100.0)
    # 1x fallback: (105-100)*1*1 = 5 gross; -1.50 commission = 3.50
    trade = t.close_trade(tid, exit_price=105.0)
    assert trade.pnl == pytest.approx(3.50)


def test_listed_symbol_unaffected(tracker: PortfolioTracker) -> None:
    # Regression guard: a known symbol still resolves normally.
    tid = tracker.open_trade(symbol="MGC", action="buy", quantity=1, price=4080.0)
    trade = tracker.close_trade(tid, exit_price=4090.0)
    # MGC mult = 10; (4090-4080)*1*10 = 100 gross; -1.50 = 98.50
    assert trade.pnl == pytest.approx(98.50)
