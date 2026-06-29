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


def main():
    tests = [
        test_prefers_clean_older_over_holed_latest_end,
        test_prefer_complete_false_keeps_latest_end,
        test_default_is_prefer_complete,
        test_single_candidate_returned_unchanged,
        test_none_trustworthy_falls_back_to_latest_end,
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
