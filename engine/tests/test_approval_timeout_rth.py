"""
Regression — approval-timeout RTH detection must be DST-correct.

is_rth() previously hardcoded the summer UTC offset (13:30-20:00 UTC), so for
the ~4 winter months (US EST) the 13:30-14:30 UTC pre-market window was wrongly
classified as RTH and given the shorter 5-minute approval timeout instead of the
10-minute overnight/closed tier. The fix converts to America/New_York; the same
ET wall-clock must map to the same RTH verdict in both seasons.
"""

from __future__ import annotations

from datetime import datetime, timezone

from risk.approval_timeout import (
    TIMEOUT_OVERNIGHT,
    TIMEOUT_RTH,
    get_timeout_for_trade,
    is_rth,
)


def _utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# ── The seasonal bug: 14:00 UTC on a weekday ──────────────────────────────────

def test_summer_1400_utc_is_rth():
    # July (EDT, UTC-4): 14:00 UTC == 10:00 ET → inside RTH.
    assert is_rth(_utc(2026, 7, 1, 14, 0)) is True


def test_winter_1400_utc_is_not_rth():
    # January (EST, UTC-5): 14:00 UTC == 09:00 ET → PRE-MARKET, not RTH.
    # The old summer-offset heuristic returned True here (the bug).
    assert is_rth(_utc(2026, 1, 14, 14, 0)) is False


# ── Same ET wall-clock maps identically across seasons ────────────────────────

def test_same_et_walltime_both_seasons():
    # 10:00 ET is RTH in both seasons (14:00 UTC summer, 15:00 UTC winter).
    assert is_rth(_utc(2026, 7, 1, 14, 0)) is True   # 10:00 EDT
    assert is_rth(_utc(2026, 1, 14, 15, 0)) is True  # 10:00 EST


def test_rth_open_and_close_boundaries_winter():
    # Winter (EST, UTC-5): 09:30 ET = 14:30 UTC (open), 16:00 ET = 21:00 UTC (close).
    assert is_rth(_utc(2026, 1, 14, 14, 30)) is True   # 09:30 EST — open
    assert is_rth(_utc(2026, 1, 14, 14, 29)) is False  # 09:29 EST — pre-market
    assert is_rth(_utc(2026, 1, 14, 21, 0)) is True    # 16:00 EST — close
    assert is_rth(_utc(2026, 1, 14, 21, 1)) is False   # 16:01 EST — after-hours


def test_weekend_is_never_rth():
    # 2026-06-06 is a Saturday; 14:00 UTC would be RTH-time on a weekday.
    assert is_rth(_utc(2026, 6, 6, 14, 0)) is False


# ── End-to-end: the timeout tier follows the corrected verdict ─────────────────

def test_timeout_tier_follows_rth_verdict(monkeypatch):
    import risk.approval_timeout as mod

    assert TIMEOUT_OVERNIGHT > TIMEOUT_RTH

    # Winter pre-market (the formerly-misclassified window) → overnight tier.
    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: False)
    assert get_timeout_for_trade({"symbol": "MES"}) == TIMEOUT_OVERNIGHT

    # Inside RTH → the shorter RTH tier.
    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: True)
    assert get_timeout_for_trade({"symbol": "MES"}) == TIMEOUT_RTH
