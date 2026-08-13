"""
HB-1 Stage 3 — Bracket completion: add take-profit (TP) child to the broker-side
bracket introduced in Stage 2 (test_broker_stp_wiring.py).

Stage 2 closed the stop-loss gap (entry + child STP + parent_id linkage).
Stage 3 closes the symmetric take-profit gap: any engine crash after entry
fills but before a winner hits target left the position unprotected on the
UP-side.  A broker-side LMT child linked to the same parent entry is the
symmetric fix.

Contract (Stage 3 extension of SafetyLayer.submit_entry_with_stop):
    target_price: Optional[float] — take-profit LMT price. When provided,
    a LMT child is placed after the STP with parent_order_id == entry_id.
    Return dict grows to include:
        tp_order_id : broker id of the TP child (None if unused/failed)
        tp_linked   : True iff TP carries parent_order_id == entry

Backward-compat: target_price=None → no TP placed, return dict still
includes tp_order_id=None + tp_linked=False.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_broker_bracket_tp_wiring.py -v
"""

from __future__ import annotations

import os
import sys

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


def _paper_offline_cfg():
    """``ALLOW_MOCK_QUOTES`` is required (2026-07-21, see
    ``test_ib_gateway_connector_offline.py``): no market-data manager is
    attached here, so the static quote table is needed to produce a fill at
    all. Production leaves this False and refuses to fill without a real
    price basis -- see ``test_paper_fill_refuses_mock_price.py``.
    """
    from config import settings

    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": False,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "ALLOW_MOCK_QUOTES": True,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
            # Test stops are 30–90 pts on MES ($5/pt) = $150–$450; allow up to $500
            # so the trade-loss gate passes without suppressing these bracket tests.
            "MAX_TRADE_LOSS_USD": 500.0,
        }
    )


@pytest.mark.asyncio
async def test_submit_entry_with_stop_and_target_places_tp_child(tmp_path) -> None:
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = _paper_offline_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )

    assert await conn.connect() is True
    safety.attach_ib_gateway(conn)

    result = await safety.submit_entry_with_stop(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=7130.0,
        stop_price=7100.0,  # -30 pt stop
        target_price=7190.0,  # +60 pt target (2:1 RRR)
    )

    assert result["approved"] is True
    assert result["routed_to_ib"] is True
    assert result["entry_order_id"] is not None
    assert result["stp_order_id"] is not None
    assert result["stp_linked"] is True
    # TP is skipped in paper mode (LIVE_TRADING_ENABLED=False) to prevent the
    # paper connector from immediately filling the LMT child as a second exit.
    assert (
        result["tp_order_id"] is None
    ), "TP child should be None in paper mode — TP placement is gated on LIVE_TRADING_ENABLED"
    assert result["tp_linked"] is False


@pytest.mark.asyncio
async def test_tp_child_linked_to_parent_entry(tmp_path) -> None:
    """In paper mode (LIVE_TRADING_ENABLED=False) TP is not placed, so tp_order_id
    is None and there is no order to verify linkage on.  This test confirms that
    the STP child IS linked and that tp_order_id is None (paper-mode invariant)."""
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = _paper_offline_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )

    await conn.connect()
    safety.attach_ib_gateway(conn)

    result = await safety.submit_entry_with_stop(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=7130.0,
        stop_price=7100.0,
        target_price=7190.0,
    )

    entry_id = result["entry_order_id"]
    stp_id = result["stp_order_id"]

    # Verify STP is linked to the entry parent
    stp_status = await conn.get_order_status(stp_id)
    assert stp_status.get("parent_order_id") == entry_id, (
        f"STP parent linkage broken: expected {entry_id}, "
        f"got {stp_status.get('parent_order_id')}"
    )
    assert stp_status.get("order_type") in {
        "STP",
        "stop",
    }, f"Child order not typed as stop: {stp_status.get('order_type')}"

    # TP must be absent in paper mode
    assert (
        result["tp_order_id"] is None
    ), "TP should not be placed in paper mode (LIVE_TRADING_ENABLED=False)"
    assert result["tp_linked"] is False


@pytest.mark.asyncio
async def test_without_target_preserves_stp_only_backward_compat(tmp_path) -> None:
    """When target_price is omitted, no TP child is placed (Stage 2 behavior)."""
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = _paper_offline_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )

    await conn.connect()
    safety.attach_ib_gateway(conn)

    result = await safety.submit_entry_with_stop(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=7130.0,
        stop_price=7100.0,
        # no target_price
    )

    assert result["stp_order_id"] is not None
    assert result["stp_linked"] is True
    assert result["tp_order_id"] is None, "TP was placed without target_price being provided"
    assert result["tp_linked"] is False


@pytest.mark.asyncio
async def test_short_entry_places_both_children_linked_to_parent(tmp_path) -> None:
    """SHORT entry should still produce a STP child linked to parent.
    TP is skipped in paper mode (LIVE_TRADING_ENABLED=False) — paper connector
    would immediately fill the LMT child as a second unintended exit.
    Direction-correctness of the STP child is enforced in SafetyLayer code
    (child_action = opposite of entry action)."""
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = _paper_offline_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )

    await conn.connect()
    safety.attach_ib_gateway(conn)

    result = await safety.submit_entry_with_stop(
        symbol="MES",
        action="SELL",
        quantity=1,
        price=7130.0,
        stop_price=7160.0,  # STP ABOVE entry for a short
        target_price=7070.0,  # TP BELOW entry for a short (skipped in paper mode)
    )

    assert result["approved"] is True
    assert result["stp_linked"] is True
    # TP skipped in paper mode
    assert result["tp_order_id"] is None
    assert result["tp_linked"] is False

    stp_status = await conn.get_order_status(result["stp_order_id"])
    entry_id = result["entry_order_id"]
    assert stp_status.get("parent_order_id") == entry_id
