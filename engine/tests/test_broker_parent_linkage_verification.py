"""
US-011 — SafetyLayer parent-linkage flag drift regression tests.

Context: safety_layer.py:1217-1219 previously set stp_linked/tp_linked based
solely on "place_paper_order returned a non-None order_id". That meant the
flags said True even when IBKR did not actually echo parent_order_id,
violating the docstring claim. The fix reads back via get_order_status()
and sets flags from actual IB truth.

These tests lock BOTH directions:
  - Happy path: IB echoes parent_id → flag True (covered by existing tests)
  - Drift path: IB does NOT echo parent_id → flag False (THIS FILE)
  - Read-back error path: get_order_status raises → flag False (THIS FILE)

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_broker_parent_linkage_verification.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def paper_safety():
    """``ALLOW_MOCK_QUOTES`` is required (2026-07-21, see
    ``test_ib_gateway_connector_offline.py``): no market-data manager is
    attached here, so the static quote table is needed to produce a fill at
    all. Production leaves this False and refuses to fill without a real
    price basis -- see ``test_paper_fill_refuses_mock_price.py``.
    """
    from config import settings
    from risk.safety_layer import SafetyLayer

    cfg = settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": False,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "ALLOW_MOCK_QUOTES": True,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
            "MAX_TRADE_LOSS_USD": 500.0,
        }
    )
    return SafetyLayer(cfg, pnl_monitor=None)


# ─────────────────────────────────────────────────────────────────────────────
# _verify_parent_linkage helper — direct unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyParentLinkage:
    @pytest.mark.asyncio
    async def test_returns_false_when_child_id_none(self, paper_safety):
        """No child id → can't verify, must return False (never optimistic)."""
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock()
        assert await paper_safety._verify_parent_linkage(None, "PARENT-1") is False
        # Must NOT have queried the broker — no child id means nothing to verify.
        paper_safety._ib_gateway.get_order_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_true_when_parent_matches(self, paper_safety):
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock(
            return_value={"order_id": "CHILD-1", "parent_order_id": "PARENT-1"}
        )
        assert await paper_safety._verify_parent_linkage("CHILD-1", "PARENT-1") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_parent_missing_from_status(self, paper_safety):
        """IB drift case: broker stored the order but didn't set parent_order_id."""
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock(
            return_value={"order_id": "CHILD-1", "parent_order_id": None}
        )
        assert await paper_safety._verify_parent_linkage("CHILD-1", "PARENT-1") is False

    @pytest.mark.asyncio
    async def test_returns_false_when_parent_mismatches(self, paper_safety):
        """Different parent id — flag must NOT be True just because some parent exists."""
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock(
            return_value={"order_id": "CHILD-1", "parent_order_id": "SOME-OTHER-PARENT"}
        )
        assert await paper_safety._verify_parent_linkage("CHILD-1", "PARENT-1") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_get_order_status_exception(self, paper_safety):
        """If broker read-back raises, fall back to pessimistic False."""
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock(
            side_effect=RuntimeError("IB connection dropped")
        )
        assert await paper_safety._verify_parent_linkage("CHILD-1", "PARENT-1") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_nondict_status(self, paper_safety):
        """Some broker paths may return str/None on not-found — must not crash."""
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock(return_value=None)
        assert await paper_safety._verify_parent_linkage("CHILD-1", "PARENT-1") is False

    @pytest.mark.asyncio
    async def test_string_vs_int_parent_ids_match(self, paper_safety):
        """IB returns parentId as int; SafetyLayer passes entry_id as str. str cast must bridge."""
        paper_safety._ib_gateway = MagicMock()
        paper_safety._ib_gateway.get_order_status = AsyncMock(
            return_value={"order_id": 42, "parent_order_id": 17}
        )
        # entry_id as string "17", broker returns int 17 → should match
        assert await paper_safety._verify_parent_linkage("42", "17") is True


# ─────────────────────────────────────────────────────────────────────────────
# submit_entry_with_stop integration — drift surfaces in returned flags
# ─────────────────────────────────────────────────────────────────────────────


class TestSubmitEntryFlagDrift:
    @pytest.mark.asyncio
    async def test_stp_linked_false_when_broker_does_not_echo_parent(self, paper_safety, tmp_path):
        """
        Regression: submit_entry_with_stop must return stp_linked=False if
        the broker accepted the child order but didn't echo parent_order_id.
        This is the exact silent-failure mode US-011 fixes.
        """
        from execution.ib_gateway_connector import IBGatewayConnector
        from portfolio.tracker import PortfolioTracker

        tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
        conn = IBGatewayConnector(
            paper_safety._config,
            paper_safety,
            portfolio_tracker=tracker,
            trades_file=tmp_path / "paper_trades.json",
        )
        await conn.connect()
        paper_safety.attach_ib_gateway(conn)

        # Monkey-patch get_order_status to simulate IB drift: order exists but
        # parent_order_id is missing. place_paper_order still returns a valid id.
        original_get_order_status = conn.get_order_status

        async def drifted_status(order_id: str) -> dict:
            real = await original_get_order_status(order_id)
            if isinstance(real, dict):
                real = dict(real)
                real["parent_order_id"] = None  # drift
            return real

        conn.get_order_status = drifted_status  # type: ignore[assignment]

        result = await paper_safety.submit_entry_with_stop(
            symbol="MES",
            action="BUY",
            quantity=1,
            price=7130.0,
            stop_price=7100.0,
            target_price=7190.0,
        )

        # STP child got an ID (broker accepted) — but linkage is broken
        assert result["stp_order_id"] is not None
        # TP is intentionally skipped in paper mode (paper connector fills LMT immediately)
        assert result["tp_order_id"] is None
        assert (
            result["stp_linked"] is False
        ), "stp_linked must be False when broker did not echo parent_order_id"
        # tp_linked is False because no TP was placed (tp_order_id is None)
        assert result["tp_linked"] is False

    @pytest.mark.asyncio
    async def test_stp_linked_true_when_broker_echoes_parent_correctly(
        self, paper_safety, tmp_path
    ):
        """
        Happy path regression: when the broker honors parent_order_id,
        stp_linked + tp_linked should be True. This re-asserts the existing
        behavior survives the semantic change.
        """
        from execution.ib_gateway_connector import IBGatewayConnector
        from portfolio.tracker import PortfolioTracker

        tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
        conn = IBGatewayConnector(
            paper_safety._config,
            paper_safety,
            portfolio_tracker=tracker,
            trades_file=tmp_path / "paper_trades.json",
        )
        await conn.connect()
        paper_safety.attach_ib_gateway(conn)

        result = await paper_safety.submit_entry_with_stop(
            symbol="MES",
            action="BUY",
            quantity=1,
            price=7130.0,
            stop_price=7100.0,
            target_price=7190.0,
        )

        assert result["stp_linked"] is True
        # TP is skipped in paper mode (paper connector fills LMT immediately)
        assert result["tp_order_id"] is None
        assert result["tp_linked"] is False
