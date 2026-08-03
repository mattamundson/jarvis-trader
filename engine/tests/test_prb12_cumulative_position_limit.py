"""
PRB-12 regression: check_order() must bound the RESULTING position after an
order, not just the order's own size.

2026-07-29 prod-readiness audit found a naked 58-lot MES/MNQ position slipped
through because no check anywhere in SafetyLayer.check_order() read the
existing broker-reported position before approving the next order -- a
sequence of individually-compliant orders could accumulate without bound.
_check_cumulative_position_limit() (safety_layer.py) closes that gap by
reading IBGatewayConnector._positions.
"""

import pytest

from risk.safety_layer import OrderRequest, SafetyLayer


class _FakeIBGateway:
    """Minimal stand-in for IBGatewayConnector exposing only what the
    cumulative-position check reads: a symbol -> signed-quantity dict."""

    def __init__(self, positions: dict[str, int]):
        self._positions = positions


class TestCumulativePositionLimit:
    def _live_safety(self, mock_settings) -> SafetyLayer:
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        # Bypass overnight cap so the test is wall-clock-independent, matching
        # the existing TestFuturesContractLimit convention.
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
        return SafetyLayer(mock_settings)

    def test_order_within_own_limit_rejected_by_cumulative_position(
        self, mock_settings
    ):
        """2 MES already held + 1 more (itself within the per-order cap of 2)
        would result in 3 -- exceeds MAX_CONTRACTS_PER_INSTRUMENT and must be
        rejected, even though _check_contract_limits alone would approve it."""
        safety = self._live_safety(mock_settings)
        safety.attach_ib_gateway(_FakeIBGateway({"MES": 2}))

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=1000.0,
        )

        result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "CUMULATIVE_POSITION_LIMIT" in result.rejection_reason

    def test_order_within_resulting_limit_approved(self, mock_settings):
        """0 held + 2 requested = 2, at the limit -> approved."""
        safety = self._live_safety(mock_settings)
        safety.attach_ib_gateway(_FakeIBGateway({}))

        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=2000.0,
        )

        result = safety.check_order(order, 100_000.0)

        assert result.approved is True, result.rejection_reason

    def test_short_side_resulting_position_also_bounded(self, mock_settings):
        """-2 held (short) + -1 more = -3 -- magnitude 3 exceeds the limit of
        2 regardless of sign."""
        safety = self._live_safety(mock_settings)
        safety.attach_ib_gateway(_FakeIBGateway({"MES": -2}))

        order = OrderRequest(
            symbol="MES",
            quantity=-1,
            order_type="market",
            is_futures=True,
            estimated_value=1000.0,
        )

        result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "CUMULATIVE_POSITION_LIMIT" in result.rejection_reason

    def test_no_gateway_attached_check_no_ops(self, mock_settings):
        """No IB Gateway attached (e.g. Schwab-only equity paths, most unit
        tests) -- there is no broker-truth position source, so the cumulative
        check must not block or raise; order still passes on its own merits."""
        safety = self._live_safety(mock_settings)
        # No attach_ib_gateway() call -- self._ib_gateway stays None.

        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=2000.0,
        )

        result = safety.check_order(order, 100_000.0)

        assert result.approved is True, result.rejection_reason

    def test_non_futures_order_not_affected(self, mock_settings):
        """Equity/options orders skip the cumulative check entirely -- it is
        scoped to futures, mirroring _check_contract_limits."""
        safety = self._live_safety(mock_settings)
        safety.attach_ib_gateway(_FakeIBGateway({"SPY": 500}))

        order = OrderRequest(
            symbol="SPY",
            quantity=10,
            order_type="market",
            is_futures=False,
            estimated_value=1000.0,
        )

        result = safety._check_cumulative_position_limit(order)

        assert result.approved is True
