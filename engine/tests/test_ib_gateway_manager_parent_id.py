"""
Q2-P2.7 Stage 3 — Red regression tests for IBGatewayManager parent-id wiring.

Closes the gap left by Stage 2 (d01bd28):
    IBGatewayConnector.place_paper_order accepts parent_order_id and records
    it in _open_orders, but IBGatewayManager (the ib_insync-wrapped real-paper
    path used when ALLOW_PAPER_SIMULATED_ORDERS=False, e.g. test_ib_paper_e2e)
    has NO parent_order_id kwarg and does NOT set Order.parentId on the
    placed order. That breaks STP-parent linkage for real paper round-trips.

Stage 3 (follow-up commit) will:
    1. Add parent_order_id: Optional[int] = None kwarg to
       IBGatewayManager.place_paper_order
    2. Assign ib_order.parentId = parent_order_id before self._ib.placeOrder(...)
    3. Log the parent linkage alongside the existing order-placed log line

Both tests below SHOULD FAIL until Stage 3 lands.
Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_ib_gateway_manager_parent_id.py -v
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


def _build_manager_with_mocked_ib():
    """Return an IBGatewayManager with a fake _ib that records placeOrder args."""
    from execution.ib_gateway import IBConnectionStatus, IBGatewayConfig, IBGatewayManager

    mgr = IBGatewayManager(IBGatewayConfig(host="127.0.0.1", port=4002, client_id=99))

    fake_ib = MagicMock()
    fake_ib.isConnected = MagicMock(return_value=True)

    fake_trade = MagicMock()
    fake_trade.order = MagicMock()
    fake_trade.order.orderId = 7777
    fake_ib.placeOrder = MagicMock(return_value=fake_trade)

    mgr._ib = fake_ib
    mgr._status = IBConnectionStatus.CONNECTED

    async def _fake_qualify(contract):
        return contract

    mgr._qualify_contract = _fake_qualify

    def _fake_resolve(symbol):
        return MagicMock(symbol=symbol)

    mgr._resolve_contract = _fake_resolve
    return mgr, fake_ib


@pytest.mark.asyncio
async def test_ib_gateway_manager_place_paper_order_accepts_parent_order_id():
    """
    IBGatewayManager.place_paper_order must accept parent_order_id kwarg.

    Stage 3 expectation: this call succeeds and returns the mocked order id.
    Pre-Stage 3: fails with TypeError (unexpected keyword argument).
    """
    pytest.importorskip("ib_async")
    mgr, _ = _build_manager_with_mocked_ib()

    order_id = await mgr.place_paper_order(
        symbol="MES",
        action="SELL",
        quantity=1,
        order_type="STP",
        aux_price=7000.0,
        parent_order_id=1234,
    )
    assert order_id == 7777


@pytest.mark.asyncio
async def test_ib_gateway_manager_sets_parent_id_on_ib_order():
    """
    When parent_order_id is passed, the ib_insync Order object placed on the
    broker must carry Order.parentId == parent_order_id so IB links the STP
    child to the parent entry fill.

    Stage 3 expectation: ib_order.parentId == 1234.
    Pre-Stage 3: fails with TypeError on the kwarg call, OR (if we ignore the
    kwarg) ib_order.parentId is the ib_insync default (0).
    """
    pytest.importorskip("ib_async")
    mgr, fake_ib = _build_manager_with_mocked_ib()

    await mgr.place_paper_order(
        symbol="MES",
        action="SELL",
        quantity=1,
        order_type="STP",
        aux_price=7000.0,
        parent_order_id=1234,
    )

    assert fake_ib.placeOrder.called, "_ib.placeOrder was never called"
    placed_order = fake_ib.placeOrder.call_args.args[1]
    assert getattr(placed_order, "parentId", None) == 1234, (
        f"Expected parentId=1234 on placed STP order, got "
        f"{getattr(placed_order, 'parentId', 'MISSING')}"
    )


@pytest.mark.asyncio
async def test_ib_gateway_manager_omits_parent_id_for_standalone_orders():
    """
    When parent_order_id is not passed (standalone MKT entry), ib_order.parentId
    should stay at the ib_insync default (0). We only assert the order is
    placed and the test doesn't raise — the default is unchanged by Stage 3.
    """
    pytest.importorskip("ib_async")
    mgr, fake_ib = _build_manager_with_mocked_ib()

    order_id = await mgr.place_paper_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        order_type="MKT",
    )
    assert order_id == 7777
    placed_order = fake_ib.placeOrder.call_args.args[1]
    assert getattr(placed_order, "parentId", 0) == 0
