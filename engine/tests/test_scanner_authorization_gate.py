"""
Tests for the scanner paper_mode_bypass halt-list gate (GT-52).

Finding: signal_scanner.py's paper-mode bypass writes straight to
paper_trades via ``self._paper_tracker.add_paper_trade()`` without ever
consulting DO_NOT_TRADE_SYMBOLS or paper_config.enabled. Reproduced live
2026-08-01: MGC wrote 5 paper trades on 2026-07-31 despite being in
DO_NOT_TRADE_SYMBOLS at the time.

Fix under test: ``_symbol_is_halted_for_scanner()`` plus a new elif rung in
the bypass gate ladder. Deliberately narrower than full gate-v2 authorization
(``gate_v2_policy.is_strategy_authorized``) -- that check also requires a
PAPER_CONFIGS entry, which would block SPY/QQQ/AAPL/TSLA. Amo explicitly
decided 2026-08-03 (engine/CLAUDE.md "Active Instruments > Equities") to
keep those four trading as-is, so this gate blocks ONLY the explicit halt
list (DO_NOT_TRADE_SYMBOLS membership, or a PAPER_CONFIGS entry with
enabled=False) and leaves symbols with no PAPER_CONFIGS entry untouched.

Harness mirrors test_scanner_entry_price_gate.py.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backtest.paper_config as _paper_config_mod
import backtest.signals as _signals_mod

# The helper under test tries `engine.backtest.signals` before falling back to
# the bare `backtest.signals` (matching the existing dual-import idiom
# elsewhere in this file). Depending on what else has already imported
# `engine.*` in a given test run, EITHER module object can be the one that's
# actually live -- they are two separate objects in sys.modules even though
# they load the same file. Patch both so these tests don't depend on import
# race order.
try:
    import engine.backtest.paper_config as _eng_paper_config_mod
    import engine.backtest.signals as _eng_signals_mod
except ImportError:  # pragma: no cover - "engine" not a resolvable package here
    _eng_paper_config_mod = None
    _eng_signals_mod = None


def _patch_halt_state(monkeypatch, *, do_not_trade=frozenset(), paper_configs=None):
    paper_configs = {} if paper_configs is None else paper_configs
    monkeypatch.setattr(_signals_mod, "DO_NOT_TRADE_SYMBOLS", do_not_trade)
    monkeypatch.setattr(_paper_config_mod, "PAPER_CONFIGS", paper_configs)
    if _eng_signals_mod is not None:
        monkeypatch.setattr(_eng_signals_mod, "DO_NOT_TRADE_SYMBOLS", do_not_trade)
        monkeypatch.setattr(_eng_paper_config_mod, "PAPER_CONFIGS", paper_configs)

# ── Deterministic clock (see test_scanner_entry_price_gate.py for rationale) ──
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
        patch("scanner.signal_scanner._is_equity_market_hours", return_value=True),
    ):
        yield


# ── Harness ──────────────────────────────────────────────────────────────────


def _build_pipeline_result(*, entry_price: float = 5200.25, final_action: str = "buy") -> dict:
    indicators = {
        "stc_value": 78.2,
        "stark_signal": "LONG_VAL_BOUNCE",
        "current_price": entry_price,
        "atr": 18.0,
    }
    return {
        "final_action": final_action,
        "final_quantity": 1,
        "requires_human": False,
        "confidence": 0.72,
        "summary": f"TEST | action={final_action.upper()} qty=1 | conviction=72%",
        "analyst_reports": {
            "technical": {"regime": "TRENDING", "trend": "bullish", "indicators": indicators}
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


def _build_scanner(pipeline_result: dict, paper_tracker: MagicMock, symbol: str) -> "object":
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
        symbols=[symbol],
        initial_delay_seconds=0,
    )
    scanner.set_paper_tracker(paper_tracker)
    return scanner


async def _run_scan(scanner, symbol: str) -> None:
    with (
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("config.settings") as mock_settings,
    ):
        mock_settings.LIVE_TRADING_ENABLED = False
        await scanner._scan_symbol(symbol)


def _tracker() -> MagicMock:
    paper_tracker = MagicMock()
    paper_tracker.add_paper_trade = MagicMock(return_value="trade-id-halt-gate")
    paper_tracker.get_open_positions = MagicMock(return_value=[])
    return paper_tracker


# ── Unit tests: _symbol_is_halted_for_scanner in isolation ────────────────────
# Patched constants so these don't drift when the live halt list changes again
# (it already has, twice, during this fix's own investigation).


def test_helper_blocks_do_not_trade_member(monkeypatch):
    from scanner.signal_scanner import _symbol_is_halted_for_scanner

    _patch_halt_state(monkeypatch, do_not_trade=frozenset({"ZZTEST"}))
    assert _symbol_is_halted_for_scanner("ZZTEST") is True


def test_helper_blocks_disabled_paper_config_entry(monkeypatch):
    from scanner.signal_scanner import _symbol_is_halted_for_scanner

    _patch_halt_state(monkeypatch, paper_configs={"ZZTEST": {"enabled": False}})
    assert _symbol_is_halted_for_scanner("ZZTEST") is True


def test_helper_allows_enabled_paper_config_entry(monkeypatch):
    from scanner.signal_scanner import _symbol_is_halted_for_scanner

    _patch_halt_state(monkeypatch, paper_configs={"ZZTEST": {"enabled": True}})
    assert _symbol_is_halted_for_scanner("ZZTEST") is False


def test_helper_allows_symbol_with_no_paper_config_entry(monkeypatch):
    """Equities carve-out: no entry at all -> not halted (2026-08-03 decision)."""
    from scanner.signal_scanner import _symbol_is_halted_for_scanner

    _patch_halt_state(monkeypatch)
    assert _symbol_is_halted_for_scanner("SPY") is False


# ── Integration tests: wired into the scanner's bypass gate ladder ────────────


@pytest.mark.asyncio
async def test_halted_symbol_blocks_paper_write(monkeypatch, caplog):
    _patch_halt_state(monkeypatch, do_not_trade=frozenset({"ZZHALT"}))

    paper_tracker = _tracker()
    result = _build_pipeline_result()
    scanner = _build_scanner(result, paper_tracker, "ZZHALT")

    with caplog.at_level(logging.CRITICAL, logger="jarvis_trader.scanner"):
        await _run_scan(scanner, "ZZHALT")

    paper_tracker.add_paper_trade.assert_not_called()
    blocked = [r for r in caplog.records if "reason=symbol_halted" in r.getMessage()]
    assert blocked, (
        "Expected a CRITICAL symbol_halted block; got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_non_halted_futures_symbol_still_writes(monkeypatch):
    _patch_halt_state(monkeypatch, paper_configs={"ZZOK": {"enabled": True}})

    paper_tracker = _tracker()
    result = _build_pipeline_result()
    scanner = _build_scanner(result, paper_tracker, "ZZOK")

    await _run_scan(scanner, "ZZOK")

    paper_tracker.add_paper_trade.assert_called_once()


@pytest.mark.asyncio
async def test_equity_with_no_paper_config_entry_still_writes(monkeypatch):
    """Regression pin for the 2026-08-03 equities decision: SPY/QQQ/AAPL/TSLA
    have no PAPER_CONFIGS entry and must NOT be blocked by this gate."""
    _patch_halt_state(monkeypatch)

    paper_tracker = _tracker()
    result = _build_pipeline_result()
    scanner = _build_scanner(result, paper_tracker, "SPY")

    await _run_scan(scanner, "SPY")

    paper_tracker.add_paper_trade.assert_called_once()
