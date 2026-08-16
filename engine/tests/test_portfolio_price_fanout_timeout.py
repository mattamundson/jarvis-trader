"""Regression: a single wedged price fetch must not hang the whole fan-out.

2026-08-16 incident: `/portfolio/summary` (and 4 sibling endpoints with the
identical pattern) fan out over open positions with
``asyncio.gather(*[_data_manager.get_tick_price(sym) for sym in symbols],
return_exceptions=True)``. ``return_exceptions=True`` only catches exceptions
raised by a coroutine -- it does nothing for a coroutine that never returns at
all (an IB Gateway "wedge": socket open, API dead -- the same root cause fixed
at 4 other call sites this session, see ``tests/test_ib_blind_chaos.py``).
One wedged symbol among many open positions hung the entire endpoint
indefinitely, and every sibling fan-out shares the same unguarded shape.

Fix: each per-symbol call is now wrapped in its own bounded
``asyncio.wait_for``, so a wedge degrades that one symbol to a stale/missing
mark (the code already has a path for this -- ``(None, None)``, excluded from
the aggregate) while the rest of the batch still resolves normally.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from routers import portfolio_router as pr_mod


class _HangForever:
    """An awaitable that never completes -- the wedge itself."""

    def __await__(self):
        yield from asyncio.Event().wait().__await__()


class _StubDataManager:
    """One symbol wedges forever, the other resolves normally."""

    def __init__(self, wedged_symbol: str, healthy_symbol: str, healthy_price: float):
        self.wedged_symbol = wedged_symbol
        self.healthy_symbol = healthy_symbol
        self.healthy_price = healthy_price
        self.calls: list[str] = []
        # _ibkr_connected()/derive_is_live() require this to count an
        # "ibkr"-sourced mark as live -- irrelevant to the fix under test.
        self.ibkr = SimpleNamespace(is_connected=True)

    async def get_tick_price(self, symbol: str, is_futures: bool = False) -> dict:
        self.calls.append(symbol)
        if symbol == self.wedged_symbol:
            return await _HangForever()
        return {"last_price": self.healthy_price, "prev_close": None, "change_pct": None, "source": "ibkr"}

    # get_current_price shares the same wedge/healthy shape for the sibling
    # fan-outs (paper_performance, get_unrealized_positions) that use it
    # instead of get_tick_price.
    get_current_price = get_tick_price


class _StubPaperTracker:
    def __init__(self, positions: list[dict]):
        self._positions = positions

    def get_open_positions(self) -> list[dict]:
        return self._positions


def _positions() -> list[dict]:
    return [
        {"symbol": "MES", "action": "buy", "quantity": 1.0, "entry_price": 5300.0, "trade_id": "t-wedged"},
        {"symbol": "MGC", "action": "buy", "quantity": 1.0, "entry_price": 4300.0, "trade_id": "t-healthy"},
    ]


def test_portfolio_summary_survives_a_wedged_symbol(monkeypatch) -> None:
    """The exact live bug: one wedged get_tick_price must not hang the endpoint."""
    dm = _StubDataManager(wedged_symbol="MES", healthy_symbol="MGC", healthy_price=4320.0)
    monkeypatch.setattr(pr_mod, "paper_tracker", _StubPaperTracker(_positions()))
    monkeypatch.setattr(pr_mod, "_data_manager", dm)
    monkeypatch.setattr(pr_mod, "_get_orchestrator", lambda: None)
    # Fast test: bound the fan-out's own timeout well below the outer guard below.
    monkeypatch.setattr(pr_mod, "_PRICE_FANOUT_TIMEOUT_S", 0.05)

    # Outer backstop: if the production timeout doesn't actually bound the
    # hang, fail this test loudly instead of hanging the whole pytest run.
    summary = asyncio.run(asyncio.wait_for(pr_mod.portfolio_summary(), timeout=5.0))

    assert dm.calls.count("MES") == 1
    assert dm.calls.count("MGC") == 1
    # The wedged symbol produced no mark at all (timeout -> excluded via the
    # existing (None, None) path, not a phantom zero) while the healthy
    # symbol's P&L still landed -- proving the batch wasn't discarded wholesale.
    assert summary["unrealized_marks_live"] == 1  # MGC only; MES has no mark
    assert summary["unrealized_pnl"] == 200.0  # (4320-4300)*10 MGC, $10/pt


def test_portfolio_summary_all_healthy_is_unaffected(monkeypatch) -> None:
    """Regression guard: the timeout wrapper must not change the healthy path."""
    dm = _StubDataManager(wedged_symbol="__none__", healthy_symbol="MGC", healthy_price=4320.0)
    monkeypatch.setattr(pr_mod, "paper_tracker", _StubPaperTracker(_positions()))
    monkeypatch.setattr(pr_mod, "_data_manager", dm)
    monkeypatch.setattr(pr_mod, "_get_orchestrator", lambda: None)
    monkeypatch.setattr(pr_mod, "_PRICE_FANOUT_TIMEOUT_S", 6.0)

    summary = asyncio.run(asyncio.wait_for(pr_mod.portfolio_summary(), timeout=5.0))

    assert summary["unrealized_marks_stale"] == 0
    assert summary["unrealized_marks_live"] == 2
