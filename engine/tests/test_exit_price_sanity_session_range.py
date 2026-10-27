"""Tests for the exit-price session-range anchor.

Regression coverage for the 2026-08-18 phantom close: an MES row was booked at
7,483.00 while the real session range was 7,707.00-7,770.75 (224.00 points BELOW
the session low). Its deviation from entry (7,731.75) was only 3.2%, far under
the existing 25% entry-anchored screen, so the old check passed it and the
resulting -$1,245.25 tripped the daily-loss kill switch, halting trading for 31
days.

Behaviour contracts asserted here (not implementation snapshots):
  - the range anchor catches a stale print the entry-deviation screen cannot
  - the range anchor never rejects a price that IS inside the session range
  - a self-inconsistent range fails closed rather than certifying the price
  - omitting the range preserves the original entry-anchored-only behavior
"""

import pytest

from risk.exit_price_sanity import (
    ExitPriceSanityError,
    assert_exit_price_sane,
    check_exit_price_sanity,
    is_exit_price_within_session_range,
)

# The real 2026-08-18 MES session (from the verified deep 1h cache).
MES_2026_08_18_LOW = 7707.00
MES_2026_08_18_HIGH = 7770.75
PHANTOM_EXIT = 7483.00
PHANTOM_ENTRY = 7731.75


# --- the regression this exists for -----------------------------------------


def test_phantom_exit_is_caught_by_the_session_range_anchor():
    """7,483 was never traded on 2026-08-18 — it must be refused."""
    ok, reason = check_exit_price_sanity(
        "MES",
        PHANTOM_ENTRY,
        PHANTOM_EXIT,
        session_low=MES_2026_08_18_LOW,
        session_high=MES_2026_08_18_HIGH,
    )
    assert ok is False
    assert "BELOW the session low" in reason


def test_entry_deviation_screen_alone_cannot_catch_it():
    """Documents WHY the range anchor is needed: entry-anchored passes it.

    3.2% is under the 25% threshold, and a 249-point adverse move is a
    plausible real trade — so this is not a threshold-tuning problem.
    """
    ok, _ = check_exit_price_sanity("MES", PHANTOM_ENTRY, PHANTOM_EXIT)
    assert ok is True


def test_gross_wrong_era_exit_still_caught_by_deviation_screen():
    """id=296 shape: 5,299.875 entry vs 7,512.50 exit (41.8%)."""
    ok, reason = check_exit_price_sanity("MES", 5299.875, 7512.50)
    assert ok is False
    assert "deviates" in reason


# --- range anchor unit behaviour --------------------------------------------


@pytest.mark.parametrize(
    "exit_price",
    [PHANTOM_EXIT, 7000.0, 1.0, MES_2026_08_18_LOW - 0.01],
)
def test_below_session_low_rejected(exit_price):
    ok, reason = is_exit_price_within_session_range(
        "MES", exit_price, MES_2026_08_18_LOW, MES_2026_08_18_HIGH
    )
    assert ok is False
    assert "BELOW the session low" in reason


def test_above_session_high_rejected():
    ok, reason = is_exit_price_within_session_range(
        "MES", 9999.0, MES_2026_08_18_LOW, MES_2026_08_18_HIGH
    )
    assert ok is False
    assert "ABOVE the session high" in reason


@pytest.mark.parametrize("exit_price", [7707.00, 7731.75, 7707.25, MES_2026_08_18_HIGH])
def test_inside_session_range_accepted(exit_price):
    ok, _ = is_exit_price_within_session_range(
        "MES", exit_price, MES_2026_08_18_LOW, MES_2026_08_18_HIGH
    )
    assert ok is True


def test_tolerance_widens_bounds_only():
    """A small tolerance can admit a borderline print; it cannot admit 7,483."""
    just_below = MES_2026_08_18_LOW - 1.0
    ok_strict, _ = is_exit_price_within_session_range(
        "MES", just_below, MES_2026_08_18_LOW, MES_2026_08_18_HIGH
    )
    ok_tol, _ = is_exit_price_within_session_range(
        "MES", just_below, MES_2026_08_18_LOW, MES_2026_08_18_HIGH, tolerance_pct=0.05
    )
    assert ok_strict is False
    assert ok_tol is True
    assert is_exit_price_within_session_range(
        "MES", PHANTOM_EXIT, MES_2026_08_18_LOW, MES_2026_08_18_HIGH, tolerance_pct=0.05
    )[0] is False


# --- fail-closed on an untrustworthy range ----------------------------------


@pytest.mark.parametrize(
    "low,high",
    [
        (MES_2026_08_18_HIGH, MES_2026_08_18_LOW),   # inverted
        (0.0, MES_2026_08_18_HIGH),                  # non-positive low
        (MES_2026_08_18_LOW, -1.0),                  # non-positive high
        (float("nan"), MES_2026_08_18_HIGH),         # non-finite
        (MES_2026_08_18_LOW, float("inf")),          # non-finite
        ("bad", MES_2026_08_18_HIGH),                # non-numeric
    ],
)
def test_self_inconsistent_range_fails_closed(low, high):
    ok, reason = is_exit_price_within_session_range("MES", 7710.0, low, high)
    assert ok is False
    assert "cannot certify" in reason


def test_partial_range_fails_closed():
    """One bound supplied and the other None is not a usable range."""
    ok, _ = is_exit_price_within_session_range("MES", 7710.0, MES_2026_08_18_LOW, None)
    assert ok is False


# --- backward compatibility -------------------------------------------------


def test_no_range_supplied_leaves_anchor_inactive():
    ok, reason = is_exit_price_within_session_range("MES", 7710.0, None, None)
    assert ok is True
    assert "inactive" in reason


def test_omitting_range_preserves_legacy_behaviour():
    """Callers without market data must behave exactly as before."""
    assert check_exit_price_sanity("MES", 7731.75, 7710.00)[0] is True
    assert check_exit_price_sanity("MES", 7731.75, 9999.00)[0] is False


def test_non_finite_and_non_positive_exit_rejected_regardless_of_range():
    for bad in (float("nan"), float("inf"), 0.0, -5.0, None, "x"):
        ok, _ = check_exit_price_sanity(
            "MES", PHANTOM_ENTRY, bad,
            session_low=MES_2026_08_18_LOW, session_high=MES_2026_08_18_HIGH,
        )
        assert ok is False, f"{bad!r} should be rejected"


# --- the raising wrapper ----------------------------------------------------


def test_assert_raises_on_phantom_and_passes_on_valid(monkeypatch):
    monkeypatch.setenv("ENABLE_EXIT_PRICE_SANITY", "1")
    with pytest.raises(ExitPriceSanityError):
        assert_exit_price_sane(
            "MES", PHANTOM_ENTRY, PHANTOM_EXIT,
            session_low=MES_2026_08_18_LOW, session_high=MES_2026_08_18_HIGH,
        )
    # a genuine in-range close must not raise
    assert_exit_price_sane(
        "MES", PHANTOM_ENTRY, 7710.00,
        session_low=MES_2026_08_18_LOW, session_high=MES_2026_08_18_HIGH,
    )


def test_assert_is_noop_when_guard_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_EXIT_PRICE_SANITY", "0")
    assert_exit_price_sane(
        "MES", PHANTOM_ENTRY, PHANTOM_EXIT,
        session_low=MES_2026_08_18_LOW, session_high=MES_2026_08_18_HIGH,
    )
