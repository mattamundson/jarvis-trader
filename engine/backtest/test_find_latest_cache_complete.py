"""Tests for _find_latest_cache's completeness preference.

The end-date-keyed selector picks the latest END date, which does NOT imply the
file is COMPLETE: a holed late-end cache can out-sort a clean earlier one. With
`prefer_complete=True` (default), _find_latest_cache delegates to
cache_completeness.find_trustworthy_cache and prefers the latest-end FULLY
trustworthy cache, falling back to latest-end when none is trustworthy.

Run:  cd engine && .venv/Scripts/python backtest/test_find_latest_cache_complete.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")

from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402


def _utc(y, mo, d, h=0):
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


def _write(d, name, stamps):
    fp = os.path.join(d, name)
    rows = ["timestamp,open,high,low,close,volume"]
    for t in stamps:
        rows.append(f"{t.isoformat()},1,1,1,1,1")
    with open(fp, "w") as fh:
        fh.write("\n".join(rows) + "\n")


def _clean_older(d):
    # continuous 5m Mon 2026-01-05 -> Fri 2026-01-09, end 01-09
    a = [_utc(2026, 1, 5) + timedelta(minutes=5 * i) for i in range(288 * 5)]
    _write(d, "SYM_2026-01-05_2026-01-09_5m_cont.csv", a)


def _holed_newer(d):
    # later end (01-16) but Jan 7+8 deleted (unexplained mid-week weekdays)
    b = [
        t
        for t in (_utc(2026, 1, 5) + timedelta(minutes=5 * i) for i in range(288 * 12))
        if t.date() not in (datetime(2026, 1, 7).date(), datetime(2026, 1, 8).date())
    ]
    _write(d, "SYM_2026-01-05_2026-01-16_5m_cont.csv", b)


def test_prefers_clean_older_over_holed_latest_end():
    d = tempfile.mkdtemp()
    _clean_older(d)
    _holed_newer(d)
    chosen = _find_latest_cache(Path(d), "SYM", "_5m_cont.csv", prefer_complete=True)
    assert chosen.name.endswith("2026-01-09_5m_cont.csv"), chosen.name
    print("[PASS] prefer_complete picks the clean earlier cache over holed latest-end")


def test_prefer_complete_false_keeps_latest_end():
    d = tempfile.mkdtemp()
    _clean_older(d)
    _holed_newer(d)
    chosen = _find_latest_cache(Path(d), "SYM", "_5m_cont.csv", prefer_complete=False)
    assert chosen.name.endswith("2026-01-16_5m_cont.csv"), chosen.name
    print("[PASS] prefer_complete=False keeps pure latest-end behavior")


def test_default_is_prefer_complete():
    d = tempfile.mkdtemp()
    _clean_older(d)
    _holed_newer(d)
    chosen = _find_latest_cache(Path(d), "SYM", "_5m_cont.csv")  # default
    assert chosen.name.endswith("2026-01-09_5m_cont.csv"), chosen.name
    print("[PASS] completeness preference is the default")


def test_single_candidate_returned_unchanged():
    d = tempfile.mkdtemp()
    _holed_newer(d)  # only the holed file present
    chosen = _find_latest_cache(Path(d), "SYM", "_5m_cont.csv", prefer_complete=True)
    assert chosen.name.endswith("2026-01-16_5m_cont.csv"), chosen.name
    print("[PASS] single candidate returned unchanged (no switch on lone file)")


def test_none_trustworthy_falls_back_to_latest_end():
    d = tempfile.mkdtemp()
    _holed_newer(d)  # 01-16, holed
    # a second, EARLIER-end, also-holed cache
    c = [
        t
        for t in (_utc(2026, 1, 5) + timedelta(minutes=5 * i) for i in range(288 * 8))
        if t.date() != datetime(2026, 1, 7).date()
    ]
    _write(d, "SYM_2026-01-05_2026-01-12_5m_cont.csv", c)
    chosen = _find_latest_cache(Path(d), "SYM", "_5m_cont.csv", prefer_complete=True)
    # neither is fully trustworthy -> fall back to the latest end-date (01-16)
    assert chosen.name.endswith("2026-01-16_5m_cont.csv"), chosen.name
    print("[PASS] none trustworthy -> falls back to latest end-date")


def _continuous_1h(start, end):
    """Hourly bars from `start` to `end` inclusive, no gaps at all (synthetic --
    real futures data has weekends too, but this scenario isolates the early-
    close / stray-anomaly behavior without weekend noise)."""
    out = []
    t = start
    while t <= end:
        out.append(t)
        t += timedelta(hours=1)
    return out


def _remove_window(stamps, day, start_hour, end_hour):
    """Drop bars on `day` between start_hour (exclusive) and end_hour (exclusive),
    i.e. the bar AT start_hour survives, the next present bar is at end_hour."""
    return [
        t
        for t in stamps
        if not (t.date() == day and start_hour < t.hour < end_hour)
    ]


def test_real_bug_repro_mostly_clean_latest_beats_tiny_lucky_clean_window():
    """Reproduces the actual 2026-07-06 vwap-sharpe bug on synthetic data.

    The real MES_*_1h.csv cache (12,612 bars, end 2026-07-03) was rejected as
    "holed" by _find_latest_cache in favor of a 964-bar 2-month cache
    (2026-03-21 -> 2026-05-20) that merely got lucky and dodged every calendar
    landmine. Empirical inspection of the real file found 14 flagged gaps: 13
    were legitimate CME early-close half-days (quarterly triple-witching
    Fridays, day-before-July4, Christmas Eve) or missing 2024-holiday-whitelist
    entries (Memorial Day / Juneteenth / Labor Day 2024) -- NONE of those imply
    a full weekday of trading data is actually missing. Exactly 1 gap
    (2025-10-06 20:00 -> 2025-10-07 08:00, a lone 12h overnight anomaly with no
    missing calendar day either) had no calendar explanation at all -- a
    genuine, isolated data blip.

    This test builds that shape: a big, current, mostly-clean cache with (a)
    one early-close-pattern gap on a real quarterly-witching Friday
    (2024-06-21, matches the actual MES gap) and (b) one unexplained but
    PURELY-INTRADAY anomaly gap (missing_days=[]), competing against a small,
    later-starting, perfectly-clean 3-week cache with an EARLIER end date.
    The fix must select the big/current file -- an isolated intraday blip in
    an otherwise-huge cache must not lose to a tiny cache that simply avoided
    every landmine.
    """
    d = tempfile.mkdtemp()

    big = _continuous_1h(_utc(2024, 6, 1), _utc(2024, 9, 1))
    # (a) early-close pattern: 2024-06-21 is a real quarterly triple-witching
    # Friday: strip 13:00-20:00 (exclusive bounds -> bars at 13:00 present,
    # resumes at 20:00), a 7h intraday gap, missing_days=[] either way.
    big = _remove_window(big, date_cls(2024, 6, 21), 13, 20)
    # (b) genuine anomaly, no calendar explanation, still purely intraday
    # (same calendar day) so missing_days stays [].
    big = _remove_window(big, date_cls(2024, 7, 15), 10, 20)
    _write(d, "SYM_2024-06-01_2024-09-01_1h.csv", big)

    small_clean = _continuous_1h(_utc(2024, 8, 1), _utc(2024, 8, 20))
    _write(d, "SYM_2024-08-01_2024-08-20_1h.csv", small_clean)

    chosen = _find_latest_cache(Path(d), "SYM", "_1h.csv", prefer_complete=True)
    assert chosen.name.endswith("2024-09-01_1h.csv"), (
        f"expected the big mostly-clean current cache, got {chosen.name} -- "
        "an isolated intraday anomaly must not lose to a lucky tiny window"
    )
    print("[PASS] mostly-clean current cache beats a tiny lucky-clean window")


def test_genuine_full_day_hole_in_latest_still_loses_to_clean_smaller():
    """Guardrail: a REAL missing weekday in the latest cache must still be
    rejected in favor of a smaller, genuinely clean cache -- the fix above
    must not swallow actual holes, only calendar-explainable ones."""
    d = tempfile.mkdtemp()

    big = _continuous_1h(_utc(2024, 6, 1), _utc(2024, 9, 1))
    big = _remove_window(big, date_cls(2024, 6, 21), 13, 20)  # legitimate, explained
    # Entirely delete an unexplained, unwhitelisted weekday (Mon 2024-07-15) --
    # a genuine hole, not a whitelisted closure and not a pure intraday blip.
    big = [t for t in big if t.date() != date_cls(2024, 7, 15)]
    _write(d, "SYM_2024-06-01_2024-09-01_1h.csv", big)

    small_clean = _continuous_1h(_utc(2024, 8, 1), _utc(2024, 8, 20))
    _write(d, "SYM_2024-08-01_2024-08-20_1h.csv", small_clean)

    chosen = _find_latest_cache(Path(d), "SYM", "_1h.csv", prefer_complete=True)
    assert chosen.name.endswith("2024-08-20_1h.csv"), (
        f"expected the fix to still reject a genuine missing weekday, got {chosen.name}"
    )
    print("[PASS] a genuine missing-weekday hole still loses to a clean smaller cache")


def main():
    tests = [
        test_prefers_clean_older_over_holed_latest_end,
        test_prefer_complete_false_keeps_latest_end,
        test_default_is_prefer_complete,
        test_single_candidate_returned_unchanged,
        test_none_trustworthy_falls_back_to_latest_end,
        test_real_bug_repro_mostly_clean_latest_beats_tiny_lucky_clean_window,
        test_genuine_full_day_hole_in_latest_still_loses_to_clean_smaller,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)
    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)} tests: {', '.join(failures)}")
        sys.exit(1)
    print(f"ALL {len(tests)} _find_latest_cache completeness tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
