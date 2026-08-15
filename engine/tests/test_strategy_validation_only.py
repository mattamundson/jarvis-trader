"""
Tests for VALIDATION_ONLY_STRATEGIES — TPO_SHORT_GAP_FILL gate.

Verifies that:
  - VALIDATION_ONLY_STRATEGIES is an immutable frozenset containing SHORT_GAP_FILL
  - Scanner paper-mode bypass is skipped for a SHORT_GAP_FILL stark_signal result
  - A known-validated strategy (stark_signal not in the set) still flows through
  - Existing open positions are NOT touched by the gate (gate blocks NEW submissions only)

The gate lives in scanner/signal_scanner.py:_scan_symbol().
The constant lives in agents/pipeline.py.

Root-cause reference:
  docs/session-logs/drawdown-root-cause-may-9-to-11.md
  Incident: 6 phantom paper trades 2026-05-09 to 2026-05-11 from SHORT_GAP_FILL
  signal with NULL wfe_snapshots metrics and no gate v2 verdict.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constant integrity ─────────────────────────────────────────────────────────


def test_tpo_short_gap_fill_in_validation_only_set():
    """VALIDATION_ONLY_STRATEGIES must be a frozenset containing SHORT_GAP_FILL."""
    from agents.pipeline import VALIDATION_ONLY_STRATEGIES

    assert isinstance(
        VALIDATION_ONLY_STRATEGIES,
        frozenset,
    ), "VALIDATION_ONLY_STRATEGIES must be a frozenset to prevent accidental mutation"
    assert "SHORT_GAP_FILL" in VALIDATION_ONLY_STRATEGIES, (
        "SHORT_GAP_FILL must be in VALIDATION_ONLY_STRATEGIES — "
        "gated 2026-05-21 after phantom-price drawdown incident"
    )


def test_validation_only_strategies_exported_in_all():
    """VALIDATION_ONLY_STRATEGIES must appear in pipeline.__all__ for explicit export."""
    import agents.pipeline as _pipeline_mod

    assert "VALIDATION_ONLY_STRATEGIES" in _pipeline_mod.__all__, (
        "VALIDATION_ONLY_STRATEGIES must be in pipeline.__all__ so scanner "
        "and tests can import it cleanly."
    )


# ── Scanner gate: SHORT_GAP_FILL does NOT submit paper trade ──────────────────


def _build_pipeline_result(stark_signal: str, final_action: str = "sell") -> dict:
    """Minimal pipeline result dict matching scanner's expected shape."""
    return {
        "final_action": final_action,
        "final_quantity": 1,
        "requires_human": False,
        "confidence": 0.72,
        "summary": f"TEST | action={final_action.upper()} qty=1 | conviction=72%",
        "analyst_reports": {
            "technical": {
                "regime": "RANGING",
                "trend": "bearish",
                "indicators": {
                    "stc_value": 12.4,
                    "stark_signal": stark_signal,
                },
            }
        },
        "trade_decision": {
            "action": final_action,
            "quantity": 1,
            "confidence": 0.72,
            "entry_price": 5200.25,
            "stop_price": 5210.00,
            "target_price": 5185.00,
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
        symbols=["ZZTEST"],
        initial_delay_seconds=0,
    )
    scanner.set_paper_tracker(paper_tracker)
    return scanner


@pytest.mark.asyncio
async def test_validation_only_strategy_does_not_submit_order(caplog):
    """
    When stark_signal == SHORT_GAP_FILL, scanner must skip paper_tracker.add_paper_trade()
    and emit a [VALIDATION_ONLY] log line.  The pending approval row IS still created
    for audit/dashboard visibility.
    """
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock()

    result = _build_pipeline_result(stark_signal="SHORT_GAP_FILL", final_action="sell")
    scanner = _build_scanner(result, paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
        caplog.at_level(logging.WARNING, logger="jarvis_trader.scanner"),
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("ZZTEST")

    # Paper trade must NOT have been submitted
    paper_tracker.add_paper_trade.assert_not_called(), (
        "add_paper_trade must NOT be called for a SHORT_GAP_FILL signal — "
        "strategy is in VALIDATION_ONLY_STRATEGIES"
    )

    # Pending approval row MUST have been created (audit visibility)
    scanner.db_manager.insert_pending_approval.assert_called_once()

    # [VALIDATION_ONLY] log line must be present
    validation_log_lines = [r for r in caplog.records if "[VALIDATION_ONLY]" in r.message]
    assert validation_log_lines, (
        "Expected a [VALIDATION_ONLY] log line when SHORT_GAP_FILL is skipped; got none. "
        f"All WARNING+ log messages: {[r.message for r in caplog.records]}"
    )
    assert "SHORT_GAP_FILL" in validation_log_lines[0].message


@pytest.mark.asyncio
async def test_validated_strategy_still_submits(caplog):
    """
    A stark_signal NOT in VALIDATION_ONLY_STRATEGIES (e.g. LONG_VAL_BOUNCE)
    must still flow through to paper_tracker.add_paper_trade() — regression check.
    """
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0001")

    result = _build_pipeline_result(stark_signal="LONG_VAL_BOUNCE", final_action="buy")
    scanner = _build_scanner(result, paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        # Entry price must be non-None for bypass to trigger
        result["trade_decision"]["entry_price"] = 5200.25
        await scanner._scan_symbol("ZZTEST")

    paper_tracker.add_paper_trade.assert_called_once(), (
        "add_paper_trade must be called for LONG_VAL_BOUNCE — "
        "signal is not in VALIDATION_ONLY_STRATEGIES"
    )

    # No [VALIDATION_ONLY] warning should appear
    validation_log_lines = [r for r in caplog.records if "[VALIDATION_ONLY]" in r.message]
    assert not validation_log_lines, (
        "No [VALIDATION_ONLY] log line expected for LONG_VAL_BOUNCE; "
        f"got: {[r.message for r in validation_log_lines]}"
    )


@pytest.mark.asyncio
async def test_validation_only_does_not_force_close_existing(caplog):
    """
    The strategy gate only blocks NEW submissions.
    Existing open positions (tracked in paper_tracker._open) must NOT be touched.
    """
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock()
    # Simulate an existing open position for the symbol
    existing_trade = MagicMock()
    existing_trade.is_open = True
    existing_trade.entry_price = 5180.00
    existing_trade.symbol = "ZZTEST"
    paper_tracker._open = {"existing-trade-id-0001": existing_trade}

    result = _build_pipeline_result(stark_signal="SHORT_GAP_FILL", final_action="sell")
    scanner = _build_scanner(result, paper_tracker)

    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("ZZTEST")

    # Existing open positions must not be closed
    assert (
        existing_trade.is_open is True
    ), "Existing open position must NOT be force-closed by the validation-only gate"
    # No new trade should be added
    paper_tracker.add_paper_trade.assert_not_called()
