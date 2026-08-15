"""#287 fix: stop_loss threading through open_trade() and its naked-open callers.

MGC #287 (-$1,236) and #286 (-$322) both booked through
PortfolioTracker.open_trade(), which had no ``stop_loss`` parameter at all --
the decision-time stop was silently dropped and the row persisted
stop_loss=NULL, leaving PaperStopMonitor nothing to enforce until an
unrelated exit. Covers:

  1. The core open_trade(stop_loss=...) plumbing (DB + in-memory).
  2. paper_trade_logger._maybe_mirror_to_tracker -- the actual #287 culprit --
     which has no decision-time stop in scope, so it now synthesizes a
     defensive one from the same dollar-risk budget as PaperStopMonitor's
     catastrophe cap (services.paper_stop_monitor.synthesize_fallback_stop).
  3. ib_order_manager.sync_positions_from_ib -- the same "no stop in scope"
     gap on the post-restart IB position-reconcile backfill path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


def _set_max_loss_env(value):
    prev = os.environ.get("PAPER_MAX_LOSS_USD_PER_TRADE")
    if value is None:
        os.environ.pop("PAPER_MAX_LOSS_USD_PER_TRADE", None)
    else:
        os.environ["PAPER_MAX_LOSS_USD_PER_TRADE"] = str(value)
    return prev


def _restore_max_loss_env(prev):
    if prev is None:
        os.environ.pop("PAPER_MAX_LOSS_USD_PER_TRADE", None)
    else:
        os.environ["PAPER_MAX_LOSS_USD_PER_TRADE"] = prev


def _ensure_symbol_on_watchlist(symbol):
    """Temporarily add *symbol* to config.settings.FUTURES_WATCHLIST.

    The approval gate (approval/service.py:approved_watchlist_symbols) reads
    the parsed settings singleton, not the environment, and the code-level
    default ("MCL,MNQ,MES") -- unlike the real deployed engine/.env, which is
    gitignored and absent in a fresh worktree/CI checkout -- doesn't include
    every symbol these stop-loss-synthesis tests exercise. Returns the prior
    value so it can be restored; symbol-membership, not the watchlist gate
    itself, is out of scope for this test.
    """
    from config import settings

    prev = list(settings.FUTURES_WATCHLIST)
    if symbol not in {s.upper() for s in prev}:
        settings.FUTURES_WATCHLIST = [*prev, symbol]
    return prev


def _restore_watchlist(prev):
    from config import settings

    settings.FUTURES_WATCHLIST = prev


# ── Core: open_trade(stop_loss=...) plumbing ──────────────────────────────────


def test_open_trade_persists_stop_loss_to_db(tmp_path: Path) -> None:
    """stop_loss reaches insert_paper_trade -- was hardcoded None before this fix."""
    from portfolio.tracker import PortfolioTracker

    captured: dict = {}

    class _FakeDB:
        def insert_paper_trade(self, trade_id, **kwargs):
            captured.update(kwargs)
            return 1

        def get_trade_by_id(self, *a, **k):
            return {"trade_id": "x"}

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=_FakeDB())
    tracker.open_trade("MGC", "buy", 1, 4503.9, stop_loss=4473.9)

    assert captured.get("stop_loss") == 4473.9


def test_open_trade_persists_stop_loss_in_memory(tmp_path: Path) -> None:
    """stop_loss lands on the in-memory PaperTrade too (no DB manager attached)."""
    from portfolio.tracker import PortfolioTracker

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl")
    tracker.open_trade("MGC", "buy", 1, 4503.9, stop_loss=4473.9)

    positions = tracker.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["stop_loss"] == 4473.9


def test_open_trade_default_stop_loss_is_none(tmp_path: Path) -> None:
    """Omitting stop_loss still defaults to None -- unchanged for callers that
    don't pass it (backward-compatible signature)."""
    from portfolio.tracker import PortfolioTracker

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl")
    tracker.open_trade("MGC", "buy", 1, 4503.9)

    positions = tracker.get_open_positions()
    assert positions[0]["stop_loss"] is None


def test_open_trade_stamps_stop_source_into_strategy_params(tmp_path: Path) -> None:
    """stop_source is an audit-clarity marker distinguishing a synthesized
    backstop stop from a real decision-derived one (#US-007)."""
    from portfolio.tracker import PortfolioTracker

    captured: dict = {}

    class _FakeDB:
        def insert_paper_trade(self, trade_id, **kwargs):
            captured.update(kwargs)
            return 1

        def get_trade_by_id(self, *a, **k):
            return {"trade_id": "x"}

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=_FakeDB())
    tracker.open_trade(
        "MGC", "buy", 1, 4503.9, stop_loss=4473.9, stop_source="synthesized_fallback"
    )

    assert captured["strategy_params"]["stop_source"] == "synthesized_fallback"


def test_open_trade_omitting_stop_source_leaves_it_untagged(tmp_path: Path) -> None:
    """A real decision-time stop (no stop_source passed) is NOT tagged --
    absence of the marker means decision-derived, by design."""
    from portfolio.tracker import PortfolioTracker

    captured: dict = {}

    class _FakeDB:
        def insert_paper_trade(self, trade_id, **kwargs):
            captured.update(kwargs)
            return 1

        def get_trade_by_id(self, *a, **k):
            return {"trade_id": "x"}

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=_FakeDB())
    tracker.open_trade("MGC", "buy", 1, 4503.9, stop_loss=4473.9)

    assert "stop_source" not in captured["strategy_params"]


# ── paper_trade_logger naked-fill mirror path (the actual #287 culprit) ──────


class _SpyTracker:
    def __init__(self) -> None:
        self.open_calls: list[dict] = []
        self._open: dict = {}
        self._n = 0

    def open_trade(self, symbol, action, quantity, price, **kwargs):
        self.open_calls.append(
            {"symbol": symbol, "action": action, "quantity": quantity, "price": price, **kwargs}
        )
        self._n += 1
        return f"tid-{self._n}"

    def close_trade(self, *a, **k):
        return None


@pytest.fixture()
def spy_logger(tmp_path: Path):
    from execution.paper_trade_logger import PaperTradeLogger

    tracker = _SpyTracker()
    log = PaperTradeLogger(
        SimpleNamespace(),
        portfolio_tracker=tracker,
        trades_file=tmp_path / "paper_trades.json",
    )
    return log, tracker


@pytest.mark.asyncio
async def test_mirror_synthesizes_stop_on_naked_fill(spy_logger) -> None:
    """The naked-fill mirror has no decision-time stop in scope -- it must
    synthesize one from the catastrophe-cap budget rather than persist NULL."""
    prev = _set_max_loss_env(300)
    try:
        log, tracker = spy_logger
        await log.log_trade(
            {
                "order_id": "11111111-1111-1111-1111-111111111111",
                "symbol": "MGC",
                "quantity": 1,
                "order_type": "market",
                "filled_price": 4503.9,
                "fill_time": "2026-07-09T15:00:00Z",
                "is_futures": True,
            }
        )
        assert tracker.open_calls, "mirror did not open a trade"
        stop = tracker.open_calls[0]["stop_loss"]
        # MGC mult=10, qty=1 -> distance = 300/10 = 30.0; long -> entry - distance
        assert stop == round(4503.9 - 30.0, 4)
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_mirror_synthesizes_stop_short_side(spy_logger) -> None:
    prev = _set_max_loss_env(300)
    try:
        log, tracker = spy_logger
        await log.log_trade(
            {
                "order_id": "33333333-3333-3333-3333-333333333333",
                "symbol": "MES",
                "quantity": -2,  # short
                "order_type": "market",
                "filled_price": 5000.0,
                "fill_time": "2026-07-09T15:00:00Z",
                "is_futures": True,
            }
        )
        stop = tracker.open_calls[0]["stop_loss"]
        # MES mult=5, qty=2 -> distance = 300/10 = 30.0; short -> entry + distance
        assert stop == round(5000.0 + 30.0, 4)
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_mirror_tags_stop_source_as_synthesized_fallback(spy_logger) -> None:
    prev = _set_max_loss_env(300)
    try:
        log, tracker = spy_logger
        await log.log_trade(
            {
                "order_id": "44444444-4444-4444-4444-444444444444",
                "symbol": "MGC",
                "quantity": 1,
                "order_type": "market",
                "filled_price": 4503.9,
                "fill_time": "2026-07-09T15:00:00Z",
                "is_futures": True,
            }
        )
        assert tracker.open_calls[0]["stop_source"] == "synthesized_fallback"
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_mirror_stop_synthesis_disabled_stays_none(spy_logger) -> None:
    """PAPER_MAX_LOSS_USD_PER_TRADE=0 must leave stop_loss None, not fabricate one."""
    prev = _set_max_loss_env(0)
    try:
        log, tracker = spy_logger
        await log.log_trade(
            {
                "order_id": "22222222-2222-2222-2222-222222222222",
                "symbol": "MGC",
                "quantity": 1,
                "order_type": "market",
                "filled_price": 4503.9,
                "fill_time": "2026-07-09T15:00:00Z",
                "is_futures": True,
            }
        )
        assert tracker.open_calls[0]["stop_loss"] is None
        assert tracker.open_calls[0]["stop_source"] is None
    finally:
        _restore_max_loss_env(prev)


# ── ib_order_manager position-reconcile backfill ──────────────────────────────


@pytest.mark.asyncio
async def test_sync_positions_from_ib_synthesizes_stop() -> None:
    """A post-restart IB-reconcile backfill also has no decision-time stop in
    scope -- the same synthesis applies so a backfilled row is never naked."""
    from execution.ib_order_manager import IBOrderManager

    prev = _set_max_loss_env(300)
    try:
        tracker = _SpyTracker()
        gateway = MagicMock()
        gateway.is_connected.return_value = True
        gateway.get_positions = AsyncMock(
            return_value=[
                {
                    "symbol": "MGC",
                    "position": 1,
                    "avg_cost": 4503.9,
                    "sec_type": "FUT",
                    "exchange": "COMEX",
                }
            ]
        )
        mgr = IBOrderManager(
            safety_layer=MagicMock(), ib_gateway=gateway, portfolio_tracker=tracker
        )

        await mgr.sync_positions_from_ib()

        assert tracker.open_calls, "reconcile did not open a trade"
        stop = tracker.open_calls[0]["stop_loss"]
        assert stop == round(4503.9 - 30.0, 4)
        assert tracker.open_calls[0]["stop_source"] == "synthesized_fallback"
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_sync_positions_from_ib_skips_already_tracked_symbol() -> None:
    """Regression guard: a symbol already open in the tracker is left alone
    (no duplicate open_trade call, so no accidental stop overwrite either)."""
    from execution.ib_order_manager import IBOrderManager

    tracker = _SpyTracker()
    tracker._open = {"existing": SimpleNamespace(symbol="MGC")}
    gateway = MagicMock()
    gateway.is_connected.return_value = True
    gateway.get_positions = AsyncMock(
        return_value=[{"symbol": "MGC", "position": 1, "avg_cost": 4503.9}]
    )
    mgr = IBOrderManager(safety_layer=MagicMock(), ib_gateway=gateway, portfolio_tracker=tracker)

    await mgr.sync_positions_from_ib()

    assert tracker.open_calls == []


# ── portfolio_router direct-open endpoints (the last 2 naked call sites) ──────


@pytest.fixture()
def portfolio_router_client(tmp_path: Path):
    """Wires the real portfolio_router with an in-memory PortfolioTracker --
    same pattern as test_portfolio_paper_trade_post.py's paper_trade_client,
    replicated locally so this file doesn't depend on another test module."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi.errors import RateLimitExceeded

    from middleware.rate_limit import limiter, rate_limit_exception_handler
    from portfolio.tracker import PortfolioTracker
    from routers import portfolio_router as pr_mod

    old_pt, old_db, old_safety = pr_mod.paper_tracker, pr_mod.db_manager, pr_mod._safety_layer

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tracker = PortfolioTracker(store_path=tmp_path / "router_stop_loss_audit.jsonl")
    safety = MagicMock()
    safety.get_status.return_value = {"is_killed": False, "kill_switch_active": False}
    pr_mod.inject_dependencies(tracker, None, None, safety)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    yield client, tracker

    pr_mod.inject_dependencies(old_pt, old_db, None, old_safety)


def test_paper_trade_sync_open_persists_client_stop(portfolio_router_client) -> None:
    client, tracker = portfolio_router_client
    r = client.post(
        "/portfolio/paper/trade",
        json={
            "action": "open",
            "symbol": "MES",
            "side": "long",
            "quantity": 1,
            "entry_price": 5823.50,
            "stop_loss": 5800.00,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["stop_loss"] == 5800.00
    positions = tracker.get_open_positions()
    assert positions[0]["stop_loss"] == 5800.00
    assert "stop_source" not in (positions[0].get("strategy_params") or {})


def test_paper_trade_sync_open_synthesizes_stop_when_omitted(portfolio_router_client) -> None:
    prev = _set_max_loss_env(300)
    prev_watchlist = _ensure_symbol_on_watchlist("MGC")
    try:
        client, tracker = portfolio_router_client
        r = client.post(
            "/portfolio/paper/trade",
            json={
                "action": "open",
                "symbol": "MGC",
                "side": "long",
                "quantity": 1,
                "entry_price": 4503.9,
            },
        )
        assert r.status_code == 200, r.text
        # MGC mult=10, qty=1 -> distance = 300/10 = 30.0; long -> entry - distance
        assert r.json()["stop_loss"] == round(4503.9 - 30.0, 4)
        positions = tracker.get_open_positions()
        assert positions[0]["stop_loss"] == round(4503.9 - 30.0, 4)
    finally:
        _restore_max_loss_env(prev)
        _restore_watchlist(prev_watchlist)


def test_paper_trade_sync_open_rejects_inverted_stop(portfolio_router_client) -> None:
    client, _tracker = portfolio_router_client
    r = client.post(
        "/portfolio/paper/trade",
        json={
            "action": "open",
            "symbol": "MES",
            "side": "long",
            "quantity": 1,
            "entry_price": 5823.50,
            "stop_loss": 5850.00,  # above entry on a long -- inverted
        },
    )
    assert r.status_code == 422, r.text


def test_paper_trade_manual_open_persists_client_stop(portfolio_router_client) -> None:
    client, tracker = portfolio_router_client
    r = client.post(
        "/portfolio/paper/trade/manual",
        json={
            "symbol": "MES",
            "action": "buy",
            "quantity": 1,
            "price": 5823.50,
            "stop_loss": 5800.00,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["stop_loss"] == 5800.00
    positions = tracker.get_open_positions()
    assert positions[0]["stop_loss"] == 5800.00


def test_paper_trade_manual_open_synthesizes_stop_when_omitted(portfolio_router_client) -> None:
    prev = _set_max_loss_env(300)
    prev_watchlist = _ensure_symbol_on_watchlist("MGC")
    try:
        client, tracker = portfolio_router_client
        r = client.post(
            "/portfolio/paper/trade/manual",
            json={
                "symbol": "MGC",
                "action": "buy",
                "quantity": 1,
                "price": 4503.9,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["stop_loss"] == round(4503.9 - 30.0, 4)
        positions = tracker.get_open_positions()
        assert positions[0]["stop_loss"] == round(4503.9 - 30.0, 4)
    finally:
        _restore_max_loss_env(prev)
        _restore_watchlist(prev_watchlist)


def test_paper_trade_manual_open_synthesizes_stop_for_sell_short(portfolio_router_client) -> None:
    """Regression guard for the sell_short/buy_to_cover side-normalization gap:
    synthesize_fallback_stop only recognizes long/short, not this endpoint's
    wider buy/sell/sell_short/buy_to_cover vocabulary -- passing action through
    raw would silently return None and leave the row naked again."""
    prev = _set_max_loss_env(300)
    try:
        client, tracker = portfolio_router_client
        r = client.post(
            "/portfolio/paper/trade/manual",
            json={
                "symbol": "MES",
                "action": "sell_short",
                "quantity": 2,
                "price": 5000.0,
            },
        )
        assert r.status_code == 200, r.text
        # MES mult=5, qty=2 -> distance = 300/10 = 30.0; short -> entry + distance
        assert r.json()["stop_loss"] == round(5000.0 + 30.0, 4)
        positions = tracker.get_open_positions()
        assert positions[0]["stop_loss"] == round(5000.0 + 30.0, 4)
    finally:
        _restore_max_loss_env(prev)


def test_paper_trade_manual_open_rejects_inverted_stop(portfolio_router_client) -> None:
    client, _tracker = portfolio_router_client
    r = client.post(
        "/portfolio/paper/trade/manual",
        json={
            "symbol": "MES",
            "action": "buy",
            "quantity": 1,
            "price": 5823.50,
            "stop_loss": 5850.00,  # above entry on a long -- inverted
        },
    )
    assert r.status_code == 422, r.text
