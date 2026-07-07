"""
Q2-P2.7 Stage 1 — Red regression tests for broker-side STP wiring + flatten-all.

These tests document the Stage 2 contract that closes HB-1 from the 2026-04-22
deployment-verification review:

    - trader agent computes stop_price but no code path submits a STP order
      to IBKR, so any engine crash mid-trade = unprotected position.
    - grep 'STP' across engine/execution, engine/agents, engine/trader,
      engine/pipeline returns zero matches today.
    - SafetyLayer.submit_paper_order supports MKT/LMT only; the STP path in
      IBGatewayManager.place_paper_order (line 510-518) is dead code.
    - No /safety/flatten-all endpoint; kill switch blocks new orders but does
      not close open positions.

Stage 1 (this file) ships RED tests and commits them so the contract for
Stage 2 is frozen in the repo, not just in a plan doc. Stage 2 will:

    1. Add SafetyLayer.submit_entry_with_stop(..., stop_price) that places
       entry MKT + child STP in one atomic call, linked by parent_order_id.
    2. Track parent_order_id in the IBGatewayConnector _open_orders dict.
    3. Add POST /safety/flatten-all to safety_router that market-closes every
       open position (used for emergency recovery when kill switch isn't
       enough).

All three tests below SHOULD FAIL until Stage 2 lands.
Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_broker_stp_wiring.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Test-environment bootstrap (mirrors test_analytics_router.py pattern)
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


def _paper_offline_cfg():
    """Relaxed config for offline paper simulation (mirrors other offline tests)."""
    from config import settings

    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": False,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
            "MAX_TRADE_LOSS_USD": 500.0,
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — Entry fill triggers STP child order
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entry_fill_triggers_stp_child_order(tmp_path) -> None:
    """
    After a successful MKT entry, a child STP order must also reach the broker.

    Contract (Stage 2):
        SafetyLayer.submit_entry_with_stop(
            symbol, action, quantity, price, stop_price
        ) -> dict with keys:
            approved       (bool)
            entry_order_id (int|str|None)
            stp_order_id   (int|str|None)    # NEW — STP child order id
            stp_linked     (bool)            # NEW — True iff STP has parent ref
            routed_to_ib   (bool)

    Stage 1 expectation: AttributeError — no such method on SafetyLayer.
    Stage 2 expectation: both IDs non-None, stp_linked=True, routed_to_ib=True.
    """
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = _paper_offline_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)

    assert await conn.connect() is True
    safety.attach_ib_gateway(conn)

    # Stage 2 contract: one call places entry + child STP atomically.
    result = await safety.submit_entry_with_stop(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=7130.0,
        stop_price=7100.0,  # 30-point stop below entry
    )

    assert result["approved"] is True, f"Entry rejected: {result.get('reason')}"
    assert result["routed_to_ib"] is True, "Entry order did not reach IB"
    assert result.get("entry_order_id") is not None, "Entry order_id missing"
    assert (
        result.get("stp_order_id") is not None
    ), "STP child order was not submitted — HB-1 regression"
    assert (
        result.get("stp_linked") is True
    ), "STP not linked to parent entry — stop would be orphaned on entry cancel"
    assert (
        result["entry_order_id"] != result["stp_order_id"]
    ), "Entry and STP collapsed to same ID — Stage 2 must place them as 2 orders"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — STP child order linked to parent entry
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stp_child_order_linked_to_parent_entry(tmp_path) -> None:
    """
    After submit_entry_with_stop, querying the STP order must report the
    parent_order_id so reconciliation and cancel-on-fill work correctly.

    Contract (Stage 2):
        IBGatewayConnector._open_orders[stp_order_id] must include the key
        'parent_order_id' set to the entry order id. get_order_status(stp_id)
        must surface it in the returned dict.

    Stage 1 expectation: AttributeError on submit_entry_with_stop, OR
                         result dict missing 'parent_order_id' field.
    Stage 2 expectation: parent_order_id present and matches entry_order_id.
    """
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = _paper_offline_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)

    await conn.connect()
    safety.attach_ib_gateway(conn)

    result = await safety.submit_entry_with_stop(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=7130.0,
        stop_price=7100.0,
    )

    entry_id = result["entry_order_id"]
    stp_id = result["stp_order_id"]

    stp_status = await conn.get_order_status(stp_id)

    assert stp_status.get("status") in {
        "filled",
        "pending",
        "working",
    }, f"STP order not in live state: {stp_status}"
    assert stp_status.get("order_type") in {
        "STP",
        "stop",
    }, f"Child order not typed as stop: {stp_status.get('order_type')}"
    assert stp_status.get("parent_order_id") == entry_id, (
        f"STP parent linkage broken: expected {entry_id}, "
        f"got {stp_status.get('parent_order_id')}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — POST /safety/flatten-all closes every open position
# ──────────────────────────────────────────────────────────────────────────────


def test_flatten_all_endpoint_closes_open_positions() -> None:
    """
    POST /safety/flatten-all must exist and market-close every open position.

    Contract (Stage 2):
        POST /safety/flatten-all
        Response 200 with body:
            {
                "flattened": [list of symbols that were open],
                "order_ids": [list of market-close order ids],
                "errors":    [list of {symbol, error} for failed closes]
            }

    Stage 1 expectation: FastAPI 404 — endpoint does not exist.
    Stage 2 expectation: 200 with body shape above; at least one symbol
                         flattened when the mock safety layer reports an
                         open MES position.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Build a minimal app that mounts safety_router. inject_dependencies needs
    # a safety_layer + loss_tracker stub with just the surface Stage 2 uses.
    from routers.safety_router import inject_dependencies
    from routers.safety_router import router as safety_router

    mock_safety = MagicMock()
    # Stage 2 will add this async method — today it doesn't exist.
    mock_safety.flatten_all_positions = AsyncMock(
        return_value={
            "flattened": ["MES"],
            "order_ids": [98765],
            "errors": [],
        }
    )
    mock_loss_tracker = MagicMock()

    inject_dependencies(mock_safety, mock_loss_tracker)

    app = FastAPI()
    app.include_router(safety_router)
    client = TestClient(app, headers={"X-API-Key": os.environ["API_KEY"]})

    resp = client.post("/safety/flatten-all")

    assert resp.status_code == 200, (
        f"/safety/flatten-all returned {resp.status_code} — endpoint missing "
        f"(Stage 2 must add it to safety_router.py). Body: {resp.text[:200]}"
    )
    body = resp.json()
    assert "flattened" in body, "Response missing 'flattened' list"
    assert "order_ids" in body, "Response missing 'order_ids' list"
    assert isinstance(body["flattened"], list)
    assert "MES" in body["flattened"], "Mock safety layer reported MES open but it wasn't flattened"
    mock_safety.flatten_all_positions.assert_awaited_once()
