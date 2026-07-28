"""D1-01 — stop-monitor close path fails closed on unknown multipliers.

Dashboard-integrity audit finding D1-01 (Tier 1): engine/main.py's
_monitor_open_stops() (the 5-min stop-monitor job) resolved contract
multipliers via a bare ``INSTRUMENT_MULTIPLIERS.get(_sym, _DEFAULT_MULTIPLIER)``
lookup, silently applying a 1.0x multiplier for any symbol missing from
INSTRUMENT_MULTIPLIERS. This is a sibling gap to the already-merged T0-06
commission fix: the tracker's own close_trade()/close_paper_trade() paths use
portfolio.tracker._resolve_multiplier(), which is fail-closed (raises
UnknownInstrumentMultiplierError unless ALLOW_DEFAULT_MULTIPLIER=1), but the
stop-monitor's close path bypassed that guard entirely.

Fix: engine/main.py's stop-monitor close path now calls
portfolio.tracker._resolve_multiplier() and, on
UnknownInstrumentMultiplierError, logs and skips the close (continues to the
next open trade) instead of silently booking a 1x-mis-stated P&L. This is
behavior-identical for every currently-mapped symbol (MES/MGC/MCL/MNQ/ES/NQ/
CL/GC); only an unmapped symbol's behavior changes, from
silently-wrong-1x to fail-closed-skip-with-log.
"""

from __future__ import annotations

import pytest

from portfolio.tracker import (
    UnknownInstrumentMultiplierError,
    _resolve_multiplier,
)


# ── _resolve_multiplier() itself ─────────────────────────────────────────


def test_resolve_multiplier_known_symbols():
    """Known futures symbols resolve to their documented dollar-per-point
    multiplier; lowercase input proves the internal .upper() normalization."""
    assert _resolve_multiplier("MES") == 5.0
    assert _resolve_multiplier("MGC") == 10.0
    assert _resolve_multiplier("mcl") == 100.0


def test_resolve_multiplier_unknown_fails_closed(monkeypatch: pytest.MonkeyPatch):
    """With ALLOW_DEFAULT_MULTIPLIER unset, an unmapped symbol raises rather
    than silently returning a 1.0x fallback."""
    monkeypatch.delenv("ALLOW_DEFAULT_MULTIPLIER", raising=False)
    with pytest.raises(UnknownInstrumentMultiplierError):
        _resolve_multiplier("ZZZ")


def test_allow_default_multiplier_escape_hatch(monkeypatch: pytest.MonkeyPatch):
    """The documented ALLOW_DEFAULT_MULTIPLIER=1 escape hatch still works and
    is the only way to get a 1.0x fallback for an unmapped symbol."""
    monkeypatch.setenv("ALLOW_DEFAULT_MULTIPLIER", "1")
    assert _resolve_multiplier("ZZZ") == 1.0


# ── engine/main.py _monitor_open_stops() call site ──────────────────────────
# _monitor_open_stops is a closure defined inline in main.py's startup code
# and is not importable in isolation (same limitation documented by
# TestStopMonitorLogic in test_safety_fixes_2026_06_01.py and by the T0-06
# commission suite's _main_py_stop_close_pnl faithful-replica helper). This
# test faithfully replicates the post-fix multiplier-resolution block exactly
# as it now appears at engine/main.py's stop-monitor loop, rather than
# reinventing separate logic.


def _stop_mult_or_skip(sym: str) -> float | None:
    """Mirrors engine/main.py::_monitor_open_stops()'s multiplier resolution
    (D1-01): resolve via the fail-closed tracker helper, returning None
    (meaning "skip this close") on UnknownInstrumentMultiplierError instead
    of silently falling back to 1.0x."""
    try:
        return _resolve_multiplier(sym)
    except UnknownInstrumentMultiplierError:
        return None


def test_stop_mult_or_skip_unknown_symbol_returns_none():
    assert _stop_mult_or_skip("ZZZ") is None


def test_stop_mult_or_skip_known_symbol_returns_multiplier():
    assert _stop_mult_or_skip("MGC") == 10.0
