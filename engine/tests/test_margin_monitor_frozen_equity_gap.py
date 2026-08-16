"""
JARVIS TRADER — MarginMonitorAgent x IBGatewayConnector integration gap
========================================================================
Reproduces a Tier-0/1 safety-invariant bug: when MarginMonitorAgent is wired
to the REAL IBGatewayConnector (as it is in main.py — `_margin_connector =
ib_paper_connector or data_manager.ibkr`), the connector's account-balance
``equity`` field is a hardcoded constant set once in ``__init__`` and never
updated by any fill path. Only ``cash`` is adjusted on paper fills
(``_submit_paper_order`` / ``_fill_paper_order``); ``equity`` and
``buying_power`` were frozen for the lifetime of the connector.

Consequence (pre-fix): MarginMonitorAgent.check_health()'s peak-equity
tracking and drawdown calculation (its ONLY functioning breach detector in
paper mode, since ``margin_used`` is separately hardcoded to 0.0) could NEVER
fire — the account could lose the vast majority of its paper capital and the
monitor would still report "HEALTHY" / 0% drawdown forever.

This is the same failure *shape* as the frozen pnl_snapshots equity bug
(fixed for safety_layer.sync_from_broker in the T0-02 PR), but a DIFFERENT
code path/file (IBGatewayConnector.get_account_balance(), which specifically
feeds MarginMonitorAgent, not the safety_layer daily-loss circuit breaker).
Existing tests/test_margin_monitor.py and tests/test_risk_margin_monitor.py
only ever exercise MarginMonitorAgent against hand-shaped fake connectors
that already update equity correctly — they never touch the real
IBGatewayConnector, so this integration gap was invisible to the existing
suite. These tests exercise the real connector end-to-end.
"""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from portfolio.tracker import PortfolioTracker
from risk.margin_monitor import MarginMonitorAgent
from risk.safety_layer import SafetyLayer


def _offline_simulated_cfg():
    """Tier-3 live off + explicit simulated-paper opt-in (matches existing
    tests/test_ib_gateway_connector_offline.py pattern)."""
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


async def _realize_catastrophic_loss(conn: IBGatewayConnector) -> None:
    """Buy 1 MGC @ 2400 then sell the same contract @ 2180 -- a realized,
    round-tripped loss of $2,200 (10x contract multiplier) on a $10,000
    paper account -- ~22% of starting equity.

    MGC is a recognized futures root (is_futures routing + a configured
    portfolio.tracker.INSTRUMENT_MULTIPLIERS entry, avoiding the unrelated
    "no contract multiplier configured" rejection an unlisted synthetic
    symbol would hit) but is NOT in IBGatewayConnector's static mock-quote
    table, so _submit_paper_order falls back to the caller-supplied
    limit_price deterministically (no live/mock quote overriding it). The
    ~9% entry/exit price deviation is picked to stay comfortably under
    risk/exit_price_sanity.py's default 25% rejection threshold (this is a
    realized trading loss, not a corrupt-price scenario) while the 10x
    multiplier still produces a $2,200 (~22%) realized loss -- comfortably
    clearing an 8% max-drawdown threshold.
    """
    buy_id = await conn.place_paper_order(
        symbol="MGC", action="BUY", quantity=1, order_type="LMT", limit_price=2400.0
    )
    assert buy_id is not None
    sell_id = await conn.place_paper_order(
        symbol="MGC", action="SELL", quantity=1, order_type="LMT", limit_price=2180.0
    )
    assert sell_id is not None


@pytest.mark.asyncio
async def test_account_balance_equity_reflects_a_catastrophic_realized_loss(tmp_path):
    """Ground-truth expectation: get_account_balance()['equity'] must move
    when the account realizes a large loss -- it cannot stay pinned to the
    startup constant forever.
    """
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)
    assert await conn.connect() is True

    before = await conn.get_account_balance()
    assert before["equity"] == 10000.0

    await _realize_catastrophic_loss(conn)

    after = await conn.get_account_balance()

    # "equity" -- the only field MarginMonitorAgent's drawdown check reads --
    # must reflect the $2,200 realized loss (10x MGC multiplier applied by
    # PortfolioTracker), not stay frozen at $10,000.
    assert after["equity"] < 9200.0, (
        "get_account_balance()['equity'] did not move after a realized "
        "~$2,200 loss -- it is frozen at the init-time constant, so nothing "
        "downstream (MarginMonitorAgent's drawdown check) can ever detect "
        "a real capital loss."
    )


@pytest.mark.asyncio
async def test_margin_monitor_detects_the_same_catastrophic_loss(tmp_path):
    """End-to-end: feed the real connector into MarginMonitorAgent and prove
    the drawdown breach IS detected when the account realizes a ~22% loss.
    """
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)
    await conn.connect()

    monitor = MarginMonitorAgent(connector=conn, max_drawdown_pct=8.0)

    # First check establishes the peak equity ($10,000).
    result_before = await monitor.check_health()
    assert result_before["status"] == "HEALTHY"

    await _realize_catastrophic_loss(conn)

    result_after = await monitor.check_health()

    # The monitor's own max_drawdown_pct=8.0% threshold must trip CRITICAL
    # given a ~99% realized loss on the wired paper account.
    assert result_after["metrics"]["drawdown_pct"] > 8.0, (
        "MarginMonitorAgent did not see any drawdown despite a ~22% "
        "realized loss on the connector it's reading -- the drawdown "
        "safety check is structurally inert because IBGatewayConnector "
        "never updates 'equity' on any fill path."
    )
    assert result_after["status"] == "CRITICAL"
