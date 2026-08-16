"""Data-provenance stamping for signal_scanner's insert_decision caller.

PR #286 stamped {last_bar_source, serve_age_s} onto main.py's `_log_decision`
path only. This pins the same stamping on `SignalScanner._scan_symbol`'s
"Also write to the decisions table" block, additive only — no schema change,
no change to existing signal_data fields.

Mirrors tests/test_scanner_safety_gates.py's `_build_scanner` + frozen-clock
conventions, trimmed to just what's needed to reach the insert_decision call
(final_action="hold" so the test never touches the live-opener path).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Tuesday 2026-06-16 17:00 UTC == 12:00 ET — inside RTH, not in the banned
# session windows, not Wednesday (no MCL EIA blackout). Deterministic so the
# test result never depends on wall-clock time.
_FROZEN_UTC = datetime(2026, 6, 16, 17, 0, 0, tzinfo=timezone.utc)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return _FROZEN_UTC.astimezone(tz)
        return _FROZEN_UTC.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _freeze_scanner_clock():
    with (
        patch("scanner.signal_scanner.datetime", _FrozenDateTime),
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
    ):
        yield


class _FakeDM:
    def __init__(self, source, freshness):
        self._last_bar_source = source
        self._freshness = freshness

    def symbol_freshness(self):
        return self._freshness


def _build_pipeline_result() -> dict:
    return {
        "final_action": "hold",  # stops before the live-opener path entirely
        "final_quantity": 1,
        "requires_human": False,
        "confidence": 0.5,
        "summary": "TEST | action=HOLD",
        "analyst_reports": {"technical": {"regime": "RANGING"}},
        "trade_decision": {"action": "hold", "confidence": 0.5, "reasoning": "no edge"},
        "fund_decision": {"final_conviction": 0.5},
    }


def _build_scanner(*, data_manager=None):
    from scanner.signal_scanner import SignalScanner

    mock_pipeline = MagicMock()
    mock_pipeline.analyze_and_decide = AsyncMock(return_value=_build_pipeline_result())

    mock_db = MagicMock()
    mock_db.insert_pipeline_run = MagicMock()
    mock_db.insert_decision = MagicMock()

    scanner = SignalScanner(
        trading_pipeline=mock_pipeline,
        db_manager=mock_db,
        symbols=["MES"],
        initial_delay_seconds=0,
    )
    if data_manager is not None:
        scanner.set_data_manager(data_manager)
    return scanner, mock_db


@pytest.mark.asyncio
async def test_scan_symbol_stamps_provenance_when_data_manager_injected():
    dm = _FakeDM("polygon", {"MES": 2.5})
    scanner, mock_db = _build_scanner(data_manager=dm)

    await scanner._scan_symbol("MES")

    mock_db.insert_decision.assert_called_once()
    sig = mock_db.insert_decision.call_args.kwargs["signal_data"]
    assert sig["data_provenance"] == {"last_bar_source": "polygon", "serve_age_s": 2.5}
    assert sig["source"] == "scanner"  # caller's fields preserved


@pytest.mark.asyncio
async def test_scan_symbol_survives_when_data_manager_absent():
    scanner, mock_db = _build_scanner(data_manager=None)

    await scanner._scan_symbol("MES")

    mock_db.insert_decision.assert_called_once()
    sig = mock_db.insert_decision.call_args.kwargs["signal_data"]
    assert "data_provenance" not in sig
