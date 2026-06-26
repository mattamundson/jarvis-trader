"""Tests for the bar-cache completeness / gap detector.

WHY THIS EXISTS
---------------
Cache *selection* is now fixed fleet-wide (end-date-keyed `_find_latest_cache`),
but a file with the right name can still be HOLED: the MES 5m cache had ~8 gaps
Aug-Dec 2025 while only ~Dec-2025 -> Jun-2026 was trustworthy. Those holes are
invisible from the filename (the date range looks complete). A backtest run on a
holed slice silently computes a verdict on partial data. This detector inspects
the actual timestamps and surfaces (start, end, duration) for every suspicious
gap plus the largest contiguous trustworthy window.

It must NOT cry wolf on the legitimate gaps every futures series has:
- the daily ~1h CME maintenance break,
- weekends (Fri close -> Sun open),
- optionally, exchange holidays (caller-supplied whitelist).

Run:  cd engine && .venv/Scripts/python backtest/test_cache_completeness.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from backtest.cache_completeness import (
    cadence_minutes_for_interval,
    inspect_cache_file,
    inspect_completeness,
    interval_from_filename,
)


def _utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def _series(start, n, step_minutes):
    """n timestamps starting at `start`, spaced step_minutes apart."""
    return [start + timedelta(minutes=step_minutes * i) for i in range(n)]


def test_interval_parsing():
    assert cadence_minutes_for_interval("5m") == 5
    assert cadence_minutes_for_interval("15m") == 15
    assert cadence_minutes_for_interval("1h") == 60
    assert cadence_minutes_for_interval("1d") == 1440
    print("[PASS] interval -> cadence minutes")


def test_filename_interval_inference():
    assert interval_from_filename("MES_2024-09-22_2026-05-29_5m_cont.csv") == "5m"
    assert interval_from_filename("ES_2025-04-23_2026-06-12_15m_cont.csv") == "15m"
    assert interval_from_filename("CL_2024-06-01_2026-03-27_1h.csv") == "1h"
    assert interval_from_filename("DIA_1998-01-20_2026-06-24_1d.csv") == "1d"
    print("[PASS] filename -> interval")


def test_clean_continuous_series_is_trustworthy():
    """A perfectly 5-min-spaced block has zero gaps and is fully trustworthy."""
    ts = _series(_utc(2026, 1, 5, 14, 30), 200, 5)  # Monday, 200 bars
    r = inspect_completeness(ts, "5m")
    assert r["n_bars"] == 200
    assert r["gaps"] == []
    assert r["n_suspicious_gaps"] == 0
    assert r["trustworthy"] is True
    assert r["trustworthy_window"]["n_bars"] == 200
    print("[PASS] clean series trustworthy, 0 gaps")


def test_daily_maintenance_break_not_suspicious():
    """A ~1h gap (CME maintenance) is below the normal-session-gap floor."""
    day1 = _series(_utc(2026, 1, 5, 14, 30), 50, 5)  # ends 18:35
    # resume ~1h later (maintenance), same calendar day
    day1b = _series(_utc(2026, 1, 5, 19, 35), 50, 5)
    r = inspect_completeness(day1 + day1b, "5m")
    # one gap may be recorded, but it must NOT be suspicious
    assert r["n_suspicious_gaps"] == 0, f"maintenance gap wrongly flagged: {r['gaps']}"
    assert r["trustworthy"] is True
    print("[PASS] ~1h maintenance break not suspicious")


def test_weekend_gap_not_suspicious():
    """Fri-close -> Sun/Mon-open spans a weekend; expected, not suspicious."""
    fri = _series(_utc(2026, 1, 9, 14, 30), 100, 5)  # Friday 2026-01-09
    mon = _series(_utc(2026, 1, 12, 14, 30), 100, 5)  # Monday 2026-01-12
    r = inspect_completeness(fri + mon, "5m")
    assert len(r["gaps"]) == 1
    g = r["gaps"][0]
    assert g["spans_weekend"] is True
    assert g["suspicious"] is False, "a weekend gap must not be suspicious"
    assert r["trustworthy"] is True
    print(f"[PASS] weekend gap not suspicious (dur={g['duration_hours']:.1f}h)")


def test_midweek_multiday_hole_is_suspicious():
    """The MES failure mode: a multi-day mid-week hole with no weekend."""
    tue = _series(_utc(2026, 1, 6, 14, 30), 120, 5)  # Tue 2026-01-06
    # jump to Fri 2026-01-09 -- Wed+Thu missing, no weekend in between
    fri = _series(_utc(2026, 1, 9, 14, 30), 120, 5)
    r = inspect_completeness(tue + fri, "5m")
    sus = [g for g in r["gaps"] if g["suspicious"]]
    assert len(sus) == 1, f"expected 1 suspicious gap, got {r['gaps']}"
    assert sus[0]["spans_weekend"] is False
    assert r["trustworthy"] is False
    # trustworthy window is the larger of the two clean sides (both 120 here)
    assert r["trustworthy_window"]["n_bars"] == 120
    print(f"[PASS] mid-week multi-day hole suspicious (dur={sus[0]['duration_hours']:.1f}h)")


def test_holiday_whitelist_suppresses_suspicion():
    """A mid-week hole whose start date is a known holiday is expected."""
    wed = _series(_utc(2026, 1, 7, 14, 30), 80, 5)  # Wed 2026-01-07
    # Thu 2026-01-08 missing (holiday), resume Fri
    fri = _series(_utc(2026, 1, 9, 14, 30), 80, 5)
    holiday = {datetime(2026, 1, 8).date()}
    r = inspect_completeness(wed + fri, "5m", holiday_dates=holiday)
    assert r["n_suspicious_gaps"] == 0, "whitelisted holiday gap should not be suspicious"
    assert r["trustworthy"] is True
    print("[PASS] holiday whitelist suppresses suspicion")


def test_holiday_close_overnight_gap_suppressed():
    """A holiday CLOSE is a long overnight gap with no full day between (e.g.
    Christmas Eve -> Christmas Day). Keyed on the endpoint date, not a missing
    weekday -> the built-in US_MARKET_HOLIDAYS set must suppress it."""
    from backtest.cache_completeness import US_MARKET_HOLIDAYS

    eve = _series(_utc(2025, 12, 24, 14, 30), 46, 5)  # ends ~18:15, Dec 24
    xmas = _series(_utc(2025, 12, 25, 23, 0), 60, 5)  # resumes Dec 25 23:00
    # without the calendar, the ~28h gap is flagged:
    naive = inspect_completeness(eve + xmas, "5m")
    assert naive["n_suspicious_gaps"] == 1
    # with the calendar, the holiday close is explained:
    r = inspect_completeness(eve + xmas, "5m", holiday_dates=US_MARKET_HOLIDAYS)
    assert r["n_suspicious_gaps"] == 0, f"holiday close not suppressed: {r['gaps']}"
    assert r["trustworthy"] is True
    print("[PASS] holiday overnight close suppressed by US_MARKET_HOLIDAYS")


def test_trustworthy_window_picks_larger_clean_side():
    """With a suspicious hole, the trustworthy window is the larger clean span."""
    small = _series(_utc(2026, 2, 3, 14, 30), 30, 5)  # Tue, 30 bars
    # multi-day mid-week hole
    big = _series(_utc(2026, 2, 6, 14, 30), 300, 5)  # Fri, 300 bars
    r = inspect_completeness(small + big, "5m")
    assert r["trustworthy"] is False
    win = r["trustworthy_window"]
    assert win["n_bars"] == 300
    assert win["start"] == big[0]
    assert win["end"] == big[-1]
    print(f"[PASS] trustworthy window = larger clean side ({win['n_bars']} bars)")


def test_degenerate_inputs_default_deny():
    """Empty / single-bar series can't be validated -> default-deny trust."""
    assert inspect_completeness([], "5m")["trustworthy"] is False
    assert inspect_completeness([_utc(2026, 1, 5)], "5m")["trustworthy"] is False
    print("[PASS] degenerate input default-denies trust")


def test_unsorted_input_is_sorted_first():
    """Out-of-order timestamps are sorted before gap analysis (no false gaps)."""
    ts = _series(_utc(2026, 1, 5, 14, 30), 50, 5)
    shuffled = ts[25:] + ts[:25]
    r = inspect_completeness(shuffled, "5m")
    assert r["n_suspicious_gaps"] == 0
    assert r["trustworthy"] is True
    print("[PASS] unsorted input sorted before analysis")


def test_inspect_cache_file_roundtrip(tmp_path_str=None):
    """The file wrapper reads a CSV, infers interval from the name, and reports."""
    import os
    import tempfile

    d = tempfile.mkdtemp()
    fp = os.path.join(d, "MES_2026-01-05_2026-01-09_5m_cont.csv")
    rows = ["timestamp,open,high,low,close,volume"]
    # clean Monday block then a multi-day mid-week hole then Friday
    mon = _series(_utc(2026, 1, 5, 14, 30), 60, 5)
    fri = _series(_utc(2026, 1, 9, 14, 30), 60, 5)
    for t in mon + fri:
        rows.append(f"{t.isoformat()},1,1,1,1,1")
    with open(fp, "w") as fh:
        fh.write("\n".join(rows) + "\n")

    r = inspect_cache_file(fp)
    assert r["interval"] == "5m"
    assert r["n_bars"] == 120
    assert r["trustworthy"] is False  # Tue-Thu hole, no weekend
    assert r["file"].endswith("MES_2026-01-05_2026-01-09_5m_cont.csv")
    print("[PASS] inspect_cache_file roundtrip detects the hole")


def test_scan_directory_sorts_holed_first_and_skips_unnamed():
    """scan_directory inspects every interval-named cache, skips files with no
    interval token, and sorts untrustworthy caches first."""
    import os
    import tempfile

    from backtest.cache_completeness import scan_directory

    d = tempfile.mkdtemp()

    def _write(name, stamps):
        fp = os.path.join(d, name)
        rows = ["timestamp,open,high,low,close,volume"]
        for t in stamps:
            rows.append(f"{t.isoformat()},1,1,1,1,1")
        with open(fp, "w") as fh:
            fh.write("\n".join(rows) + "\n")

    # clean 5m cache
    _write("MES_2026-01-05_2026-01-05_5m_cont.csv", _series(_utc(2026, 1, 5, 14, 30), 80, 5))
    # holed 5m cache (Tue -> Fri mid-week hole)
    _write(
        "ES_2026-01-06_2026-01-09_5m_cont.csv",
        _series(_utc(2026, 1, 6, 14, 30), 60, 5) + _series(_utc(2026, 1, 9, 14, 30), 60, 5),
    )
    # no interval token -> must be skipped
    _write("DIA_daily.csv", _series(_utc(2026, 1, 5, 14, 30), 5, 1440))

    rows = scan_directory(d)
    assert len(rows) == 2, f"expected 2 interval-named caches, got {[r['file'] for r in rows]}"
    # untrustworthy sorts first
    assert rows[0]["trustworthy"] is False and "ES_" in rows[0]["file"]
    assert rows[1]["trustworthy"] is True and "MES_" in rows[1]["file"]
    print("[PASS] scan_directory sorts holed-first, skips unnamed caches")


def _make_picker_dir():
    """A clean older-end cache (A) and a holed later-end cache (B) for the picker."""
    import os
    import tempfile

    d = tempfile.mkdtemp()

    def _write(name, stamps):
        fp = os.path.join(d, name)
        rows = ["timestamp,open,high,low,close,volume"]
        for t in stamps:
            rows.append(f"{t.isoformat()},1,1,1,1,1")
        with open(fp, "w") as fh:
            fh.write("\n".join(rows) + "\n")

    # A: clean continuous 5m, Mon 2026-01-05 -> Fri 2026-01-09 (1440 bars), end 01-09
    a = [_utc(2026, 1, 5) + timedelta(minutes=5 * i) for i in range(288 * 5)]
    _write("SYM_2026-01-05_2026-01-09_5m_cont.csv", a)
    # B: later end (01-16) but HOLED -- Jan 7+8 deleted (unexplained weekdays)
    b = [
        t
        for t in (_utc(2026, 1, 5) + timedelta(minutes=5 * i) for i in range(288 * 12))
        if t.date() not in (datetime(2026, 1, 7).date(), datetime(2026, 1, 8).date())
    ]
    _write("SYM_2026-01-05_2026-01-16_5m_cont.csv", b)
    return d


def test_picker_prefers_complete_over_holed_latest_end():
    """Required window in the early range -> pick clean A, NOT the holed later B."""
    from datetime import date

    from backtest.cache_completeness import find_trustworthy_cache

    d = _make_picker_dir()
    r = find_trustworthy_cache(
        d, "SYM", required_start=date(2026, 1, 5), required_end=date(2026, 1, 9)
    )
    assert r["path"].endswith("2026-01-09_5m_cont.csv"), r["path"]
    assert r["fallback"] is False
    assert r["latest_end_path"].endswith("2026-01-16_5m_cont.csv")
    print("[PASS] picker prefers complete cache over holed latest-end")


def test_picker_uses_latest_when_only_it_covers():
    """Window in the late range only B covers -> pick B."""
    from datetime import date

    from backtest.cache_completeness import find_trustworthy_cache

    d = _make_picker_dir()
    r = find_trustworthy_cache(
        d, "SYM", required_start=date(2026, 1, 12), required_end=date(2026, 1, 16)
    )
    assert r["path"].endswith("2026-01-16_5m_cont.csv"), r["path"]
    assert r["fallback"] is False
    print("[PASS] picker uses latest-end when only it covers the window")


def test_picker_falls_back_when_none_cover():
    """A window nobody covers -> fallback to latest-end, flagged."""
    from datetime import date

    from backtest.cache_completeness import find_trustworthy_cache

    d = _make_picker_dir()
    r = find_trustworthy_cache(
        d, "SYM", required_start=date(2025, 1, 1), required_end=date(2025, 1, 3)
    )
    assert r["fallback"] is True
    assert r["path"].endswith("2026-01-16_5m_cont.csv")
    print("[PASS] picker falls back (flagged) when no cache covers the window")


def test_picker_no_window_picks_latest_clean():
    """No required window -> the latest-end FULLY-trustworthy cache (A, not holed B)."""
    from backtest.cache_completeness import find_trustworthy_cache

    d = _make_picker_dir()
    r = find_trustworthy_cache(d, "SYM")
    assert r["path"].endswith("2026-01-09_5m_cont.csv"), r["path"]
    assert r["fallback"] is False
    print("[PASS] picker (no window) picks latest fully-trustworthy cache")


def test_picker_raises_when_no_match():
    import tempfile

    from backtest.cache_completeness import find_trustworthy_cache

    try:
        find_trustworthy_cache(tempfile.mkdtemp(), "NOPE")
    except FileNotFoundError:
        print("[PASS] picker raises FileNotFoundError when no cache matches")
        return
    raise AssertionError("expected FileNotFoundError")


def main():
    tests = [
        test_interval_parsing,
        test_filename_interval_inference,
        test_clean_continuous_series_is_trustworthy,
        test_daily_maintenance_break_not_suspicious,
        test_weekend_gap_not_suspicious,
        test_midweek_multiday_hole_is_suspicious,
        test_holiday_whitelist_suppresses_suspicion,
        test_holiday_close_overnight_gap_suppressed,
        test_trustworthy_window_picks_larger_clean_side,
        test_degenerate_inputs_default_deny,
        test_unsorted_input_is_sorted_first,
        test_inspect_cache_file_roundtrip,
        test_scan_directory_sorts_holed_first_and_skips_unnamed,
        test_picker_prefers_complete_over_holed_latest_end,
        test_picker_uses_latest_when_only_it_covers,
        test_picker_falls_back_when_none_cover,
        test_picker_no_window_picks_latest_clean,
        test_picker_raises_when_no_match,
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
    print(f"ALL {len(tests)} cache-completeness tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
