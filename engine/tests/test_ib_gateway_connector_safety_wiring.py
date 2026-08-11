"""IBGatewayManager ↔ SafetyLayer / IBOrderManager contract (paper path).

These tests place REAL orders (BUY 1 MES / MCL / MNQ) against whatever IB
Gateway is reachable on port 4002 -- that is their point, they verify the
actual live wiring contract, not a mock. The 2026-08-11 incident (see
pyproject.toml's addopts comment) happened because the *only* thing gating
that was the `integration_ib` pytest marker via addopts -- a single config
line that is one edit, one CI override, or one non-addopts-respecting test
runner away from firing again with no other safeguard.

`ALLOW_LIVE_IB_ORDER_TESTS=1` is a second, independent gate checked inside
the test body itself, so it holds even if the marker/addopts layer is ever
bypassed or misconfigured. Unset (or anything other than "1") -> skip,
unconditionally, before any connection is attempted.
"""

from __future__ import annotations

import os

import pytest

from config import settings
from execution.ib_gateway import IBGatewayConfig, IBGatewayManager
from execution.ib_order_manager import IBOrderManager
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer


def _require_live_ib_order_tests_allowed() -> None:
    if os.environ.get("ALLOW_LIVE_IB_ORDER_TESTS", "0") != "1":
        pytest.skip(
            "ALLOW_LIVE_IB_ORDER_TESTS != 1 -- this test places a REAL order "
            "against IB Gateway; set the env var explicitly to opt in "
            "(second gate, independent of the integration_ib marker)"
        )


def _paper_order_settings():
    """Relax Tier-3 gates for IB paper routing contract tests only."""
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": True,
            "REQUIRE_HUMAN_APPROVAL": False,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 1.0,
        }
    )


@pytest.mark.integration_ib
@pytest.mark.asyncio
async def test_place_paper_order_after_safety_no_double_reject(tmp_path) -> None:
    """IBGatewayManager routes orders through SafetyLayer.submit_paper_order()."""
    _require_live_ib_order_tests_allowed()
    cfg = _paper_order_settings()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    ib_config = IBGatewayConfig(host="127.0.0.1", port=4002, client_id=1)
    gateway = IBGatewayManager(ib_config)
    # Note: connect() will fail if IB Gateway is not running, so wrap in try/except
    try:
        conn_ok = await gateway.connect()
        if not conn_ok:
            pytest.skip("IB Gateway not running on port 4002 — skipping live connection test")
    except Exception:
        pytest.skip("IB Gateway not running on port 4002 — skipping live connection test")

    assert gateway.is_connected() is True
    safety.attach_ib_gateway(gateway)

    out = await safety.submit_paper_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=5300.0,
        order_type="MKT",
        limit_price=None,
    )
    assert out["approved"] is True
    # routed_to_ib only if IB is connected and accepts the order
    if gateway.is_connected():
        assert out["routed_to_ib"] is True
        assert out.get("order_id")


@pytest.mark.integration_ib
@pytest.mark.asyncio
async def test_get_positions_list_shape_for_order_manager(tmp_path) -> None:
    _require_live_ib_order_tests_allowed()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(settings, pnl_monitor=None)
    ib_config = IBGatewayConfig(host="127.0.0.1", port=4002, client_id=1)
    gateway = IBGatewayManager(ib_config)
    try:
        conn_ok = await gateway.connect()
        if not conn_ok:
            pytest.skip("IB Gateway not running on port 4002 — skipping test")
    except Exception:
        pytest.skip("IB Gateway not running on port 4002 — skipping test")

    # Place an order to create a position
    await gateway.place_paper_order("MCL", "BUY", 1)

    positions = await gateway.get_positions()
    assert isinstance(positions, list)
    if positions:  # Only check if positions exist
        row = positions[0]
        assert row.get("symbol")
        assert "position" in row


@pytest.mark.integration_ib
@pytest.mark.asyncio
async def test_ib_order_manager_uses_gateway(tmp_path) -> None:
    _require_live_ib_order_tests_allowed()
    cfg = _paper_order_settings()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    ib_config = IBGatewayConfig(host="127.0.0.1", port=4002, client_id=1)
    gateway = IBGatewayManager(ib_config)
    try:
        conn_ok = await gateway.connect()
        if not conn_ok:
            pytest.skip("IB Gateway not running on port 4002 — skipping test")
    except Exception:
        pytest.skip("IB Gateway not running on port 4002 — skipping test")
    safety.attach_ib_gateway(gateway)
    om = IBOrderManager(safety, ib_gateway=gateway, portfolio_tracker=tracker)
    res = await om.submit_order(
        symbol="MNQ",
        action="BUY",
        quantity=1,
        price=17500.0,
        order_type="MKT",
        limit_price=None,
    )
    assert res["approved"] is True
    if gateway.is_connected():
        assert res["routed_to_ib"] is True
    st = om.get_status()
    assert st["ib_gateway_connected"] is True
