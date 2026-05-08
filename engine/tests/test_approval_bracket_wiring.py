"""
HB-1 Stage 4 — Approval path routes through broker brackets when enabled.

Contract:
  When settings.ENABLE_BROKER_BRACKETS is False (default), execute_approved_trade
  calls safety_layer.submit_paper_order (legacy naked-entry behavior).

  When the flag is True AND the caller supplies stop_price,
  execute_approved_trade calls safety_layer.submit_entry_with_stop
  (broker-side STP + optional TP children).

  When the flag is True but stop_price is None, the bracket path is skipped
  and legacy submit_paper_order is used (graceful fallback).

Also covers the _extract_snapshot_price helper:
  - pulls from top-level snapshot keys
  - falls back to snapshot.decision nested dict
  - returns None for missing / non-numeric / zero values

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_approval_bracket_wiring.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# ─── execute_approved_trade: bracket ON/OFF flag behavior ─────────────


@pytest.mark.asyncio
async def test_execute_approved_trade_flag_off_uses_legacy_naked_entry() -> None:
    """Default ENABLE_BROKER_BRACKETS=False → naked entry (submit_paper_order)."""
    from approval.service import execute_approved_trade

    mock_safety = MagicMock()
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "order_id": 111, "routed_to_ib": True}
    )
    mock_safety.submit_entry_with_stop = AsyncMock()

    with patch("approval.service.settings.ENABLE_BROKER_BRACKETS", False):
        result = await execute_approved_trade(
            safety_layer=mock_safety,
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=7130.0,
            stop_price=7100.0,
            target_price=7190.0,
        )

    mock_safety.submit_paper_order.assert_awaited_once()
    mock_safety.submit_entry_with_stop.assert_not_awaited()
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_execute_approved_trade_flag_on_with_stop_uses_bracket() -> None:
    """ENABLE_BROKER_BRACKETS=True + stop_price → submit_entry_with_stop."""
    from approval.service import execute_approved_trade

    mock_safety = MagicMock()
    mock_safety.submit_paper_order = AsyncMock()
    mock_safety.submit_entry_with_stop = AsyncMock(
        return_value={
            "approved": True,
            "entry_order_id": 222,
            "stp_order_id": 333,
            "tp_order_id": 444,
            "stp_linked": True,
            "tp_linked": True,
            "routed_to_ib": True,
        }
    )

    with patch("approval.service.settings.ENABLE_BROKER_BRACKETS", True):
        result = await execute_approved_trade(
            safety_layer=mock_safety,
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=7130.0,
            stop_price=7100.0,
            target_price=7190.0,
        )

    mock_safety.submit_entry_with_stop.assert_awaited_once()
    mock_safety.submit_paper_order.assert_not_awaited()
    call_kwargs = mock_safety.submit_entry_with_stop.await_args.kwargs
    assert call_kwargs["stop_price"] == 7100.0
    assert call_kwargs["target_price"] == 7190.0
    assert result["tp_order_id"] == 444


@pytest.mark.asyncio
async def test_execute_approved_trade_flag_on_no_stop_falls_back_to_legacy() -> None:
    """Flag on but stop_price=None → legacy naked-entry (graceful)."""
    from approval.service import execute_approved_trade

    mock_safety = MagicMock()
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "order_id": 555, "routed_to_ib": True}
    )
    mock_safety.submit_entry_with_stop = AsyncMock()

    with patch("approval.service.settings.ENABLE_BROKER_BRACKETS", True):
        result = await execute_approved_trade(
            safety_layer=mock_safety,
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=7130.0,
            # no stop_price
        )

    mock_safety.submit_paper_order.assert_awaited_once()
    mock_safety.submit_entry_with_stop.assert_not_awaited()
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_execute_approved_trade_bracket_without_target_ok() -> None:
    """Flag on, stop_price set, no target_price → bracket with STP only."""
    from approval.service import execute_approved_trade

    mock_safety = MagicMock()
    mock_safety.submit_entry_with_stop = AsyncMock(
        return_value={
            "approved": True,
            "entry_order_id": 666,
            "stp_order_id": 777,
            "tp_order_id": None,
            "stp_linked": True,
            "tp_linked": False,
            "routed_to_ib": True,
        }
    )

    with patch("approval.service.settings.ENABLE_BROKER_BRACKETS", True):
        result = await execute_approved_trade(
            safety_layer=mock_safety,
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=7130.0,
            stop_price=7100.0,
        )

    mock_safety.submit_entry_with_stop.assert_awaited_once()
    call_kwargs = mock_safety.submit_entry_with_stop.await_args.kwargs
    assert call_kwargs["stop_price"] == 7100.0
    assert call_kwargs["target_price"] is None
    assert result["tp_linked"] is False


# ─── _extract_snapshot_price helper ───────────────────────────────────


def test_extract_snapshot_price_top_level_key() -> None:
    from approval.service import _extract_snapshot_price

    snap = {"stop_price": 7100.0, "target_1": 7200.0}
    assert _extract_snapshot_price(snap, ("stop_price",)) == 7100.0
    assert _extract_snapshot_price(snap, ("target_1", "target_2")) == 7200.0


def test_extract_snapshot_price_nested_decision() -> None:
    """When not at top level, check snapshot['decision']."""
    from approval.service import _extract_snapshot_price

    snap = {"decision": {"stop_price": 7050.0, "target_1": 7150.0}}
    assert _extract_snapshot_price(snap, ("stop_price",)) == 7050.0
    assert _extract_snapshot_price(snap, ("target_1",)) == 7150.0


def test_extract_snapshot_price_key_order_priority() -> None:
    """First matching positive numeric key wins."""
    from approval.service import _extract_snapshot_price

    snap = {"target_1": 7200.0, "target_2": 7300.0}
    # target_1 preferred over target_2 per our ordering
    assert _extract_snapshot_price(snap, ("target_1", "target_2")) == 7200.0


def test_extract_snapshot_price_missing_returns_none() -> None:
    from approval.service import _extract_snapshot_price

    assert _extract_snapshot_price({}, ("stop_price",)) is None
    assert _extract_snapshot_price({"other": 123}, ("stop_price",)) is None


def test_extract_snapshot_price_rejects_non_numeric_and_non_positive() -> None:
    from approval.service import _extract_snapshot_price

    # non-numeric
    assert _extract_snapshot_price({"stop_price": "invalid"}, ("stop_price",)) is None
    # zero or negative → treated as absent
    assert _extract_snapshot_price({"stop_price": 0.0}, ("stop_price",)) is None
    assert _extract_snapshot_price({"stop_price": -5.0}, ("stop_price",)) is None


def test_extract_snapshot_price_handles_none_and_non_dict() -> None:
    from approval.service import _extract_snapshot_price

    assert _extract_snapshot_price(None, ("stop_price",)) is None  # type: ignore[arg-type]
    assert _extract_snapshot_price("not a dict", ("stop_price",)) is None  # type: ignore[arg-type]


def test_extract_snapshot_price_nested_trade_decision_dict() -> None:
    """pipeline_result_for_approval_snapshot stores Trader output under 'trade_decision'."""
    from approval.service import _extract_snapshot_price

    snap = {"trade_decision": {"stop_price": 5980.0, "target_1": 6050.0}}
    assert _extract_snapshot_price(snap, ("stop_price",)) == 5980.0
    assert _extract_snapshot_price(snap, ("target_1",)) == 6050.0


def test_extract_snapshot_price_nested_trade_decision_json_string() -> None:
    """SQLite stores trade_decision as a JSON string; service must deserialize it."""
    import json

    from approval.service import _extract_snapshot_price

    td = {"stop_price": 5980.0, "target_1": 6050.0}
    snap = {"trade_decision": json.dumps(td)}
    assert _extract_snapshot_price(snap, ("stop_price",)) == 5980.0
    assert _extract_snapshot_price(snap, ("target_1",)) == 6050.0


def test_extract_snapshot_price_trade_decision_takes_priority_over_legacy_decision() -> None:
    """trade_decision is checked before the legacy 'decision' key."""
    from approval.service import _extract_snapshot_price

    snap = {
        "trade_decision": {"stop_price": 5980.0},
        "decision": {"stop_price": 5000.0},
    }
    assert _extract_snapshot_price(snap, ("stop_price",)) == 5980.0
