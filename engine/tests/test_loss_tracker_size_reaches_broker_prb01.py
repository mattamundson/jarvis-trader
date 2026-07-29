"""PRB-01 regression tests — loss-tracker size reduction must reach the broker.

Bug (2026-07-29 prod-readiness audit): SafetyLayer._apply_loss_tracker_adjustment
correctly halves/quarters order size after 3/5 consecutive losses and returns it
as RiskCheckResult.adjusted_order, but every real order-submission call site
discarded that and built the broker order from the ORIGINAL quantity instead:

  - SafetyLayer.submit_paper_order (risk/safety_layer.py)
  - IBKRExecutor.submit_order (execution/ibkr_executor.py) — "CRITICAL PATH"
  - SchwabConnector._run_safety_check + place_paper_order (execution/schwab_connector.py)
  - IBGatewayConnector.submit_order (execution/ib_gateway_connector.py) — the
    OrderRouter's live futures/equity paper-fill path; same defect shape, found
    while fixing the three call sites named in the original audit.

Net effect: after a losing streak, the safety layer believed it had de-risked
(reduced size) while full-size orders still reached the broker/paper-fill path.
NOT behind a disabled feature flag — live in production.

Each test below drives a REAL SafetyLayer + REAL ConsecutiveLossTracker through
3 losses (-> 0.5x) or 5 losses (-> 0.25x), submits an order, and asserts the
quantity that actually reaches the broker/paper-fill path is the REDUCED size,
not the original request.
"""

from __future__ import annotations

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.schwab_connector import ConnectionState, SchwabConnector
from execution.ibkr_executor import IB_AVAILABLE, IBKRExecutor
from execution.ib_gateway_connector import IBGatewayConnector
from risk.loss_tracker import ConsecutiveLossTracker
from risk.safety_layer import SafetyLayer

# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def prb01_settings(mock_settings):
    """conftest's mock_settings, tuned for loss-tracker order-submission tests.

    Mirrors test_loss_tracker.py's loss_tracker_settings fixture: live-trading
    gate open enough to reach check_order()'s loss-tracker branch, contract
    limits loosened so they don't mask the loss-tracker's own reduction, and
    the overnight-contract cap raised (MAX_OVERNIGHT_CONTRACTS default=1 would
    reject a qty=4 order outright whenever the suite runs after 15:00 CT,
    masking the assertion this file cares about).
    """
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = False
    mock_settings.CONSECUTIVE_LOSS_HALF_SIZE = 3
    mock_settings.CONSECUTIVE_LOSS_QUARTER_SIZE = 5
    mock_settings.CONSECUTIVE_LOSS_HALT = 7
    mock_settings.CONSECUTIVE_LOSS_HALT_HOURS = 24
    mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 10
    mock_settings.MAX_OVERNIGHT_CONTRACTS = 10
    mock_settings.MAX_SINGLE_ORDER_VALUE = 500_000.0
    mock_settings.MAX_POSITION_SIZE_PCT = 0.50
    # SafetyLayer seeds equity from INITIAL_CAPITAL=$10,000 when no live
    # broker/db equity is available (see "seeded from INITIAL_CAPITAL" log).
    # A 4-contract MES order's margin (~$5,280) exceeds the default
    # MAX_FUTURES_MARGIN_PCT=30% of that; raise the ceiling so the futures
    # margin gate doesn't mask the loss-tracker assertions these tests exist
    # to check.
    mock_settings.MAX_FUTURES_MARGIN_PCT = 0.95
    # A 4-contract MES entry with a 30-point stop trips MAX_TRADE_LOSS_USD's
    # default per-ticket ceiling; raise it so the stop-leg-sizing tests (which
    # need a real stop_price to exercise the STP-leg code path) aren't masked
    # by an unrelated gate.
    mock_settings.MAX_TRADE_LOSS_USD = 10_000.0
    mock_settings.PAPER_TRADING = True
    mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = True
    mock_settings.IBKR_HOST = "127.0.0.1"
    mock_settings.IBKR_PORT = 4002
    mock_settings.IBKR_CLIENT_ID = 11
    return mock_settings


def _tracker_with_losses(tmpdir: str, n: int) -> ConsecutiveLossTracker:
    """A ConsecutiveLossTracker with `n` recorded consecutive losses on MES."""
    tracker = ConsecutiveLossTracker(
        data_dir=tmpdir,
        consecutive_loss_half_size=3,
        consecutive_loss_quarter_size=5,
        consecutive_loss_halt=7,
    )
    for _ in range(n):
        tracker.record_trade("MES", -100.0)
    return tracker


# ══════════════════════════════════════════════════════════════════════════
# 1. SafetyLayer.submit_paper_order (+ submit_entry_with_stop)
# ══════════════════════════════════════════════════════════════════════════


class TestSubmitPaperOrderAppliesReduction:
    """Entry AND its linked STP child must both carry the reduced quantity."""

    async def _connected_pair(self, settings, tracker):
        safety = SafetyLayer(settings, loss_tracker=tracker)
        conn = IBGatewayConnector(settings, safety)
        assert await conn.connect() is True
        safety.attach_ib_gateway(conn)
        return safety, conn

    @pytest.mark.asyncio
    async def test_half_size_after_three_losses(self, prb01_settings, tmp_path):
        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety, conn = await self._connected_pair(prb01_settings, tracker)

        result = await safety.submit_paper_order(
            symbol="MES", action="BUY", quantity=4, price=7130.0, order_type="MKT"
        )

        assert result["approved"] is True, result
        assert result["routed_to_ib"] is True, result
        assert result["quantity"] == 2, (
            f"3 losses -> 0.5x multiplier: requested 4, expected 2 reaching the "
            f"broker, got {result['quantity']}"
        )
        # The actual paper fill (position delta) must match, not just the
        # dict's self-reported "quantity" field.
        assert conn._positions.get("MES") == 2

    @pytest.mark.asyncio
    async def test_quarter_size_after_five_losses(self, prb01_settings, tmp_path):
        tracker = _tracker_with_losses(str(tmp_path), 5)
        safety, conn = await self._connected_pair(prb01_settings, tracker)

        result = await safety.submit_paper_order(
            symbol="MES", action="BUY", quantity=4, price=7130.0, order_type="MKT"
        )

        assert result["approved"] is True, result
        assert result["routed_to_ib"] is True, result
        assert result["quantity"] == 1, (
            f"5 losses -> 0.25x multiplier: requested 4, expected 1 (floored by "
            f"max(1, ...)) reaching the broker, got {result['quantity']}"
        )
        assert conn._positions.get("MES") == 1

    @pytest.mark.asyncio
    async def test_no_reduction_with_no_losses(self, prb01_settings, tmp_path):
        """Control: with zero losses the full requested size must still go out."""
        tracker = _tracker_with_losses(str(tmp_path), 0)
        safety, conn = await self._connected_pair(prb01_settings, tracker)

        result = await safety.submit_paper_order(
            symbol="MES", action="BUY", quantity=4, price=7130.0, order_type="MKT"
        )

        assert result["approved"] is True, result
        assert result["quantity"] == 4
        assert conn._positions.get("MES") == 4

    @pytest.mark.asyncio
    async def test_linked_stop_leg_matches_reduced_entry(self, prb01_settings, tmp_path):
        """The STP child order built inside submit_paper_order must also carry
        the reduced size -- a full-size stop protecting a half-size entry would
        (on trigger) sell more than is actually held."""
        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety, conn = await self._connected_pair(prb01_settings, tracker)

        result = await safety.submit_paper_order(
            symbol="MES",
            action="BUY",
            quantity=4,
            price=7130.0,
            order_type="MKT",
            stop_price=7100.0,
        )

        assert result["approved"] is True, result
        assert result["quantity"] == 2

        # Exactly one STP child should be open, sized to match the entry.
        stp_orders = [o for o in conn._open_orders.values() if o.get("order_type") == "stop"]
        assert len(stp_orders) == 1, conn._open_orders
        assert abs(stp_orders[0]["quantity"]) == 2, (
            f"STP leg must match the reduced entry size (2), got "
            f"{stp_orders[0]['quantity']}"
        )


class TestSubmitEntryWithStopAppliesReduction:
    """submit_entry_with_stop's separately-placed STP/TP legs must match the
    ACTUAL (risk-adjusted) entry size, not the caller's raw `quantity` arg --
    otherwise a reduced entry ends up paired with an oversized stop/target."""

    @pytest.mark.asyncio
    async def test_stop_and_target_match_reduced_entry(self, prb01_settings, tmp_path):
        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        conn = IBGatewayConnector(prb01_settings, safety)
        assert await conn.connect() is True
        safety.attach_ib_gateway(conn)

        result = await safety.submit_entry_with_stop(
            symbol="MES",
            action="BUY",
            quantity=4,
            price=7130.0,
            stop_price=7100.0,
            target_price=7160.0,
        )

        assert result["approved"] is True, result
        assert result["routed_to_ib"] is True, result
        assert result["stp_order_id"] is not None
        assert conn._positions.get("MES") == 2, (
            "Entry must be risk-adjusted to 2 (0.5x after 3 losses)"
        )
        stp = conn._open_orders[result["stp_order_id"]]
        assert abs(stp["quantity"]) == 2, (
            f"STP child must match the reduced entry (2), got {stp['quantity']} "
            "-- an oversized stop would open an unintended new position on trigger"
        )


# ══════════════════════════════════════════════════════════════════════════
# 2. IBKRExecutor.submit_order — "CRITICAL PATH"
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not IB_AVAILABLE, reason="ib_async not installed")
class TestIBKRExecutorSubmitOrderAppliesReduction:
    @pytest.mark.asyncio
    async def test_half_size_after_three_losses(self, prb01_settings, tmp_path):
        from risk.safety_layer import OrderRequest

        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        executor = IBKRExecutor(prb01_settings, safety)
        executor._ib = MagicMock()
        executor._ib.isConnected.return_value = True
        executor._ib.qualifyContractsAsync = AsyncMock(return_value=None)
        executor._ib.placeOrder = MagicMock(return_value=MagicMock())

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=1000.0,
            is_futures=True,
        )
        result = await executor.submit_order(order, portfolio_equity=50_000.0)

        assert result["submitted"] is True, result
        assert result["quantity"] == 2, (
            f"3 losses -> 0.5x multiplier: requested 4, expected 2 submitted to "
            f"IBKR, got {result['quantity']}"
        )
        # The actual ib_async Order object placed with IBKR must carry the
        # reduced size, not just the returned dict.
        placed_order_arg = executor._ib.placeOrder.call_args.args[1]
        assert placed_order_arg.totalQuantity == 2

    @pytest.mark.asyncio
    async def test_quarter_size_after_five_losses(self, prb01_settings, tmp_path):
        from risk.safety_layer import OrderRequest

        tracker = _tracker_with_losses(str(tmp_path), 5)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        executor = IBKRExecutor(prb01_settings, safety)
        executor._ib = MagicMock()
        executor._ib.isConnected.return_value = True
        executor._ib.qualifyContractsAsync = AsyncMock(return_value=None)
        executor._ib.placeOrder = MagicMock(return_value=MagicMock())

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=1000.0,
            is_futures=True,
        )
        result = await executor.submit_order(order, portfolio_equity=50_000.0)

        assert result["submitted"] is True, result
        assert result["quantity"] == 1, (
            f"5 losses -> 0.25x multiplier: requested 4, expected 1 submitted to "
            f"IBKR, got {result['quantity']}"
        )
        placed_order_arg = executor._ib.placeOrder.call_args.args[1]
        assert placed_order_arg.totalQuantity == 1

    @pytest.mark.asyncio
    async def test_no_reduction_with_no_losses(self, prb01_settings, tmp_path):
        """Control: with zero losses the full requested size must still be sent."""
        from risk.safety_layer import OrderRequest

        tracker = _tracker_with_losses(str(tmp_path), 0)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        executor = IBKRExecutor(prb01_settings, safety)
        executor._ib = MagicMock()
        executor._ib.isConnected.return_value = True
        executor._ib.qualifyContractsAsync = AsyncMock(return_value=None)
        executor._ib.placeOrder = MagicMock(return_value=MagicMock())

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=1000.0,
            is_futures=True,
        )
        result = await executor.submit_order(order, portfolio_equity=50_000.0)

        assert result["submitted"] is True, result
        assert result["quantity"] == 4
        placed_order_arg = executor._ib.placeOrder.call_args.args[1]
        assert placed_order_arg.totalQuantity == 4


# ══════════════════════════════════════════════════════════════════════════
# 3. SchwabConnector._run_safety_check + place_paper_order (equity path)
# ══════════════════════════════════════════════════════════════════════════


class TestSchwabConnectorPlacePaperOrderAppliesReduction:
    def _connector(self, safety):
        settings = MagicMock()
        settings.SCHWAB_READY = True
        conn = SchwabConnector(settings=settings, safety_layer=safety)
        conn._state = ConnectionState.CONNECTED
        conn._client = MagicMock()
        conn._account_hash = "TESTHASH12345678"
        return conn

    @pytest.mark.asyncio
    async def test_run_safety_check_returns_adjusted_order(self, prb01_settings, tmp_path):
        """Direct contract test: _run_safety_check's 4th return value must be
        the risk layer's adjusted_order, not silently dropped."""
        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        conn = self._connector(safety)

        approved, reason, warnings, adjusted_order = conn._run_safety_check(
            symbol="MES",
            quantity=4,
            order_type="market",
            limit_price=None,
            portfolio_equity=50_000.0,
            is_futures=True,
        )

        assert approved is True, reason
        assert adjusted_order is not None, (
            "adjusted_order must be populated when the loss tracker reduces size"
        )
        assert adjusted_order.quantity == 2

    @pytest.mark.asyncio
    async def test_place_paper_order_uses_adjusted_quantity(self, prb01_settings, tmp_path):
        """End-to-end: place_paper_order must route the RISK-ADJUSTED quantity
        to submit_equity_order, not the caller's original request."""
        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        conn = self._connector(safety)

        captured = {}

        async def _fake_submit_equity_order(**kwargs):
            captured.update(kwargs)
            return {"status": "placed", "order_id": "abc123"}

        conn.submit_equity_order = _fake_submit_equity_order

        order = {
            "symbol": "SPY",
            "quantity": 4,
            "side": "BUY",
            "order_type": "market",
            "portfolio_equity": 50_000.0,
        }
        result = await conn.place_paper_order(order)

        assert result["status"] == "placed", result
        assert captured.get("quantity") == 2, (
            f"3 losses -> 0.5x multiplier: requested 4, expected submit_equity_order "
            f"called with quantity=2, got {captured.get('quantity')}"
        )

    @pytest.mark.asyncio
    async def test_place_paper_order_no_reduction_with_no_losses(self, prb01_settings, tmp_path):
        """Control: zero losses -> full requested size passed through."""
        tracker = _tracker_with_losses(str(tmp_path), 0)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        conn = self._connector(safety)

        captured = {}

        async def _fake_submit_equity_order(**kwargs):
            captured.update(kwargs)
            return {"status": "placed", "order_id": "abc123"}

        conn.submit_equity_order = _fake_submit_equity_order

        order = {
            "symbol": "SPY",
            "quantity": 4,
            "side": "BUY",
            "order_type": "market",
            "portfolio_equity": 50_000.0,
        }
        result = await conn.place_paper_order(order)

        assert result["status"] == "placed", result
        assert captured.get("quantity") == 4


# ══════════════════════════════════════════════════════════════════════════
# 4. IBGatewayConnector.submit_order — OrderRouter's live futures/equity path
#    (found while fixing the 3 named call sites; same defect shape, same fix)
# ══════════════════════════════════════════════════════════════════════════


class TestIBGatewayConnectorSubmitOrderAppliesReduction:
    @pytest.mark.asyncio
    async def test_half_size_after_three_losses(self, prb01_settings, tmp_path):
        tracker = _tracker_with_losses(str(tmp_path), 3)
        safety = SafetyLayer(prb01_settings, loss_tracker=tracker)
        conn = IBGatewayConnector(prb01_settings, safety)
        assert await conn.connect() is True

        result = await conn.submit_order(
            {
                "symbol": "MES",
                "quantity": 4,
                "order_type": "market",
                "is_futures": True,
            },
            portfolio_equity=50_000.0,
        )

        assert result["status"] == "placed", result
        assert result["quantity"] == 2, (
            f"3 losses -> 0.5x multiplier: requested 4, expected 2 filled, "
            f"got {result['quantity']}"
        )
        assert conn._positions.get("MES") == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
