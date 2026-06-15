"""
Tests for the live-opener safety gates added to the signal scanner's
paper-mode bypass (2026-06-15 autonomy hardening).

The scanner (scanner/signal_scanner.py) is the path that actually OPENS
autonomous paper trades when REQUIRE_HUMAN_APPROVAL is off. Before this change
it had neither a kill-switch check nor an entry-price-sanity gate -- both existed
only in the enqueue (pipeline_autonomous) and manual-approval (approval/service)
paths. These tests pin the new behavior:

  - kill switch active  -> no auto-execution (fail-closed on status error)
  - entry-price insane   -> no auto-execution (phantom-price guard)
  - sanity check raises  -> no auto-execution (fail-closed)
  - all gates pass       -> exactly one paper trade + a real "trade opened" alert
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_pipeline_result(final_action: str = "buy") -> dict:
    return {
        "final_action": final_action,
        "final_quantity": 1,
        "requires_human": False,
        "confidence": 0.72,
        "summary": f"TEST | action={final_action.upper()} qty=1 | conviction=72%",
        "analyst_reports": {
            "technical": {
                "regime": "TRENDING",
                "trend": "bullish",
                "indicators": {"stc_value": 78.2, "stark_signal": "LONG_VAL_BOUNCE"},
            }
        },
        "trade_decision": {
            "action": final_action,
            "quantity": 1,
            "confidence": 0.72,
            "entry_price": 5200.25,
            "stop_price": 5180.00,
            "target_price": 5235.00,
            "reasoning": "Test reasoning",
        },
        "fund_decision": {"final_conviction": 0.72},
    }


def _build_scanner(
    paper_tracker: MagicMock,
    *,
    safety_layer=None,
    data_manager=None,
) -> "object":
    from scanner.signal_scanner import SignalScanner

    mock_pipeline = MagicMock()
    mock_pipeline.analyze_and_decide = AsyncMock(return_value=_build_pipeline_result())

    mock_db = MagicMock()
    mock_db.insert_pipeline_run = MagicMock()
    mock_db.insert_decision = MagicMock()
    mock_db.insert_pending_approval = MagicMock(return_value="approval-uuid-0001")

    scanner = SignalScanner(
        trading_pipeline=mock_pipeline,
        db_manager=mock_db,
        symbols=["MES"],
        initial_delay_seconds=0,
    )
    scanner.set_paper_tracker(paper_tracker)
    if safety_layer is not None:
        scanner.set_safety_layer(safety_layer)
    if data_manager is not None:
        scanner.set_data_manager(data_manager)
    return scanner


def _flat_tracker() -> MagicMock:
    pt = MagicMock()
    pt.add_paper_trade = MagicMock(return_value="trade-id-0001")
    pt.get_open_positions = MagicMock(return_value=[])
    return pt


# -- Kill switch ------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_active_blocks_open(caplog):
    pt = _flat_tracker()
    safety = MagicMock()
    safety.get_status = MagicMock(return_value={"kill_switch_active": True})
    scanner = _build_scanner(pt, safety_layer=safety)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        caplog.at_level(logging.WARNING, logger="jarvis_trader.scanner"),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MES")

    pt.add_paper_trade.assert_not_called()
    assert any("kill_switch_active" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_kill_switch_status_error_fails_closed():
    pt = _flat_tracker()
    safety = MagicMock()
    safety.get_status = MagicMock(side_effect=RuntimeError("safety layer down"))
    scanner = _build_scanner(pt, safety_layer=safety)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MES")

    # Cannot determine kill-switch state -> must NOT open.
    pt.add_paper_trade.assert_not_called()


@pytest.mark.asyncio
async def test_kill_switch_inactive_allows_open():
    pt = _flat_tracker()
    safety = MagicMock()
    safety.get_status = MagicMock(return_value={"kill_switch_active": False})
    scanner = _build_scanner(pt, safety_layer=safety)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MES")

    pt.add_paper_trade.assert_called_once()


# -- Entry-price sanity (phantom-price guard) -------------------------------


@pytest.mark.asyncio
async def test_insane_entry_price_blocks_open(caplog):
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        patch(
            "risk.entry_price_sanity.check_entry_price_sanity",
            new=AsyncMock(return_value=(False, "entry 1.9 ATR from market")),
        ),
        caplog.at_level(logging.CRITICAL, logger="jarvis_trader.scanner"),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MES")

    pt.add_paper_trade.assert_not_called()
    assert any("entry_price_sanity" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_sanity_check_exception_fails_closed():
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        patch(
            "risk.entry_price_sanity.check_entry_price_sanity",
            new=AsyncMock(side_effect=RuntimeError("data feed dark")),
        ),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MES")

    # An error verifying the price must reject the trade, not let it through.
    pt.add_paper_trade.assert_not_called()


@pytest.mark.asyncio
async def test_sane_entry_price_allows_open_and_alerts():
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())
    opened = AsyncMock(return_value=True)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        patch(
            "risk.entry_price_sanity.check_entry_price_sanity",
            new=AsyncMock(return_value=(True, "")),
        ),
        patch("notifications.openclaw_notifier.notify_trade_opened", new=opened),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MES")

    pt.add_paper_trade.assert_called_once()
    # A real "trade opened" execution confirmation must fire (not the legacy
    # "approval required" prompt).
    opened.assert_awaited_once()
    _, kwargs = opened.call_args
    assert kwargs.get("symbol") == "MES"
    assert kwargs.get("source") == "scanner"
