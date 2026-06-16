"""P2 wiring: the paper-entry mirror stamps decision_identity on a new trade."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


class _SpyTracker:
    def __init__(self) -> None:
        self.open_calls: list[dict] = []
        self._n = 0

    def open_trade(self, symbol, action, quantity, price, **kwargs):
        self.open_calls.append({"symbol": symbol, **kwargs})
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
async def test_mirror_stamps_decision_identity(spy_logger) -> None:
    log, tracker = spy_logger
    await log.log_trade(
        {
            "order_id": "11111111-1111-1111-1111-111111111111",
            "symbol": "MES",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 7100.0,
            "fill_time": "2026-06-15T15:00:00Z",
            "is_futures": True,
        }
    )
    assert tracker.open_calls, "mirror did not open a trade"
    did = tracker.open_calls[0]["decision_identity"]
    assert did is not None
    assert did["symbol"] == "MES"
    assert did["lineage"].endswith("::MES")
    assert "config_hash" in did and "pipeline_version" in did


@pytest.mark.asyncio
async def test_open_trade_persists_decision_identity_in_strategy_params(tmp_path) -> None:
    """open_trade stamps decision_identity into the trade's strategy_params."""
    from portfolio.tracker import PortfolioTracker

    captured: dict = {}

    class _FakeDB:
        def insert_paper_trade(self, trade_id, **kwargs):
            captured.update(kwargs)
            return 1

        def get_trade_by_id(self, *a, **k):
            return {"trade_id": "x"}

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=_FakeDB())
    ident = {"config_hash": "abc123", "lineage": "unregistered:abc123::MGC", "symbol": "MGC"}
    tracker.open_trade("MGC", "buy", 1, 4080.0, decision_identity=ident)

    sp = captured.get("strategy_params") or {}
    assert sp.get("decision_identity") == ident
