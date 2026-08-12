"""
IB Gateway paper-mode END-TO-END tests — manual opt-in only.

These tests require a running IB Gateway (or TWS) session configured for
paper trading on port 4002. They are skipped in all CI/default runs and must
be invoked explicitly with ``-m manual``.

Covered scenarios
-----------------
1. ``test_ibkr_gateway_reachable`` — TCP handshake to port 4002; logs server
   version. Fails with an informative message if Gateway is not running.

2. ``test_mes_front_month_subscribe_ticks`` — subscribes to front-month MES,
   collects at least one price field within 30 s, asserts price is in a
   sensible range for the Micro E-mini S&P 500 (4 000 – 10 000). Passes
   with a warning when market is closed and data is "pending" (bid/ask/last
   all zero) — that is a Gateway/subscription state, not a code bug.

3. ``test_paper_order_dry_run`` — submits a single-contract MES limit order
   far from market (price = 1.00) so it will NOT fill, records the IB order
   ID, then immediately cancels. Verifies: order ID is a positive integer,
   cancel returns True, and the order disappears from open orders within 5 s.

Run command
-----------
    cd engine
    .venv/Scripts/python -m pytest tests/test_ibkr_e2e_paper.py -m manual -v

DO NOT run without ``-m manual`` — the tests will not appear in the default
collection (``--strict-markers`` would reject an unknown marker, but ``manual``
is now registered in pyproject.toml).

Safety constraints
------------------
* Port 4002 (paper) is hardcoded everywhere. Port 4001 (live) is rejected by
  ``IBGatewayConfig.__post_init__`` and will never be reached.
* The limit price of 1.00 for the dry-run order is intentionally far below
  any realistic MES price; the order CANNOT fill during the test window.
* All tests disconnect and cancel lingering state in ``finally`` blocks.
"""

from __future__ import annotations

import asyncio
import logging
import os

import pytest

from execution.ib_gateway import (
    IB_INSYNC_AVAILABLE,
    IBGatewayConfig,
    IBGatewayManager,
    _nearest_quarterly_expiry,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAPER_PORT = 4002
_CLIENT_ID_BASE = 91  # Use high client IDs to avoid collisions with the engine (IDs 1–44)


def _require_live_ib_order_tests_allowed() -> None:
    """Second, independent gate on top of the `manual` pytest marker.

    The marker/addopts layer is a single config line (pyproject.toml's
    `-m "not manual and not integration_ib"`) away from firing for real --
    see tests/test_ib_gateway_connector_safety_wiring.py, which had exactly
    this gap fixed 2026-08-11 after the addopts-only version of this pattern
    let 3 live orders through. This file's own docstring even documents the
    single-flag `-m manual` invocation as the intended run command, so it
    carries the same risk. Unset (or anything other than "1") -> skip,
    unconditionally, before any connection is attempted.
    """
    if os.environ.get("ALLOW_LIVE_IB_ORDER_TESTS", "0") != "1":
        pytest.skip(
            "ALLOW_LIVE_IB_ORDER_TESTS != 1 -- this test talks to a REAL IB "
            "Gateway (and test_paper_order_dry_run places a real order); set "
            "the env var explicitly to opt in (second gate, independent of "
            "the manual marker)"
        )


async def _connect_or_skip(client_id: int) -> IBGatewayManager:
    """
    Attempt to connect to IB Gateway paper port 4002.

    Skips the test cleanly (``pytest.skip``) when:
    - ``ib_async`` / ``ib_insync`` library is not installed
    - Gateway is not running or refuses the connection
    - Handshake times out

    Returns a connected ``IBGatewayManager`` on success.
    """
    if not IB_INSYNC_AVAILABLE:
        pytest.skip(
            "ib_async / ib_insync not installed — "
            "run: pip install ib_async>=0.9.86 inside engine/.venv"
        )

    cfg = IBGatewayConfig(
        host="127.0.0.1",
        port=_PAPER_PORT,
        client_id=client_id,
        timeout=15.0,
        account="",  # auto-detect paper account (DUP662235 or similar)
    )
    gw = IBGatewayManager(cfg)
    connected = await gw.connect()
    if not connected or not gw.is_connected():
        pytest.skip(
            "IB Gateway not started — run TWS / IB Gateway paper on port 4002.\n"
            "In IB Gateway: Configure → API → Enable ActiveX and Socket Clients → Port 4002"
        )
    return gw


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
@pytest.mark.asyncio
async def test_ibkr_gateway_reachable() -> None:
    """
    Validates that IB Gateway paper (port 4002) is reachable and that the
    ib_async handshake succeeds. Logs the IB server version for diagnostics.

    Pass criteria:
    - ``connect()`` returns True
    - ``is_connected()`` returns True
    - IB server version is available and > 0

    Fail message if Gateway is not running:
        "IB Gateway not started — run TWS / IB Gateway paper on port 4002."
    """
    _require_live_ib_order_tests_allowed()
    gw = await _connect_or_skip(client_id=_CLIENT_ID_BASE)
    try:
        assert gw.is_connected(), "Gateway reported is_connected()=False after successful connect()"

        # ib_async exposes client.serverVersion() on the internal IB() instance
        ib = gw._ib  # type: ignore[attr-defined]  # internal access for test diagnostics
        server_version: int = 0
        if ib is not None:
            try:
                server_version = ib.client.serverVersion()
            except Exception as exc:
                logger.warning("Could not read server version: %s", exc)

        logger.info(
            "IB Gateway reachable — paper port=%d server_version=%d",
            _PAPER_PORT,
            server_version,
        )
        # A healthy Gateway always returns a positive server version
        assert server_version > 0, (
            f"IB server version={server_version} — expected a positive integer. "
            "This may indicate a partial connection."
        )
    finally:
        await gw.disconnect()


@pytest.mark.manual
@pytest.mark.asyncio
async def test_mes_front_month_subscribe_ticks() -> None:
    """
    Subscribes to the front-month MES (Micro E-mini S&P 500) contract and
    collects at least one price field within a 30 s timeout.

    Acceptance criteria:
    - Contract qualifies successfully (IB returns a conId)
    - At least one price field (last / bid / ask / close) is received, OR
      all fields are zero but the contract qualified (market is closed —
      this is not a code bug)
    - When a price IS received, it falls within 4 000 – 10 000 (reasonable
      range for MES regardless of market conditions through 2030+)

    Teardown: ``cancelMktData`` is always called, even on failure.
    """
    _require_live_ib_order_tests_allowed()
    gw = await _connect_or_skip(client_id=_CLIENT_ID_BASE + 1)
    ib = gw._ib  # type: ignore[attr-defined]

    contract = None
    try:
        # Resolve and qualify front-month MES contract
        contract = gw._resolve_contract("MES")  # type: ignore[attr-defined]
        assert contract is not None, "IBGatewayManager._resolve_contract('MES') returned None"

        qualified_list = await asyncio.wait_for(
            ib.qualifyContractsAsync(contract),
            timeout=10.0,
        )
        assert qualified_list, (
            "IB could not qualify MES front-month contract. "
            "Check MES market data subscription in IB Account Management."
        )
        qualified = qualified_list[0]
        logger.info("MES qualified: conId=%s", qualified.conId)

        # Request a snapshot tick — ib_async populates the Ticker object
        ticker = ib.reqMktData(qualified, "", snapshot=True, regulatorySnapshot=False)

        # Poll for up to 30 s, checking every 0.5 s for any price field to populate
        price_received = False
        price_value: float = 0.0
        for _ in range(60):  # 60 × 0.5 s = 30 s
            await asyncio.sleep(0.5)
            last = getattr(ticker, "last", 0) or 0
            bid = getattr(ticker, "bid", 0) or 0
            ask = getattr(ticker, "ask", 0) or 0
            close = getattr(ticker, "close", 0) or 0
            # ib_async uses float("nan") for unset fields; treat NaN/0 as "no data"
            import math

            def _valid(v: float) -> bool:
                return v is not None and not math.isnan(v) and v > 0

            if _valid(last) or _valid(bid) or _valid(ask) or _valid(close):
                price_value = next(v for v in (last, bid, ask, close) if _valid(v))
                price_received = True
                break

        if price_received:
            logger.info("MES tick received: price=%.2f", price_value)
            assert 4_000 <= price_value <= 10_000, (
                f"MES price {price_value:.2f} is outside the expected range 4000–10000. "
                "Check that the correct front-month contract was selected."
            )
        else:
            # Market closed or subscription not active — contract qualified, no data yet
            logger.warning(
                "MES contract qualified (conId=%s) but no price data received within 30 s. "
                "This is expected outside CME Globex trading hours or if market data "
                "subscription for MES is not active on this paper account.",
                qualified.conId,
            )
            # Not an assertion failure — the contract round-trip itself succeeded.

    finally:
        # Always cancel the market data subscription to avoid Gateway resource leaks
        if contract is not None and ib is not None and ib.isConnected():
            try:
                ib.cancelMktData(contract)
            except Exception as exc:
                logger.warning("cancelMktData cleanup error: %s", exc)
        await gw.disconnect()


@pytest.mark.manual
@pytest.mark.asyncio
async def test_paper_order_dry_run() -> None:
    """
    Submits a 1-contract MES limit order at price = 1.00 (far below market)
    so it will NOT fill during the test. Verifies the full order lifecycle:

    1. ``place_paper_order`` returns a positive integer order ID (IB orderId)
    2. The order appears in ``get_open_orders()`` immediately after placement
    3. ``cancel_order`` returns True
    4. Within 5 s the order is no longer in ``get_open_orders()``

    Teardown: any lingering order is cancelled in the finally block.

    NOTE: This tests the REAL IB paper order path (``IBGatewayManager``), NOT
    the simulated paper path in ``IBGatewayConnector``. The former actually
    sends the order to IB's paper account engine.
    """
    _require_live_ib_order_tests_allowed()
    gw = await _connect_or_skip(client_id=_CLIENT_ID_BASE + 2)
    order_id: int | None = None

    try:
        # Place a limit order deliberately far from market so it won't fill.
        # MES is currently ~5 000–6 000; price=1.00 is safely unreachable.
        order_id = await asyncio.wait_for(
            gw.place_paper_order(
                symbol="MES",
                action="BUY",
                quantity=1,
                order_type="LMT",
                limit_price=1.00,
            ),
            timeout=15.0,
        )

        assert order_id is not None, (
            "place_paper_order returned None — IB Gateway may have rejected the order. "
            "Check that the paper account is funded and the MES contract is tradeable."
        )
        assert isinstance(order_id, int) and order_id > 0, (
            f"Expected a positive integer order ID, got: {order_id!r}"
        )
        logger.info("MES dry-run order placed: order_id=%d", order_id)

        # Give IB a moment to register the order in the paper book
        await asyncio.sleep(1.0)

        # Verify the order appears in open orders
        open_orders = await gw.get_open_orders()
        order_ids_open = [o.get("order_id") for o in open_orders]
        assert order_id in order_ids_open, (
            f"order_id={order_id} not found in open orders immediately after placement. "
            f"Open orders: {order_ids_open}"
        )
        logger.info("order_id=%d confirmed in open orders", order_id)

        # Cancel the order
        cancelled = await asyncio.wait_for(
            gw.cancel_order(order_id),
            timeout=10.0,
        )
        assert cancelled is True, (
            f"cancel_order(order_id={order_id}) returned False — cancellation may have failed."
        )
        logger.info("Cancel sent for order_id=%d", order_id)

        # Poll for up to 5 s for the order to leave open orders
        order_gone = False
        for _ in range(10):  # 10 × 0.5 s = 5 s
            await asyncio.sleep(0.5)
            open_orders = await gw.get_open_orders()
            if order_id not in [o.get("order_id") for o in open_orders]:
                order_gone = True
                break

        assert order_gone, (
            f"order_id={order_id} still present in open orders 5 s after cancel. "
            "IB Gateway may be slow to acknowledge the cancellation."
        )
        logger.info("order_id=%d confirmed removed from open orders — dry-run PASSED", order_id)

        # Reset so finally block doesn't double-cancel
        order_id = None

    finally:
        # Belt-and-suspenders: cancel the order if something went wrong above
        if order_id is not None:
            try:
                await gw.cancel_order(order_id)
                logger.info("Cleanup: cancelled lingering order_id=%d", order_id)
            except Exception as exc:
                logger.warning("Cleanup cancel failed for order_id=%d: %s", order_id, exc)
        await gw.disconnect()
