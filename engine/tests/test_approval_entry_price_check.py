"""
JARVIS TRADER — Approval Path Entry Price Sanity Tests
=======================================================
Verifies that the entry price sanity check is correctly wired into
approve_pending_trade() and that the HTTP 422 rejection / bypass flows work.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from approval.service import ApprovalFlowError, approve_pending_trade
from database.manager import DatabaseManager
from portfolio.tracker import PortfolioTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sane_data_manager(entry_price: float, market_price: float, atr_range: float = 2.0):
    """Return a mock data manager whose bars produce ATR ~ atr_range/2."""
    mock_dm = MagicMock()
    mock_dm.get_current_price = AsyncMock(return_value={"last_price": market_price})

    rows = 20
    df = pd.DataFrame(
        {
            "high": [market_price + atr_range / 2] * rows,
            "low": [market_price - atr_range / 2] * rows,
            "close": [market_price] * rows,
        }
    )
    mock_dm.get_bars = AsyncMock(return_value=df)
    return mock_dm


def _build_mock_safety_layer(*, kill_switch=False, locked=False, symbol="MCL"):
    sl = MagicMock()
    sl.get_status.return_value = {
        "kill_switch_active": kill_switch,
    }
    sl.get_lockout_status.return_value = {"locked": locked}
    return sl


async def _insert_approval(db, *, symbol="MCL", entry_price: float = 72.5):
    return db.insert_pending_approval(
        symbol=symbol,
        action="buy",
        quantity=1.0,
        entry_price=entry_price,
        pipeline_snapshot={"summary": "test"},
        timeframe="1h",
    )


# ---------------------------------------------------------------------------
# Test: corrupted entry price → HTTP 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_path_rejects_corrupted_entry(tmp_path: Path, monkeypatch):
    """approve_pending_trade raises ApprovalFlowError(422) for a corrupted price.

    Scenario: entry_price is 7398.5481 (a stop_loss field copied in);
    market is 7385; ATR~10 → ratio≈1.35 >> 1.0 threshold.
    """
    monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "1")
    monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)
    # Put MCL on the watchlist
    monkeypatch.setenv("FUTURES_WATCHLIST", "MCL,MES,MNQ,MGC")

    db = DatabaseManager(str(tmp_path / "test.db"))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)
    sl = _build_mock_safety_layer(symbol="MCL")

    # Corrupted price: stop_loss value (~7398) in entry_price field; real market ~7385
    approval_id = await _insert_approval(db, symbol="MCL", entry_price=7398.5481)

    # data_manager: market=7385, ATR≈10 (high-low range 10 per bar)
    mock_dm = MagicMock()
    mock_dm.get_current_price = AsyncMock(return_value={"last_price": 7385.0})
    rows = 20
    df = pd.DataFrame(
        {
            "high": [7390.0 + i for i in range(rows)],
            "low": [7380.0 + i for i in range(rows)],
            "close": [7385.0 + i for i in range(rows)],
        }
    )
    mock_dm.get_bars = AsyncMock(return_value=df)

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MCL", "MES", "MNQ", "MGC"}
    ):
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")
        ):
            with pytest.raises(ApprovalFlowError) as exc_info:
                await approve_pending_trade(
                    approval_id=approval_id,
                    db_manager=db,
                    paper_tracker=tracker,
                    safety_layer=sl,
                    resolved_by="test",
                    data_manager=mock_dm,
                )

    assert exc_info.value.status_code == 422
    assert (
        "sanity" in exc_info.value.detail.lower() or "entry price" in exc_info.value.detail.lower()
    )
    # Approval row must still be pending — no paper trade opened
    assert db.get_pending_approval(approval_id)["status"] == "pending"
    assert tracker.get_open_positions() == []


# ---------------------------------------------------------------------------
# Test: sane entry price passes through to IB submission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_path_accepts_sane_entry(tmp_path: Path, monkeypatch):
    """approve_pending_trade succeeds when entry_price is sane."""
    monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "1")
    monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)
    monkeypatch.setenv("FUTURES_WATCHLIST", "MCL,MES,MNQ,MGC")

    db = DatabaseManager(str(tmp_path / "test.db"))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)

    # Sane price: entry=72.5, market=72.0, ATR≈2.0 → delta=0.5, ratio=0.25
    approval_id = await _insert_approval(db, symbol="MCL", entry_price=72.5)

    mock_dm = _make_sane_data_manager(entry_price=72.5, market_price=72.0, atr_range=4.0)

    sl = MagicMock()
    sl.get_status.return_value = {"kill_switch_active": False}
    sl.get_lockout_status.return_value = {"locked": False}

    # Mock safety_layer.submit_entry_with_stop / submit_paper_order to succeed
    sl.submit_paper_order = AsyncMock(
        return_value={
            "approved": True,
            "paper_trade_id": "t-123",
            "routed_to_ib": True,
        }
    )
    sl.submit_entry_with_stop = AsyncMock(
        return_value={
            "approved": True,
            "paper_trade_id": "t-123",
            "routed_to_ib": True,
            "entry_order_id": "e-1",
        }
    )

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MCL", "MES", "MNQ", "MGC"}
    ):
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")
        ):
            result = await approve_pending_trade(
                approval_id=approval_id,
                db_manager=db,
                paper_tracker=tracker,
                safety_layer=sl,
                resolved_by="test",
                data_manager=mock_dm,
            )

    assert result["status"] == "approved"
    assert result["symbol"] == "MCL"


# ---------------------------------------------------------------------------
# Test: disabled flag bypasses check entirely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_path_disabled_flag_skips_check(tmp_path: Path, monkeypatch):
    """With ENABLE_ENTRY_PRICE_SANITY=0 a corrupted price is NOT caught at the approval layer.

    This test confirms the opt-out path works: the sanity check is bypassed when the
    flag is disabled, and the approval proceeds to the IB submission stage.
    (The corrupted price would still cause an IB rejection downstream, but that is
    outside the scope of this layer.)
    """
    monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "0")
    monkeypatch.setenv("FUTURES_WATCHLIST", "MCL,MES,MNQ,MGC")

    db = DatabaseManager(str(tmp_path / "test.db"))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)

    # Use a corrupted price that would be rejected if the check were enabled
    approval_id = await _insert_approval(db, symbol="MCL", entry_price=7398.5481)

    mock_dm = MagicMock()
    mock_dm.get_current_price = AsyncMock(return_value={"last_price": 7385.0})
    mock_dm.get_bars = AsyncMock(return_value=pd.DataFrame())

    sl = MagicMock()
    sl.get_status.return_value = {"kill_switch_active": False}
    sl.get_lockout_status.return_value = {"locked": False}
    sl.submit_paper_order = AsyncMock(
        return_value={
            "approved": True,
            "paper_trade_id": "t-999",
            "routed_to_ib": True,
        }
    )
    sl.submit_entry_with_stop = AsyncMock(
        return_value={
            "approved": True,
            "paper_trade_id": "t-999",
            "routed_to_ib": True,
            "entry_order_id": "e-9",
        }
    )

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MCL", "MES", "MNQ", "MGC"}
    ):
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")
        ):
            # Should NOT raise — sanity check is disabled
            result = await approve_pending_trade(
                approval_id=approval_id,
                db_manager=db,
                paper_tracker=tracker,
                safety_layer=sl,
                resolved_by="test",
                data_manager=mock_dm,
            )

    assert result["status"] == "approved"


# ---------------------------------------------------------------------------
# Test: no data_manager provided — sanity check skipped gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_path_no_data_manager_skips_check(tmp_path: Path, monkeypatch):
    """When data_manager=None the sanity check is skipped (no crash)."""
    monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "1")
    monkeypatch.setenv("FUTURES_WATCHLIST", "MCL,MES,MNQ,MGC")

    db = DatabaseManager(str(tmp_path / "test.db"))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)

    approval_id = await _insert_approval(db, symbol="MCL", entry_price=72.5)

    sl = MagicMock()
    sl.get_status.return_value = {"kill_switch_active": False}
    sl.get_lockout_status.return_value = {"locked": False}
    sl.submit_paper_order = AsyncMock(
        return_value={
            "approved": True,
            "paper_trade_id": "t-456",
            "routed_to_ib": True,
        }
    )
    sl.submit_entry_with_stop = AsyncMock(
        return_value={
            "approved": True,
            "paper_trade_id": "t-456",
            "routed_to_ib": True,
            "entry_order_id": "e-2",
        }
    )

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MCL", "MES", "MNQ", "MGC"}
    ):
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")
        ):
            result = await approve_pending_trade(
                approval_id=approval_id,
                db_manager=db,
                paper_tracker=tracker,
                safety_layer=sl,
                resolved_by="test",
                data_manager=None,  # <-- no data manager
            )

    assert result["status"] == "approved"
