"""
JARVIS TRADER — IBGatewayConnector paper-cash futures-multiplier gap
=======================================================================
Post-merge follow-up to #641 (fix(execution): reflect realized P&L in paper
account equity/buying-power). #641 fixed ``equity``/``buying_power`` in
``get_account_balance()`` to reflect realized P&L via ``_realized_pnl_total()``
-> ``PortfolioTracker.get_performance()['total_pnl']``, which correctly
applies each instrument's futures contract multiplier
(``portfolio.tracker.INSTRUMENT_MULTIPLIERS``).

``cash`` in the same account-summary object was computed separately in two
places -- ``_fill_paper_order`` and ``_submit_paper_order`` -- and neither
applied the multiplier, so a filled MES/MGC/MCL/MNQ order moved ``cash`` by
the bare ``price * qty`` notional while ``equity`` moved by the correctly
multiplied realized P&L. On a real futures fill those two views of the same
account diverge by the multiplier factor (5x for MES) instead of staying in
lockstep.

These tests exercise the REAL IBGatewayConnector + PortfolioTracker (not
fakes), following the pattern established by
tests/test_margin_monitor_frozen_equity_gap.py (#641's own regression test).
"""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from portfolio.tracker import INSTRUMENT_MULTIPLIERS, PortfolioTracker
from risk.safety_layer import SafetyLayer


def _offline_simulated_cfg():
    """Tier-3 live off + explicit simulated-paper opt-in (matches existing
    tests/test_ib_gateway_connector_offline.py / test_margin_monitor_frozen_equity_gap.py)."""
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": True,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
        }
    )


@pytest.mark.asyncio
async def test_submit_paper_order_cash_applies_futures_multiplier(tmp_path):
    """_submit_paper_order (the MKT/LMT fill path) must move cash by
    qty * filled_price * INSTRUMENT_MULTIPLIERS[symbol], not the bare
    price*qty notional.
    """
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)
    assert await conn.connect() is True

    multiplier = INSTRUMENT_MULTIPLIERS["MES"]
    assert multiplier != 1.0, "test requires a futures symbol with a real multiplier"

    before = await conn.get_account_balance()
    starting_cash = before["cash"]

    order_id = await conn.place_paper_order(
        symbol="MES", action="BUY", quantity=1, order_type="LMT", limit_price=5300.0
    )
    assert order_id is not None
    filled_price = conn._open_orders[order_id]["filled_price"]
    assert filled_price is not None

    after = await conn.get_account_balance()

    expected_cash = starting_cash - (1 * filled_price * multiplier)
    wrong_cash_pre_fix = starting_cash - (1 * filled_price)  # bare notional, the bug

    assert after["cash"] == pytest.approx(expected_cash, abs=0.01), (
        "cash did not move by the multiplied notional (qty * filled_price * "
        f"{multiplier}) -- got {after['cash']}, expected {expected_cash}"
    )
    assert after["cash"] != pytest.approx(wrong_cash_pre_fix, abs=0.01), (
        "cash moved by the bare (unmultiplied) notional -- the pre-fix bug"
    )


@pytest.mark.asyncio
async def test_fill_paper_order_cash_applies_futures_multiplier(tmp_path):
    """_fill_paper_order (the STP/simulation-loop fill path -- a code path
    separate from _submit_paper_order) must also apply the futures
    multiplier to cash. Uses a fixed price (no LMT slippage) for a fully
    deterministic assertion.
    """
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)
    assert await conn.connect() is True

    multiplier = INSTRUMENT_MULTIPLIERS["MGC"]
    assert multiplier != 1.0

    starting_cash = conn._account_summary["cash"]

    order_id = "test-stp-fill-mgc"
    conn._open_orders[order_id] = {
        "status": "pending",
        "order_id": order_id,
        "symbol": "MGC",
        "quantity": 1,
        "order_type": "stop",
        "stop_price": 2400.0,
        "is_futures": True,
    }

    await conn._fill_paper_order(order_id, 2400.0)

    expected_cash = starting_cash - (1 * 2400.0 * multiplier)
    wrong_cash_pre_fix = starting_cash - (1 * 2400.0)

    assert conn._account_summary["cash"] == pytest.approx(expected_cash, abs=0.01)
    assert conn._account_summary["cash"] != pytest.approx(wrong_cash_pre_fix, abs=0.01)


@pytest.mark.asyncio
async def test_paper_cash_unaffected_for_non_futures_symbol(tmp_path):
    """Equities (SPY/QQQ/AAPL/TSLA) must keep the 1x cash behavior.

    PR #450 added these names to INSTRUMENT_MULTIPLIERS at 1.0 so sizing and
    P&L resolve them identically (previously position_sizing fell back to the
    $5/pt futures multiplier while the tracker RAISED on them). Multiplier 1.0
    preserves the existing $1-per-share cash behavior -- the assertion moved
    from "not present" to "present with multiplier 1.0" to match that intent.
    """
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)
    assert await conn.connect() is True

    assert INSTRUMENT_MULTIPLIERS.get("SPY") == 1.0

    starting_cash = conn._account_summary["cash"]

    order_id = await conn.place_paper_order(
        symbol="SPY", action="BUY", quantity=1, order_type="LMT", limit_price=450.0
    )
    assert order_id is not None
    filled_price = conn._open_orders[order_id]["filled_price"]

    after = await conn.get_account_balance()
    expected_cash = starting_cash - (1 * filled_price)  # multiplier == 1.0
    assert after["cash"] == pytest.approx(expected_cash, abs=0.01)


@pytest.mark.asyncio
async def test_account_summary_starting_balances_derive_from_initial_capital(tmp_path):
    """equity/cash/buying_power at init time derive from settings.INITIAL_CAPITAL
    (the same source PortfolioTracker._get_starting_balance() uses) rather
    than a standalone literal."""
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)

    initial_capital = float(cfg.INITIAL_CAPITAL)
    assert conn._account_summary["equity"] == initial_capital
    assert conn._account_summary["cash"] == initial_capital
    assert conn._account_summary["buying_power"] == initial_capital * 4
