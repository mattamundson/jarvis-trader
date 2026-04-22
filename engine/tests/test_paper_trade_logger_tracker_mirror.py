"""PaperTradeLogger optional mirror into PortfolioTracker (mode B)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from execution.paper_trade_logger import PaperTradeLogger
from portfolio.tracker import PortfolioTracker


@pytest.fixture()
def tmp_trades_file(tmp_path: Path) -> Path:
    return tmp_path / "paper_trades.json"


@pytest.fixture()
def tracker(tmp_path: Path) -> PortfolioTracker:
    store = tmp_path / "audit.jsonl"
    return PortfolioTracker(store_path=store)


def test_constructor_emits_deprecation_warning(
    tmp_trades_file: Path,
) -> None:
    """PaperTradeLogger should emit a DeprecationWarning on init — SQLite is source of truth."""
    settings = SimpleNamespace()
    with pytest.warns(DeprecationWarning, match="source of truth"):
        PaperTradeLogger(
            settings,
            portfolio_tracker=None,
            trades_file=tmp_trades_file,
        )


@pytest.mark.asyncio
async def test_mirror_open_close_long_round_trip(
    tmp_trades_file: Path,
    tracker: PortfolioTracker,
) -> None:
    settings = SimpleNamespace()
    log = PaperTradeLogger(
        settings,
        portfolio_tracker=tracker,
        trades_file=tmp_trades_file,
    )

    await log.log_trade(
        {
            "order_id": "11111111-1111-1111-1111-111111111111",
            "symbol": "MCL",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 70.0,
            "slippage_ticks": 0,
            "fill_time": "2026-04-02T12:00:00Z",
            "is_futures": True,
        }
    )
    assert len(tracker.get_open_positions()) == 1

    await log.log_trade(
        {
            "order_id": "22222222-2222-2222-2222-222222222222",
            "symbol": "MCL",
            "quantity": -1,
            "order_type": "market",
            "filled_price": 71.0,
            "slippage_ticks": 0,
            "fill_time": "2026-04-02T13:00:00Z",
            "is_futures": True,
        }
    )
    assert len(tracker.get_open_positions()) == 0
    perf = tracker.get_performance()
    assert perf["num_trades"] == 1
    assert tmp_trades_file.exists()
    data = tmp_trades_file.read_text(encoding="utf-8")
    assert "MCL" in data


@pytest.mark.asyncio
async def test_mirror_disabled_json_only(
    tmp_trades_file: Path,
    tracker: PortfolioTracker,
) -> None:
    settings = SimpleNamespace()
    log = PaperTradeLogger(
        settings,
        portfolio_tracker=tracker,
        mirror_to_tracker=False,
        trades_file=tmp_trades_file,
    )

    await log.log_trade(
        {
            "order_id": "33333333-3333-3333-3333-333333333333",
            "symbol": "MNQ",
            "quantity": 1,
            "order_type": "market",
            "filled_price": 20000.0,
            "slippage_ticks": 0,
            "fill_time": "2026-04-02T12:00:00Z",
            "is_futures": True,
        }
    )
    assert len(tracker.get_open_positions()) == 0
