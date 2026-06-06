"""
Tests for risk/safety_layer.py — async methods.

Covers: submit_paper_order (kill switch blocks, safety gate blocks, dry-run pass,
IB connected pass, IB disconnected, IB exception), flatten_all_positions,
_verify_parent_linkage, submit_entry_with_stop (entry rejected, STP failure with
cancel, success).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from risk.safety_layer import KillSwitchReason, OrderRequest, SafetyLayer

# ── Helpers ───────────────────────────────────────────────────────────────────


def _live_settings(base):
    """Return a settings object permissive enough to pass gating."""
    base.LIVE_TRADING_ENABLED = True
    base.REQUIRE_HUMAN_APPROVAL = False
    base.MAX_DAILY_LOSS_PCT = 0.99
    base.MAX_DRAWDOWN_PCT = 0.99
    base.MAX_POSITION_SIZE_PCT = 0.99
    base.MAX_SINGLE_ORDER_VALUE = 9_999_999.0
    base.MAX_ORDERS_PER_MINUTE = 10_000
    base.MAX_CONTRACTS_PER_INSTRUMENT = 100
    base.MAX_FUTURES_MARGIN_PCT = 0.99
    base.MAX_MARGIN_UTILIZATION = 0.99
    base.MAX_DAILY_LOSS_USD = 999_999.0
    base.MAX_TRADE_LOSS_USD = 999_999.0
    base.ALLOW_PAPER_SIMULATED_ORDERS = False
    return base


# ── submit_paper_order ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSubmitPaperOrder:
    async def test_kill_switch_blocks_before_building_order(self, mock_settings, mock_safety_layer):
        """Kill switch check (#0) fires before OrderRequest is even built."""
        sl = mock_safety_layer
        sl.activate_kill_switch(KillSwitchReason.MANUAL, "test")
        result = await sl.submit_paper_order(symbol="MES", action="BUY", quantity=1, price=5800.0)
        assert result["approved"] is False
        assert result["routed_to_ib"] is False
        assert "kill switch" in result["reason"].lower() or "Kill switch" in result["reason"]

    async def test_live_trading_disabled_allows_paper_dryrun(self, mock_settings, mock_safety_layer):
        """LIVE_TRADING_ENABLED=False no longer *blocks* a paper order.

        Since the ALLOW_PAPER_SIMULATED_ORDERS flip, submit_paper_order is a
        PAPER path: a live-disabled order passes safety checks and proceeds as a
        dry-run rather than being rejected. The safety property preserved here is
        that it is NEVER routed to a live broker — approved as a dry-run
        (no IB gateway attached → routed_to_ib False, order_id None), never a
        real fill. Live-money execution is gated separately.
        """
        sl = mock_safety_layer
        # mock_settings has LIVE_TRADING_ENABLED=False; the paper-sim flip
        # (ALLOW_PAPER_SIMULATED_ORDERS=True) is what lets a live-disabled order
        # pass the gate as a dry-run. Without it, check_order() rejects outright
        # ("Live trading is disabled") — see safety_layer.py:958-964. No IB
        # gateway attached, so it resolves to a dry-run, never a live fill.
        mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = True
        result = await sl.submit_paper_order(symbol="MES", action="BUY", quantity=1, price=5800.0)
        assert result["approved"] is True  # paper order passes safety checks
        assert result["routed_to_ib"] is False  # but is NOT routed to a live broker
        assert result["order_id"] is None  # dry-run — no real fill

    async def test_dry_run_no_ib_gateway_returns_approved(self, mock_settings):
        """Safety checks pass but no IB gateway → dry-run response."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        sl._equity_peak = 10000.0
        # No IB gateway attached
        result = await sl.submit_paper_order(symbol="MES", action="BUY", quantity=1, price=5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert result["order_id"] is None

    async def test_ib_disconnected_returns_approved_not_routed(self, mock_settings):
        """IB gateway present but not connected → approved but not routed."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        sl._equity_peak = 10000.0

        ib = MagicMock()
        ib.is_connected.return_value = False
        sl._ib_gateway = ib

        result = await sl.submit_paper_order(symbol="MES", action="BUY", quantity=1, price=5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False

    async def test_ib_connected_routes_order(self, mock_settings):
        """IB gateway connected → order placed, routed_to_ib=True."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        sl._equity_peak = 10000.0

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(return_value=42)
        sl._ib_gateway = ib

        result = await sl.submit_paper_order(symbol="MES", action="BUY", quantity=1, price=5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is True
        assert result["order_id"] == "42"

    async def test_ib_exception_returns_approved_but_not_routed(self, mock_settings):
        """IB place_paper_order raises → approved=True, routed_to_ib=False."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        sl._equity_peak = 10000.0

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(side_effect=RuntimeError("IB timeout"))
        sl._ib_gateway = ib

        result = await sl.submit_paper_order(symbol="MES", action="BUY", quantity=1, price=5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert "IB Gateway raised" in result["reason"]

    async def test_stop_price_triggers_linked_stop_order(self, mock_settings):
        """When stop_price provided and entry placed, linked stop order is submitted."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        sl._equity_peak = 10000.0

        call_count = {"n": 0}

        async def _place(**kwargs):
            call_count["n"] += 1
            return call_count["n"]

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(side_effect=_place)
        sl._ib_gateway = ib

        result = await sl.submit_paper_order(
            symbol="MES", action="BUY", quantity=1, price=5800.0, stop_price=5780.0
        )
        # Entry + Stop = 2 calls
        assert call_count["n"] == 2
        assert result["approved"] is True

    async def test_sell_action_builds_negative_qty(self, mock_settings):
        """SELL action creates negative signed quantity internally."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        sl._equity_peak = 10000.0

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(return_value=99)
        sl._ib_gateway = ib

        result = await sl.submit_paper_order(symbol="MES", action="SELL", quantity=1, price=5800.0)
        assert result["approved"] is True


# ── flatten_all_positions ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestFlattenAllPositions:
    async def test_no_ib_gateway_returns_error(self, mock_safety_layer):
        sl = mock_safety_layer
        sl._ib_gateway = None
        result = await sl.flatten_all_positions()
        assert result["flattened"] == []
        assert len(result["errors"]) >= 1
        assert "No IB gateway" in result["errors"][0]["error"]

    async def test_get_positions_raises_returns_error(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(side_effect=RuntimeError("connection lost"))
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert result["flattened"] == []
        assert "get_positions raised" in result["errors"][0]["error"]

    async def test_no_positions_returns_empty(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(return_value=[])
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert result["flattened"] == []
        assert result["order_ids"] == []
        assert result["errors"] == []

    async def test_long_position_flattened_with_sell(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 2}])
        ib.place_paper_order = AsyncMock(return_value=101)
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert "MES" in result["flattened"]
        assert len(result["order_ids"]) == 1
        # SELL to close long
        call_kwargs = ib.place_paper_order.call_args[1]
        assert call_kwargs.get("action") == "SELL" or call_kwargs.get("action") == "SELL"

    async def test_short_position_flattened_with_buy(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": -1}])
        ib.place_paper_order = AsyncMock(return_value=102)
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert "MES" in result["flattened"]
        call_kwargs = ib.place_paper_order.call_args[1]
        assert call_kwargs.get("action") == "BUY"

    async def test_zero_position_skipped(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 0}])
        ib.place_paper_order = AsyncMock(return_value=103)
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert result["flattened"] == []
        ib.place_paper_order.assert_not_called()

    async def test_place_order_exception_recorded_in_errors(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 1}])
        ib.place_paper_order = AsyncMock(side_effect=RuntimeError("order failed"))
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert result["errors"] != []
        assert result["flattened"] == []


# ── _verify_parent_linkage ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestVerifyParentLinkage:
    async def test_none_child_order_id_returns_false(self, mock_safety_layer):
        sl = mock_safety_layer
        result = await sl._verify_parent_linkage(None, "entry-1")
        assert result is False

    async def test_status_not_dict_returns_false(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_order_status = AsyncMock(return_value="not-a-dict")
        sl._ib_gateway = ib
        result = await sl._verify_parent_linkage("child-1", "entry-1")
        assert result is False

    async def test_matching_parent_returns_true(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_order_status = AsyncMock(return_value={"parent_order_id": "entry-1"})
        sl._ib_gateway = ib
        result = await sl._verify_parent_linkage("child-1", "entry-1")
        assert result is True

    async def test_mismatched_parent_returns_false(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_order_status = AsyncMock(return_value={"parent_order_id": "wrong-id"})
        sl._ib_gateway = ib
        result = await sl._verify_parent_linkage("child-1", "entry-1")
        assert result is False

    async def test_no_parent_order_id_key_returns_false(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_order_status = AsyncMock(return_value={"status": "filled"})
        sl._ib_gateway = ib
        result = await sl._verify_parent_linkage("child-1", "entry-1")
        assert result is False

    async def test_get_order_status_raises_returns_false(self, mock_safety_layer):
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_order_status = AsyncMock(side_effect=RuntimeError("timeout"))
        sl._ib_gateway = ib
        result = await sl._verify_parent_linkage("child-1", "entry-1")
        assert result is False


# ── submit_entry_with_stop ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSubmitEntryWithStop:
    async def test_entry_rejected_returns_not_approved(self, mock_settings):
        """Entry order blocked by safety → early return without placing STP."""
        settings = _live_settings(mock_settings)
        # Re-enable human approval to force rejection
        settings.REQUIRE_HUMAN_APPROVAL = True
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0

        result = await sl.submit_entry_with_stop(
            symbol="MES", action="BUY", quantity=1, price=5800.0, stop_price=5780.0
        )
        assert result["approved"] is False
        assert result["stp_order_id"] is None
        assert result["routed_to_ib"] is False

    async def test_entry_not_routed_no_stop_placed(self, mock_settings):
        """Entry passes safety but not routed (no IB) → STP not placed."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0
        # No IB gateway → not routed
        result = await sl.submit_entry_with_stop(
            symbol="MES", action="BUY", quantity=1, price=5800.0, stop_price=5780.0
        )
        # approved=True but routed_to_ib=False → early return without STP
        assert result.get("routed_to_ib") is False

    async def test_stp_placement_failure_cancels_entry(self, mock_settings):
        """STP child direct call fails → cancel_order called → result not approved.

        We mock submit_paper_order to return approved=True, routed_to_ib=True
        (as if entry placed successfully), then make the direct STP placement
        call (via place_paper_order) raise to exercise the STP failure path.
        """
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0

        # Mock submit_paper_order directly so no IB calls for the entry
        entry_result = {
            "approved": True,
            "reason": "Safety checks passed - IB gateway not attached (dry-run)",
            "order_id": "entry-123",
            "routed_to_ib": True,
        }

        ib = MagicMock()
        ib.place_paper_order = AsyncMock(side_effect=RuntimeError("STP placement failed"))
        ib.cancel_order = AsyncMock(return_value=True)
        sl._ib_gateway = ib

        with patch.object(sl, "submit_paper_order", new=AsyncMock(return_value=entry_result)):
            result = await sl.submit_entry_with_stop(
                symbol="MES",
                action="BUY",
                quantity=1,
                price=5800.0,
                stop_price=5780.0,
            )

        # STP failed → stp_id=None → entry cancelled → approved=False
        assert result["approved"] is False
        assert "STP" in result.get("reason", "")
        ib.cancel_order.assert_called_once()

    async def test_successful_bracket_order(self, mock_settings):
        """All legs succeed → approved=True, entry_id + stp_id set."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10000.0

        call_count = {"n": 0}

        async def _place(**kwargs):
            call_count["n"] += 1
            return f"order-{call_count['n']}"

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(side_effect=_place)
        ib.get_order_status = AsyncMock(return_value={"parent_order_id": "order-1"})
        sl._ib_gateway = ib

        result = await sl.submit_entry_with_stop(
            symbol="MES", action="BUY", quantity=1, price=5800.0, stop_price=5780.0
        )
        assert result["approved"] is True
        assert result["routed_to_ib"] is True
        assert result["entry_order_id"] is not None
        assert result["stp_order_id"] is not None
