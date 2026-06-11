"""Regression: emergency-stop rounding must use the symbol's real tick grid.

The reconciler's orphan-recovery path hardcoded a 0.25 tick for every symbol.
On a finer grid (MGC=0.10, MCL=0.01) that yields an INVALID price IB can reject,
leaving the orphaned position with no emergency stop. round_to_tick snaps to the
canonical per-symbol tick, with a 0.25 fallback for unregistered symbols, and
never raises (it runs in the recovery path).
"""

from __future__ import annotations

from execution.position_reconciler import round_to_tick


def test_mes_snaps_to_quarter():
    # MES tick = 0.25; nearest grid point wins.
    assert round_to_tick(4503.13, "MES") == 4503.25  # 0.12 from 4503.25 < 0.13 from 4503.00
    assert round_to_tick(4503.10, "MES") == 4503.0
    assert round_to_tick(4503.40, "MES") == 4503.5


def test_mgc_snaps_to_tenth_not_quarter():
    # MGC tick = 0.10. The old hardcoded-0.25 path would snap 2597.13 -> 2597.25,
    # which is NOT a valid MGC price. The fix must snap to 2597.10.
    assert round_to_tick(2597.13, "MGC") == 2597.10
    assert round_to_tick(2597.16, "MGC") == 2597.20
    # And critically, never lands on a 0.25-only grid point that isn't a 0.10 multiple.
    snapped = round_to_tick(2597.13, "MGC")
    assert abs(round(snapped / 0.10) * 0.10 - snapped) < 1e-6


def test_mcl_snaps_to_cent():
    # MCL tick = 0.01
    assert round_to_tick(72.137, "MCL") == 72.14
    assert round_to_tick(72.132, "MCL") == 72.13


def test_unknown_symbol_falls_back_to_quarter_without_raising():
    # No registered spec -> 0.25 fallback, no exception (recovery path must not die).
    assert round_to_tick(100.13, "ZZZZ") == 100.25
    assert round_to_tick(100.10, "ZZZZ") == 100.0


def test_none_or_empty_symbol_is_safe():
    assert round_to_tick(100.13, "") == 100.25  # falls back, no crash


def test_lowercase_symbol_resolved():
    assert round_to_tick(2597.13, "mgc") == 2597.10
