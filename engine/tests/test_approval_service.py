import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from approval.service import ApprovalFlowError, approve_pending_trade, ensure_approval_allowed

_TEST_WATCHLIST = {"MCL", "MES", "MNQ", "MGC"}


@pytest.fixture
def mock_watchlist():
    """Patch watchlist and authorization so tests focus on the strategy gate.

    is_strategy_authorized is bypassed here because these tests verify the
    VALIDATION_ONLY_STRATEGIES gate, not the instrument authorization gate.
    """
    with patch("approval.service.approved_watchlist_symbols", return_value=_TEST_WATCHLIST):
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized",
            return_value=(True, "authorized"),
        ):
            yield


@pytest.mark.asyncio
async def test_approve_pending_trade_requires_safety_layer(tmp_path):
    from database.manager import DatabaseManager
    from portfolio.tracker import PortfolioTracker

    db_path = tmp_path / "approval.db"
    trades_path = tmp_path / "paper_trades.jsonl"

    db = DatabaseManager(str(db_path))
    db.initialize()
    tracker = PortfolioTracker(store_path=trades_path, db_manager=db)

    approval_id = db.insert_pending_approval(
        symbol="MCL",
        action="buy",
        quantity=1.0,
        entry_price=72.5,
        pipeline_snapshot={"summary": "approval regression"},
        timeframe="1h",
    )

    with pytest.raises(ApprovalFlowError) as exc_info:
        await approve_pending_trade(
            approval_id=approval_id,
            db_manager=db,
            paper_tracker=tracker,
            safety_layer=None,
            resolved_by="test",
        )

    assert exc_info.value.status_code == 503
    assert db.get_pending_approval(approval_id)["status"] == "pending"
    assert tracker.get_open_positions() == []


# ── VALIDATION_ONLY_STRATEGIES gate in ensure_approval_allowed ────────────────


def _make_mock_safety():
    """Minimal safety layer mock that reports kill switch inactive."""
    mock = MagicMock()
    mock.get_status.return_value = {"kill_switch_active": False}
    mock.get_lockout_status.return_value = {"locked": False}
    return mock


def _approval_row(symbol: str = "MCL", stark_signal: str = "") -> dict:
    """Minimal approval row shape consumed by ensure_approval_allowed.

    Uses MCL by default: on FUTURES_WATCHLIST but NOT in VALIDATION_ONLY_INSTRUMENTS,
    so the instrument gate does not fire before the strategy gate under test.
    """
    snapshot: dict = {}
    if stark_signal:
        snapshot = {
            "analyst_reports": {"technical": {"indicators": {"stark_signal": stark_signal}}}
        }
    return {
        "symbol": symbol,
        "action": "sell",
        "quantity": 1.0,
        "entry_price": 72.50,
        "pipeline_snapshot": snapshot,
    }


def test_ensure_approval_allowed_blocks_short_gap_fill(mock_watchlist):
    """Manual approval of a SHORT_GAP_FILL signal must be rejected (BLOCKER 5 / §6.3)."""
    row = _approval_row(symbol="MCL", stark_signal="SHORT_GAP_FILL")
    with pytest.raises(ApprovalFlowError) as exc_info:
        ensure_approval_allowed(row, _make_mock_safety())
    assert exc_info.value.status_code == 409
    assert "VALIDATION_ONLY_STRATEGIES" in exc_info.value.detail
    assert "SHORT_GAP_FILL" in exc_info.value.detail


def test_ensure_approval_allowed_blocks_short_gap_fill_lowercase(mock_watchlist):
    """stark_signal matching is case-insensitive."""
    row = _approval_row(symbol="MCL", stark_signal="short_gap_fill")
    with pytest.raises(ApprovalFlowError) as exc_info:
        ensure_approval_allowed(row, _make_mock_safety())
    assert exc_info.value.status_code == 409


def test_ensure_approval_allowed_passes_validated_strategy(mock_watchlist):
    """A strategy NOT in VALIDATION_ONLY_STRATEGIES must not be blocked."""
    row = _approval_row(symbol="MCL", stark_signal="LONG_VAL_BOUNCE")
    result = ensure_approval_allowed(row, _make_mock_safety())
    assert result is None


def test_ensure_approval_allowed_passes_empty_stark_signal(mock_watchlist):
    """Missing stark_signal in snapshot must not block approval."""
    row = _approval_row(symbol="MCL", stark_signal="")
    result = ensure_approval_allowed(row, _make_mock_safety())
    assert result is None


def test_ensure_approval_allowed_handles_json_string_snapshot(mock_watchlist):
    """pipeline_snapshot stored as JSON string must still be parsed for the strategy gate."""
    snapshot_dict = {
        "analyst_reports": {"technical": {"indicators": {"stark_signal": "SHORT_GAP_FILL"}}}
    }
    row = {
        "symbol": "MCL",
        "action": "sell",
        "quantity": 1.0,
        "entry_price": 72.50,
        "pipeline_snapshot": json.dumps(snapshot_dict),
    }
    with pytest.raises(ApprovalFlowError) as exc_info:
        ensure_approval_allowed(row, _make_mock_safety())
    assert exc_info.value.status_code == 409
    assert "SHORT_GAP_FILL" in exc_info.value.detail


# ── #287 fix: the "safe" (human-approved) path was ALSO dropping its stop ─────
# stop_price is computed at approval/service.py:~351 for the broker bracket
# order but was never threaded into open_trade() -- even human-approved trades
# persisted stop_loss=NULL on the paper_trades row.


@pytest.mark.asyncio
async def test_approve_pending_trade_threads_stop_price_into_open_trade(
    mock_watchlist, tmp_path
) -> None:
    from database.manager import DatabaseManager
    from portfolio.tracker import PortfolioTracker

    db_path = tmp_path / "approval.db"
    trades_path = tmp_path / "paper_trades.jsonl"
    db = DatabaseManager(str(db_path))
    db.initialize()
    tracker = PortfolioTracker(store_path=trades_path, db_manager=db)

    approval_id = db.insert_pending_approval(
        symbol="MCL",
        action="buy",
        quantity=1.0,
        entry_price=72.50,
        pipeline_snapshot={"stop_price": 71.80},
        timeframe="1h",
    )

    safety = _make_mock_safety()
    safety.submit_entry_with_stop = AsyncMock(
        return_value={"approved": True, "entry_order_id": "1", "stp_order_id": "2"}
    )

    await approve_pending_trade(
        approval_id=approval_id,
        db_manager=db,
        paper_tracker=tracker,
        safety_layer=safety,
        resolved_by="test",
    )

    open_positions = tracker.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0]["stop_loss"] == pytest.approx(71.80)
