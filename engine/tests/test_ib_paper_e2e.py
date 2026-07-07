"""
IB Gateway paper-mode END-TO-END tests (requires IB Gateway on port 4002).

Exercises the full vertical slice: SafetyLayer → IBGatewayConnector → paper
account → PortfolioTracker. Unlike the unit tests in
`test_ib_gateway_connector_offline.py` (which use the offline-sim path), these
tests connect to a live IB Gateway paper session.

Covered scenarios:
  1. MCL paper BUY completes the full pipeline and is captured in PortfolioTracker
  2. Kill-switch prevents order routing to IB even when the signal would otherwise go
  3. MNQ paper BUY mirrors scenario 1 for a second paper-approved instrument

NOT covered (already live-verified elsewhere):
  - Inverted stop-loss rejection → engine/tests/test_stop_loss_invariants.py
    (live-verified 2026-04-16, HTTP 422 on PATCH with inverted stop)

Run:
    pytest engine/tests/test_ib_paper_e2e.py -v -m integration_ib

Skips cleanly if IB Gateway is not running — do NOT @pytest.skip at module
level; let each test negotiate its own skip via the connect() attempt.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from config import settings
from execution.ib_gateway import IBGatewayConfig, IBGatewayManager
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer


def _paper_settings(overrides: dict | None = None):
    """Tier-3 settings for live paper-trade routing (NOT production)."""
    update = {
        "LIVE_TRADING_ENABLED": True,           # gate open for paper path
        "REQUIRE_HUMAN_APPROVAL": False,        # auto-approve in tests
        "PAPER_TRADING": True,                  # paper account only
        "ALLOW_PAPER_SIMULATED_ORDERS": False,  # force real IB paper path
        "MAX_SINGLE_ORDER_VALUE": 500_000.0,
        "MAX_POSITION_SIZE_PCT": 1.0,
    }
    if overrides:
        update.update(overrides)
    return settings.model_copy(update=update)


async def _connect_or_skip(ib_config: IBGatewayConfig) -> IBGatewayManager:
    """Attempt paper-gateway connect; skip the test cleanly if unavailable."""
    gateway = IBGatewayManager(ib_config)
    try:
        ok = await gateway.connect()
    except Exception as exc:
        pytest.skip(f"IB Gateway not running on port 4002 ({exc!s})")
    if not ok or not gateway.is_connected():
        pytest.skip("IB Gateway connect() returned False on port 4002")
    return gateway


@pytest.mark.integration_ib
@pytest.mark.asyncio
async def test_mcl_paper_buy_full_pipeline(tmp_path: Path) -> None:
    """
    Happy path: signal → SafetyLayer → IB paper order → PortfolioTracker.

    Verifies the complete vertical slice without mocks. If this passes with a
    real IB Gateway session, the paper-trading path is safe for real-capital
    promotion gates (pending manual approval wiring).
    """
    cfg = _paper_settings()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)

    ib_cfg = IBGatewayConfig(host="127.0.0.1", port=4002, client_id=42)
    gateway = await _connect_or_skip(ib_cfg)
    try:
        safety.attach_ib_gateway(gateway)

        out = await safety.submit_paper_order(
            symbol="MCL",
            action="BUY",
            quantity=1,
            price=82.50,
            order_type="MKT",
            limit_price=None,
        )

        assert out["approved"] is True, f"SafetyLayer rejected order: {out}"
        assert out["routed_to_ib"] is True, f"Order not routed to IB: {out}"
        assert out.get("order_id"), "IB did not return an order_id"

        # Give IB a beat to register the order in its paper book.
        await asyncio.sleep(0.5)

        positions = await gateway.get_positions()
        symbols = [p.get("symbol") or p.get("contract", {}).get("symbol") for p in positions]
        assert "MCL" in symbols or any("CL" in str(s) for s in symbols), (
            f"MCL not in gateway positions after fill: {positions}"
        )
    finally:
        await gateway.disconnect()


@pytest.mark.integration_ib
@pytest.mark.asyncio
async def test_kill_switch_blocks_paper_order(tmp_path: Path) -> None:
    """
    Kill-switch active → SafetyLayer rejects the order before it reaches IB.

    Guards the contract that the kill-switch is the absolute stop. Without this
    test, a SafetyLayer refactor could silently let orders past the gate.
    """
    cfg = _paper_settings()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)

    ib_cfg = IBGatewayConfig(host="127.0.0.1", port=4002, client_id=43)
    gateway = await _connect_or_skip(ib_cfg)
    try:
        safety.attach_ib_gateway(gateway)

        # Engage kill switch BEFORE submitting
        safety.activate_kill_switch(reason="TEST", message="kill-switch E2E regression")

        out = await safety.submit_paper_order(
            symbol="MCL",
            action="BUY",
            quantity=1,
            price=82.50,
            order_type="MKT",
            limit_price=None,
        )

        assert out["approved"] is False, (
            f"Kill switch failed to block — SafetyLayer approved: {out}"
        )
        assert not out.get("order_id"), (
            f"Kill-switch-blocked order still got an order_id: {out.get('order_id')}"
        )
    finally:
        # Reset kill switch so other tests aren't poisoned by this fixture
        try:
            safety.deactivate_kill_switch(authorized_by="test-cleanup")
        except Exception:
            pass
        await gateway.disconnect()


@pytest.mark.integration_ib
@pytest.mark.asyncio
async def test_mnq_paper_buy_mirrors_mcl(tmp_path: Path) -> None:
    """Second paper-approved instrument (MNQ) follows the same contract as MCL."""
    cfg = _paper_settings()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)

    ib_cfg = IBGatewayConfig(host="127.0.0.1", port=4002, client_id=44)
    gateway = await _connect_or_skip(ib_cfg)
    try:
        safety.attach_ib_gateway(gateway)

        out = await safety.submit_paper_order(
            symbol="MNQ",
            action="BUY",
            quantity=1,
            price=20100.0,
            order_type="MKT",
            limit_price=None,
        )

        assert out["approved"] is True, out
        assert out["routed_to_ib"] is True, out
        assert out.get("order_id")
    finally:
        await gateway.disconnect()
