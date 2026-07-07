"""
Tests for the scanner paper_mode_bypass open-position dedup guard.

Incident 2026-06-11: the engine's hourly scan re-emitted the persisting
trend signal every cycle, and the paper-mode bypass auto-logged a NEW
paper trade each time — MES and MGC were both entered identically at
00:04 and 01:04 (duplicate open positions, identical entry prices).
Duplicates leak past paper_runner's symbol-keyed position dict as
zombie-open rows and contaminate fidelity/Brier calibration data.

Guard under test (scanner/signal_scanner.py paper_mode_bypass block):
an open paper position for the same symbol skips the auto-log with
``executed=False reason=paper_position_already_open``; the pending
approval row is still created for audit visibility.
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


# ── Harness (mirrors test_strategy_validation_only.py) ────────────────────────


def _build_pipeline_result(final_action: str = "buy") -> dict:
    """Minimal pipeline result dict matching scanner's expected shape."""
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
                "indicators": {
                    "stc_value": 78.2,
                    "stark_signal": "LONG_VAL_BOUNCE",
                },
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


def _build_scanner(pipeline_result: dict, paper_tracker: MagicMock) -> "object":
    """Build a minimal SignalScanner wired with mocks."""
    from scanner.signal_scanner import SignalScanner

    mock_pipeline = MagicMock()
    mock_pipeline.analyze_and_decide = AsyncMock(return_value=pipeline_result)

    mock_db = MagicMock()
    mock_db.insert_pipeline_run = MagicMock()
    mock_db.insert_decision = MagicMock()
    mock_db.insert_pending_approval = MagicMock(return_value="approval-uuid-0001")

    scanner = SignalScanner(
        trading_pipeline=mock_pipeline,
        db_manager=mock_db,
        symbols=["MCL"],
        initial_delay_seconds=0,
    )
    scanner.set_paper_tracker(paper_tracker)
    return scanner


def _open_position(symbol: str, trade_id: str = "dup-trade-0001") -> dict:
    """Shape matches PaperTrade.to_dict() for the fields the guard reads."""
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": "buy",
        "quantity": 1.0,
        "entry_price": 5195.00,
        "is_open": True,
        "exit_time": None,
    }


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_position_blocks_duplicate_auto_log(caplog):
    """An open paper position for the symbol must skip add_paper_trade()."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock()
    paper_tracker.get_open_positions = MagicMock(return_value=[_open_position("MCL")])

    scanner = _build_scanner(_build_pipeline_result(), paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        caplog.at_level(logging.INFO, logger="jarvis_trader.scanner"),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MCL")

    paper_tracker.add_paper_trade.assert_not_called()

    # Pending approval row MUST still be created (audit visibility)
    scanner.db_manager.insert_pending_approval.assert_called_once()

    dedup_lines = [
        r for r in caplog.records if "paper_position_already_open" in r.getMessage()
    ]
    assert dedup_lines, (
        "Expected an executed=False reason=paper_position_already_open log line; "
        f"got: {[r.getMessage() for r in caplog.records]}"
    )
    assert "executed=False" in dedup_lines[0].getMessage()
    assert "dup-trad" in dedup_lines[0].getMessage()  # open_trade_id[:8]


@pytest.mark.asyncio
async def test_flat_symbol_still_auto_logs():
    """No open position -> the bypass submits exactly one paper trade."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0001")
    paper_tracker.get_open_positions = MagicMock(return_value=[])

    scanner = _build_scanner(_build_pipeline_result(), paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MCL")

    paper_tracker.add_paper_trade.assert_called_once()


@pytest.mark.asyncio
async def test_open_position_other_symbol_does_not_block():
    """The guard is per-symbol: an open MGC position must not block MCL."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0002")
    paper_tracker.get_open_positions = MagicMock(return_value=[_open_position("MGC")])

    scanner = _build_scanner(_build_pipeline_result(), paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MCL")

    paper_tracker.add_paper_trade.assert_called_once()


@pytest.mark.asyncio
async def test_symbol_match_is_case_insensitive():
    """Tracker rows may carry any casing; 'mcl' must still block MCL."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock()
    paper_tracker.get_open_positions = MagicMock(return_value=[_open_position("mcl")])

    scanner = _build_scanner(_build_pipeline_result(), paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MCL")

    paper_tracker.add_paper_trade.assert_not_called()


@pytest.mark.asyncio
async def test_no_stop_takes_precedence_over_dedup_log(caplog):
    """Missing stop is still the first gate (safety logging unchanged)."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock()
    paper_tracker.get_open_positions = MagicMock(return_value=[_open_position("MCL")])

    result = _build_pipeline_result()
    result["trade_decision"]["stop_price"] = None
    scanner = _build_scanner(result, paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        caplog.at_level(logging.INFO, logger="jarvis_trader.scanner"),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("MCL")

    paper_tracker.add_paper_trade.assert_not_called()
    safety_lines = [r for r in caplog.records if "paper_mode_bypass BLOCKED" in r.getMessage()]
    assert safety_lines, "no-stop safety gate must still fire first"
    dedup_lines = [
        r for r in caplog.records if "paper_position_already_open" in r.getMessage()
    ]
    assert not dedup_lines, "dedup log must not fire when the stop gate already blocked"
