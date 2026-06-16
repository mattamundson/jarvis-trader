"""Forward-test attribution wiring (ROI #2 Part B).

The paper-entry mirror must tag a new trade with the deployed registry
candidate_id for its symbol, so forward-testing attributes the trade at the
precise (graduating) level. Two layers:

1. live_candidate_for_symbol() resolves the single deployed_live candidate for a
   symbol from the locked registry, and FAILS SAFE (None) when zero or >1 are
   deployed -- a wrong tag corrupts attribution, so ambiguity must never be
   guessed.

2. PaperTradeLogger._maybe_mirror_to_tracker passes that candidate_id into
   open_trade on a 0->position open. Fail-open: resolution errors must not block
   the entry, and a symbol with no deployed candidate opens exactly as before.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backtest.candidate_registry import live_candidate_for_symbol, load_registry


class TestLiveCandidateForSymbol:
    # ── Shipped registry: nothing deployed by design ────────────────────────
    # The live autonomous pipeline decides entries via LLM/agent conviction, NOT
    # by running a mechanical registry candidate, so NO candidate is deployed_live
    # today -- tagging would mis-attribute LLM-driven trades to a mechanical
    # strategy and manufacture a fake graduation record.
    def test_shipped_registry_deploys_nothing(self) -> None:
        reg = load_registry()
        assert all(c.get("deployed_live") is not True for c in reg["candidates"])

    def test_shipped_mgc_is_untagged(self) -> None:
        assert live_candidate_for_symbol("MGC") is None

    def test_shipped_mes_is_untagged(self) -> None:
        assert live_candidate_for_symbol("MES") is None

    def test_none_for_unknown_symbol(self) -> None:
        assert live_candidate_for_symbol("ZZZZ") is None

    def test_none_for_empty_symbol(self) -> None:
        assert live_candidate_for_symbol("") is None

    # ── Mechanism: resolves the single deployed candidate when one exists ────
    def _synthetic(self, mgc_deployed: int) -> dict:
        """A registry with `mgc_deployed` MGC candidates flagged deployed_live."""
        reg = load_registry()
        flagged = 0
        for c in reg["candidates"]:
            if c["symbol"] == "MGC" and flagged < mgc_deployed:
                c["deployed_live"] = True
                flagged += 1
        return reg

    def test_resolves_single_deployed_candidate(self) -> None:
        reg = self._synthetic(mgc_deployed=1)
        # The first MGC candidate in the registry is MGC_trend_rv_filter_rank1.
        assert live_candidate_for_symbol("MGC", registry=reg) == "MGC_trend_rv_filter_rank1"

    def test_resolves_case_insensitive(self) -> None:
        reg = self._synthetic(mgc_deployed=1)
        assert live_candidate_for_symbol("mgc", registry=reg) == "MGC_trend_rv_filter_rank1"

    def test_ambiguous_multiple_deployed_returns_none(self) -> None:
        # Two deployed_live candidates for one symbol must NOT be guessed.
        reg = self._synthetic(mgc_deployed=2)
        assert live_candidate_for_symbol("MGC", registry=reg) is None

    def test_at_most_one_deployed_per_symbol_in_shipped_registry(self) -> None:
        # Guard the contract: the shipped registry must never be ambiguous.
        reg = load_registry()
        by_symbol: dict[str, int] = {}
        for c in reg["candidates"]:
            if c.get("deployed_live") is True:
                by_symbol[c["symbol"]] = by_symbol.get(c["symbol"], 0) + 1
        assert all(n <= 1 for n in by_symbol.values()), by_symbol


class _SpyTracker:
    """Captures the kwargs the mirror passes to open_trade."""

    def __init__(self) -> None:
        self.open_calls: list[dict] = []
        self._next = 0

    def open_trade(self, symbol, action, quantity, price, **kwargs):
        self.open_calls.append({"symbol": symbol, **kwargs})
        self._next += 1
        return f"tid-{self._next}"

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
async def test_mirror_passes_resolved_candidate_id(spy_logger, monkeypatch) -> None:
    """When a candidate IS deployed for the symbol, the mirror threads its id
    through to open_trade. (Patched resolver -- the shipped registry deploys
    nothing today by design, so this tests the wiring, not the flag values.)"""
    log, tracker = spy_logger
    monkeypatch.setattr(
        "backtest.candidate_registry.live_candidate_for_symbol",
        lambda symbol, registry=None: "MGC_trend_rv_filter_rank1" if symbol == "MGC" else None,
    )
    await log.log_trade(
        {
            "order_id": "11111111-1111-1111-1111-111111111111",
            "symbol": "MGC",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 4080.0,
            "fill_time": "2026-06-12T15:00:00Z",
            "is_futures": True,
        }
    )
    assert tracker.open_calls, "mirror did not open a trade"
    assert tracker.open_calls[0]["candidate_id"] == "MGC_trend_rv_filter_rank1"


@pytest.mark.asyncio
async def test_mirror_untagged_with_shipped_registry(spy_logger) -> None:
    """With the real registry (nothing deployed), MGC opens untagged -- honest
    symbol-level context, no mis-attribution to a mechanical candidate."""
    log, tracker = spy_logger
    await log.log_trade(
        {
            "order_id": "22222222-2222-2222-2222-222222222222",
            "symbol": "MGC",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 4080.0,
            "fill_time": "2026-06-12T15:00:00Z",
            "is_futures": True,
        }
    )
    assert tracker.open_calls
    assert tracker.open_calls[0]["candidate_id"] is None


@pytest.mark.asyncio
async def test_mirror_failopen_on_resolver_error(spy_logger, monkeypatch) -> None:
    """A resolver exception must never block the entry -- candidate_id falls to
    None and the trade still opens."""
    log, tracker = spy_logger

    def _boom(symbol, registry=None):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(
        "backtest.candidate_registry.live_candidate_for_symbol", _boom
    )
    await log.log_trade(
        {
            "order_id": "33333333-3333-3333-3333-333333333333",
            "symbol": "MGC",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 4080.0,
            "fill_time": "2026-06-12T15:00:00Z",
            "is_futures": True,
        }
    )
    assert tracker.open_calls, "fail-open: trade must still open"
    assert tracker.open_calls[0]["candidate_id"] is None
