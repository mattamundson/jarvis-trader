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
    def test_returns_deployed_candidate_for_mgc(self) -> None:
        # The registry ships exactly one deployed_live candidate for MGC.
        assert live_candidate_for_symbol("MGC") == "MGC_trend_rv_filter_rank1"

    def test_case_insensitive(self) -> None:
        assert live_candidate_for_symbol("mgc") == "MGC_trend_rv_filter_rank1"

    def test_none_when_no_deployed_candidate(self) -> None:
        # MES candidates are not deployed_live -> untagged (symbol-level context).
        assert live_candidate_for_symbol("MES") is None

    def test_none_for_unknown_symbol(self) -> None:
        assert live_candidate_for_symbol("ZZZZ") is None

    def test_none_for_empty_symbol(self) -> None:
        assert live_candidate_for_symbol("") is None

    def test_ambiguous_multiple_deployed_returns_none(self) -> None:
        # Two deployed_live candidates for one symbol must NOT be guessed.
        reg = load_registry()
        for c in reg["candidates"]:
            if c["symbol"] == "MGC":
                c["deployed_live"] = True
        assert live_candidate_for_symbol("MGC", registry=reg) is None

    def test_registry_has_at_most_one_deployed_per_symbol(self) -> None:
        # Guard the contract: the shipped registry must not be ambiguous.
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
async def test_mirror_tags_deployed_symbol(spy_logger) -> None:
    log, tracker = spy_logger
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
async def test_mirror_untagged_for_undeployed_symbol(spy_logger) -> None:
    log, tracker = spy_logger
    await log.log_trade(
        {
            "order_id": "22222222-2222-2222-2222-222222222222",
            "symbol": "MES",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 7100.0,
            "fill_time": "2026-06-12T15:00:00Z",
            "is_futures": True,
        }
    )
    assert tracker.open_calls
    assert tracker.open_calls[0]["candidate_id"] is None
