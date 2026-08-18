"""
Tests for the scanner paper_mode_bypass entry-price sanity gate.

Incident 2026-06-12: an MES paper trade was auto-logged by the scanner
bypass at ``entry_price=100.5`` — an STC oscillator value (0-100) had
leaked into the price field (MES trades ~5,000-6,000). The human-approval
path validates entry prices via ``risk.entry_price_sanity`` (wired in
approval/service.py), but the scanner auto-paper bypass wrote unchecked.

Guard under test (scanner/signal_scanner.py paper_mode_bypass block):
when the technical report carries a market reference (current_price + atr),
an entry price that is many ATR units away from market is BLOCKED before
``add_paper_trade`` is called. When no reference is present the write is
allowed (fail-open) but logged UNVALIDATED — incomplete indicators must
not silently halt all auto-paper trading. A sane entry writes normally.

Harness mirrors test_scanner_position_dedup.py.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Deterministic clock ──────────────────────────────────────────────────────
# A fixed instant: Tuesday 2026-06-16 17:00 UTC == 12:00 ET. Chosen so the
# scanner's wall-clock gates in _scan_symbol() all resolve to "scan allowed":
#   - not in the 9:30-9:35 / 15:45-16:00 ET banned session windows,
#   - not Wednesday (so no futures EIA blackout window ever triggers),
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


# ── Harness ──────────────────────────────────────────────────────────────────


def _build_pipeline_result(
    *,
    entry_price: float = 5200.25,
    current_price: float | None = 5200.0,
    atr: float | None = 18.0,
    final_action: str = "buy",
) -> dict:
    """Pipeline result with a configurable entry price and market reference."""
    indicators: dict = {"stc_value": 78.2, "stark_signal": "LONG_VAL_BOUNCE"}
    if current_price is not None:
        indicators["current_price"] = current_price
    if atr is not None:
        indicators["atr"] = atr
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
                "indicators": indicators,
            }
        },
        "trade_decision": {
            "action": final_action,
            "quantity": 1,
            "confidence": 0.72,
            "entry_price": entry_price,
            "stop_price": entry_price - 20.0,
            "target_price": entry_price + 35.0,
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


async def _run_scan(scanner) -> None:
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol("ZZTEST")


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phantom_price_blocks_auto_log(caplog):
    """The exact 2026-06-12 case: entry 100.5 vs market ~5200 must be blocked."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0001")
    paper_tracker.get_open_positions = MagicMock(return_value=[])

    # entry_price 100.5 (STC leak) while market is ~5200 -> ~272 ATR units off
    result = _build_pipeline_result(entry_price=100.5, current_price=5200.0, atr=18.0)
    scanner = _build_scanner(result, paper_tracker)

    with caplog.at_level(logging.CRITICAL, logger="jarvis_trader.scanner"):
        await _run_scan(scanner)

    paper_tracker.add_paper_trade.assert_not_called()
    blocked = [
        r for r in caplog.records if "entry-price sanity failed" in r.getMessage()
    ]
    assert blocked, (
        "Expected a CRITICAL entry-price sanity block; got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_sane_price_writes_normally():
    """A plausible entry price (near market) auto-logs exactly once."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0002")
    paper_tracker.get_open_positions = MagicMock(return_value=[])

    result = _build_pipeline_result(entry_price=5200.25, current_price=5200.0, atr=18.0)
    scanner = _build_scanner(result, paper_tracker)

    await _run_scan(scanner)

    paper_tracker.add_paper_trade.assert_called_once()


@pytest.mark.asyncio
async def test_missing_reference_fails_open(caplog):
    """No current_price/atr -> write is allowed but logged UNVALIDATED."""
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0003")
    paper_tracker.get_open_positions = MagicMock(return_value=[])

    result = _build_pipeline_result(
        entry_price=5200.25, current_price=None, atr=None
    )
    scanner = _build_scanner(result, paper_tracker)

    with caplog.at_level(logging.WARNING, logger="jarvis_trader.scanner"):
        await _run_scan(scanner)

    paper_tracker.add_paper_trade.assert_called_once()
    unvalidated = [r for r in caplog.records if "UNVALIDATED" in r.getMessage()]
    assert unvalidated, "expected an UNVALIDATED warning when reference is missing"


@pytest.mark.asyncio
async def test_disabled_flag_skips_gate(monkeypatch):
    """ENABLE_ENTRY_PRICE_SANITY=0 -> a phantom price is written unchecked."""
    monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "0")

    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-0004")
    paper_tracker.get_open_positions = MagicMock(return_value=[])

    result = _build_pipeline_result(entry_price=100.5, current_price=5200.0, atr=18.0)
    scanner = _build_scanner(result, paper_tracker)

    await _run_scan(scanner)

    # Gate disabled -> the bypass writes even the phantom price.
    paper_tracker.add_paper_trade.assert_called_once()
