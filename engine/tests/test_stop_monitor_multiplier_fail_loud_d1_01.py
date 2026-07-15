"""D1-01 -- stop-monitor multiplier lookup must fail LOUD, not silent.

Dashboard-integrity audit finding D1-01 (Tier 1, discovery round 1,
2026-07-11): engine/main.py::_monitor_open_stops() resolved a symbol's
contract multiplier via ``INSTRUMENT_MULTIPLIERS.get(symbol, _DEFAULT_MULTIPLIER)``
-- a dict .get() with a silent 1.0x default. The primary close path
(PortfolioTracker.close_trade()) already uses the fail-closed
``_resolve_multiplier()`` (raises ``UnknownInstrumentMultiplierError`` on an
unmapped symbol, per T0-06's sibling fix), but the stop-monitor's automated
close path bypassed that guard entirely -- an unmapped/mistyped futures
symbol would silently book P&L at 1x instead of its true multiplier (e.g.
MES 5x, MGC 10x), understating real gains/losses by up to 1000x (CL/MCL).

Fix: the stop-monitor now calls the SAME ``_resolve_multiplier()`` tracker
uses. On an unmapped symbol it does NOT silently succeed -- it logs a loud
ERROR naming the symbol -- but it also does NOT skip the close. This monitor
exists specifically to enforce a breached stop_loss (the 2026-06-01 MGC #178
incident, documented directly above _monitor_open_stops() in main.py): a
position that rode -128pts past a 6.4pt stop because nothing closed it.
Silently *skipping* the close on an unmapped symbol would recreate that exact
failure mode, so the fallback multiplier is still applied -- just loudly, not
silently.

The stop-monitor job is a closure defined inline in main.py's startup code
and is not importable in isolation (same documented limitation as T0-06's
sibling suite, test_stop_close_commission_t0_06.py). This test faithfully
replicates the post-fix multiplier-resolution logic exactly as it now
appears at engine/main.py's stop-monitor loop, rather than reinventing a
separate implementation.
"""

from __future__ import annotations

import logging

import pytest

from portfolio.tracker import (
    _DEFAULT_MULTIPLIER,
    UnknownInstrumentMultiplierError,
    _resolve_multiplier,
)


def _main_py_resolve_multiplier_faithful(symbol: str) -> tuple[float, bool]:
    """Mirrors engine/main.py::_monitor_open_stops()'s post-fix multiplier
    resolution (D1-01). Returns (multiplier, fell_back_loudly)."""
    try:
        return _resolve_multiplier(symbol), False
    except UnknownInstrumentMultiplierError:
        logging.getLogger(__name__).error(
            "[stop_monitor] No contract multiplier configured for %s -- "
            "closing at stop with a %.1fx fallback so the breach is still "
            "enforced, but this trade's P&L may be wrong. Add %s to "
            "INSTRUMENT_MULTIPLIERS.",
            symbol,
            _DEFAULT_MULTIPLIER,
            symbol,
        )
        return _DEFAULT_MULTIPLIER, True


def test_known_symbol_resolves_its_real_multiplier_not_the_default():
    """MGC (10.0x) must resolve to its real multiplier, never silently 1x."""
    mult, fell_back = _main_py_resolve_multiplier_faithful("MGC")
    assert mult == pytest.approx(10.0)
    assert fell_back is False


def test_known_symbol_case_insensitive():
    mult, fell_back = _main_py_resolve_multiplier_faithful("mes")
    assert mult == pytest.approx(5.0)
    assert fell_back is False


def test_unmapped_symbol_still_closes_with_a_visible_fallback(caplog):
    """The core D1-01 fix: an unmapped symbol does NOT silently succeed with
    a bare 1x -- but it also does NOT skip the close (that would leave a
    stop-breached position open, recreating the 2026-06-01 MGC #178
    incident). It falls back to _DEFAULT_MULTIPLIER loudly, logged at ERROR.
    """
    with caplog.at_level(logging.ERROR):
        mult, fell_back = _main_py_resolve_multiplier_faithful("ZZZFAKE")
    assert mult == pytest.approx(_DEFAULT_MULTIPLIER)
    assert fell_back is True
    assert any(
        "ZZZFAKE" in rec.message and "No contract multiplier" in rec.message
        for rec in caplog.records
    )


def test_unmapped_symbol_fallback_is_never_silent():
    """Regression guard for the exact D1-01 bug shape: the old code was
    ``INSTRUMENT_MULTIPLIERS.get(symbol, _DEFAULT_MULTIPLIER)`` -- a plain
    dict lookup with no logging path at all. Prove the new path always
    raises internally (i.e. goes through the except branch, not a silent
    dict .get()) for any symbol not in INSTRUMENT_MULTIPLIERS.
    """
    with pytest.raises(UnknownInstrumentMultiplierError):
        _resolve_multiplier("ZZZFAKE")


@pytest.mark.parametrize("symbol,expected_mult", [
    ("MCL", 100.0),
    ("MNQ", 2.0),
    ("MES", 5.0),
    ("MGC", 10.0),
    ("ES", 50.0),
    ("NQ", 20.0),
    ("CL", 1000.0),
    ("GC", 100.0),
])
def test_all_currently_traded_symbols_still_resolve_correctly(symbol, expected_mult):
    """Every symbol the fleet actually trades today must be unaffected by
    this change -- this fix only changes behavior for symbols NOT in the
    map."""
    mult, fell_back = _main_py_resolve_multiplier_faithful(symbol)
    assert mult == pytest.approx(expected_mult)
    assert fell_back is False
