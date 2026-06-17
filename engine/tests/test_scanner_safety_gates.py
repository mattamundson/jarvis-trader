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
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Deterministic clock ──────────────────────────────────────────────────────
# A fixed instant: Tuesday 2026-06-16 17:00 UTC == 12:00 ET. Chosen so the
# scanner's wall-clock gates in _scan_symbol() all resolve to "scan allowed":
#   - not in the 9:30-9:35 / 15:45-16:00 ET banned session windows,
#   - not Wednesday (so the MCL 10:15-11:00 ET EIA blackout never triggers),
#   - inside equity Regular Trading Hours.
# Without this, the outcome depends on the wall-clock time CI runs at (flaky).
# The default _is_equity_market_hours=True here is overridden by the two
# tests that intentionally exercise the closed-market path (their inner
# `with patch(...)` wins inside the fixture's context).
_FROZEN_UTC = datetime(2026, 6, 16, 17, 0, 0, tzinfo=timezone.utc)


class _FrozenDateTime(datetime):
    """datetime subclass whose now() is pinned to _FROZEN_UTC."""

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return _FROZEN_UTC.astimezone(tz)
        return _FROZEN_UTC.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _freeze_scanner_clock():
    """Pin all wall-clock-dependent scanner gates to a deterministic instant.

    Covers the _scan_symbol() session-timing / EIA-blackout gates plus both
    market-hours helpers so a test never depends on when CI runs.
    """
    with (
        patch("scanner.signal_scanner.datetime", _FrozenDateTime),
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("scanner.signal_scanner._is_equity_market_hours", return_value=True),
    ):
        yield


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
    # Mirror the REAL SafetyLayer.get_status() contract: the latched flag is
    # exposed as "is_killed" (safety_router maps it to public kill_switch_active).
    # A mock keyed on "kill_switch_active" masked the 2026-06-15 wrong-key bug
    # where the live opener read a non-existent key and bypassed the switch.
    safety.get_status = MagicMock(return_value={"is_killed": True})
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
    safety.get_status = MagicMock(return_value={"is_killed": False})
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


# -- Equity execution (OPTIONS_WATCHLIST symbols become paper trades) --------


@pytest.mark.asyncio
async def test_equity_symbol_executes_with_is_futures_false():
    """A symbol NOT in the futures set is analyzed + priced as an equity and
    still opens a paper trade through the same safety-gated path."""
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())
    # Declare only MES as futures -> QQQ is treated as an equity.
    scanner.set_futures_symbols(["MES"])

    sanity = AsyncMock(return_value=(True, ""))
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        # Equity RTH open — the market-hours submission guard must allow booking.
        patch("scanner.signal_scanner._is_equity_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        patch("risk.entry_price_sanity.check_entry_price_sanity", new=sanity),
        patch("notifications.openclaw_notifier.notify_trade_opened", new=AsyncMock()),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("QQQ")

    # Pipeline analyzed QQQ as an equity.
    _, akwargs = scanner.trading_pipeline.analyze_and_decide.call_args
    assert akwargs.get("is_futures") is False
    # Sanity check ran with is_futures=False.
    _, skwargs = sanity.call_args
    assert skwargs.get("is_futures") is False
    # And the equity paper trade was booked.
    pt.add_paper_trade.assert_called_once()


@pytest.mark.asyncio
async def test_equity_submission_blocked_outside_rth():
    """An equity signal outside Regular Trading Hours must NOT auto-book a paper
    trade (the 20:24 off-hours stale-fill class). Futures are unaffected."""
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())
    scanner.set_futures_symbols(["MES"])  # QQQ -> equity

    sanity = AsyncMock(return_value=(True, ""))
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        # Equity market CLOSED → guard blocks submission.
        patch("scanner.signal_scanner._is_equity_market_hours", return_value=False),
        patch("config.settings") as mock_settings,
        patch("risk.entry_price_sanity.check_entry_price_sanity", new=sanity),
        patch("notifications.openclaw_notifier.notify_trade_opened", new=AsyncMock()),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("QQQ")

    # No paper trade booked; the entry-sanity gate was never even reached.
    pt.add_paper_trade.assert_not_called()
    sanity.assert_not_called()


@pytest.mark.asyncio
async def test_equity_guard_can_be_disabled_by_env(monkeypatch):
    """ENABLE_MARKET_HOURS_SUBMISSION_GUARD=0 restores pre-guard behavior."""
    monkeypatch.setenv("ENABLE_MARKET_HOURS_SUBMISSION_GUARD", "0")
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())
    scanner.set_futures_symbols(["MES"])  # QQQ -> equity

    sanity = AsyncMock(return_value=(True, ""))
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("scanner.signal_scanner._is_equity_market_hours", return_value=False),
        patch("config.settings") as mock_settings,
        patch("risk.entry_price_sanity.check_entry_price_sanity", new=sanity),
        patch("notifications.openclaw_notifier.notify_trade_opened", new=AsyncMock()),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("QQQ")

    # Guard disabled → equity books even though _is_equity_market_hours is False.
    pt.add_paper_trade.assert_called_once()


# -- Approval-row gating (no more "approve a trade that never happens" noise) --


@pytest.mark.asyncio
async def test_autonomous_mode_skips_pending_approval_row():
    """REQUIRE_HUMAN_APPROVAL=False -> NO pending_trade_approvals row is created
    (those only time out and auto-reject, spamming the user); the executed paper
    trade is the record of record."""
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        patch(
            "risk.entry_price_sanity.check_entry_price_sanity",
            new=AsyncMock(return_value=(True, "")),
        ),
        patch("notifications.openclaw_notifier.notify_trade_opened", new=AsyncMock()),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        await scanner._scan_symbol("MES")

    scanner.db_manager.insert_pending_approval.assert_not_called()
    pt.add_paper_trade.assert_called_once()


@pytest.mark.asyncio
async def test_human_mode_still_creates_pending_approval_row():
    """REQUIRE_HUMAN_APPROVAL=True -> the approval row IS still created."""
    pt = _flat_tracker()
    scanner = _build_scanner(pt, data_manager=MagicMock())
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        patch(
            "risk.entry_price_sanity.check_entry_price_sanity",
            new=AsyncMock(return_value=(True, "")),
        ),
        patch("notifications.openclaw_notifier.notify_trade_opened", new=AsyncMock()),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        mock_settings.REQUIRE_HUMAN_APPROVAL = True
        await scanner._scan_symbol("MES")

    scanner.db_manager.insert_pending_approval.assert_called_once()
