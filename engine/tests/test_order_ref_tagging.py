"""
Blocker A (execution-fidelity forward-test) — orderRef tagging tests.

DUP662235 (the IB paper account) carries a pre-seeded demo portfolio. When
ALLOW_PAPER_SIMULATED_ORDERS=True routes real JARVIS orders to that account,
reconciliation must be able to separate JARVIS-originated fills from the demo
activity. IBGatewayManager.place_paper_order now tags every order with an IB
``orderRef`` — an explicit value when passed, otherwise an auto-generated
``JARVIS-<uuid>`` — and threads it through to the placed Order object.

These tests assert:
    1. place_paper_order accepts an explicit order_ref and stamps it on the
       placed Order.
    2. When order_ref is omitted, a ``JARVIS-<hex>`` ref is auto-generated and
       stamped on the placed Order (no order goes out untagged).
    3. _build_order_object sets Order.orderRef only when order_ref is provided.

This path is inert until ALLOW_PAPER_SIMULATED_ORDERS=True (the real-IB
place_paper_order is only exercised when the flag is enabled); the tagging is
additive and changes no default behavior.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_order_ref_tagging.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

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
async def test_explicit_order_ref_is_stamped_on_placed_order():
    """An explicit order_ref must appear verbatim as Order.orderRef."""
    pytest.importorskip("ib_async")
    mgr, fake_ib = _build_manager_with_mocked_ib()

    order_id = await mgr.place_paper_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        order_type="MKT",
        order_ref="JARVIS-entry-abc123",
    )

    assert order_id == 7777
    assert fake_ib.placeOrder.called, "_ib.placeOrder was never called"
    placed_order = fake_ib.placeOrder.call_args.args[1]
    assert getattr(placed_order, "orderRef", "") == "JARVIS-entry-abc123"


@pytest.mark.asyncio
async def test_missing_order_ref_auto_generates_jarvis_tag():
    """With no order_ref, a JARVIS-<hex> ref is generated and stamped."""
    pytest.importorskip("ib_async")
    mgr, fake_ib = _build_manager_with_mocked_ib()

    order_id = await mgr.place_paper_order(
        symbol="MES",
        action="SELL",
        quantity=1,
        order_type="MKT",
    )

    assert order_id == 7777
    placed_order = fake_ib.placeOrder.call_args.args[1]
    ref = getattr(placed_order, "orderRef", "")
    assert ref.startswith("JARVIS-"), f"expected auto JARVIS- ref, got {ref!r}"
    # JARVIS- prefix (7) + 12 hex chars from uuid4().hex[:12]
    assert len(ref) == len("JARVIS-") + 12, f"unexpected ref length: {ref!r}"


@pytest.mark.asyncio
async def test_auto_generated_refs_are_unique_per_order():
    """Each untagged order gets a distinct auto-generated ref."""
    pytest.importorskip("ib_async")
    mgr, fake_ib = _build_manager_with_mocked_ib()

    await mgr.place_paper_order(symbol="MES", action="BUY", quantity=1, order_type="MKT")
    first = getattr(fake_ib.placeOrder.call_args.args[1], "orderRef", "")

    await mgr.place_paper_order(symbol="MES", action="BUY", quantity=1, order_type="MKT")
    second = getattr(fake_ib.placeOrder.call_args.args[1], "orderRef", "")

    assert first and second and first != second, (
        f"auto-generated refs should be unique, got {first!r} and {second!r}"
    )


def test_build_order_object_sets_orderref_when_provided():
    """_build_order_object stamps orderRef only when order_ref is passed."""
    pytest.importorskip("ib_async")
    mgr, _ = _build_manager_with_mocked_ib()

    tagged = mgr._build_order_object(
        "MKT", "BUY", 1, None, None, order_ref="JARVIS-xyz"
    )
    assert getattr(tagged, "orderRef", "") == "JARVIS-xyz"

    # Omitted -> orderRef left at the ib_async default (empty string), untouched.
    untagged = mgr._build_order_object("MKT", "BUY", 1, None, None)
    assert getattr(untagged, "orderRef", "") == ""
