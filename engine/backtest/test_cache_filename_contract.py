"""
Cache filename contract unit tests — P3-2.

Tests the CACHE_FILENAME_CONTRACT regex defined in export_ibkr_history.py
and the _find_latest_cache() selector in _gate_v2_helpers.py.

CONTRACT (summary):
    <SYMBOL>_<START_DATE>_<END_DATE>_<INTERVAL>.csv
      SYMBOL   : 2-4 uppercase alphanumeric chars starting with A-Z
      START/END: ISO YYYY-MM-DD
      INTERVAL : 1-2 digit integer + 'm', 'h', or 'd'  (e.g. 5m, 15m, 1h, 4h, 1d)

Run:  cd engine && .venv/Scripts/python backtest/test_cache_filename_contract.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from backtest._gate_v2_helpers import _find_latest_cache
from backtest.export_ibkr_history import CACHE_FILENAME_CONTRACT

# ---------------------------------------------------------------------------
# Regex acceptance tests
# ---------------------------------------------------------------------------

VALID_FILENAMES = [
    "MES_2024-01-01_2026-03-28_1h.csv",
    "MGC_2024-01-01_2026-05-07_1h.csv",
    "MCL_2022-06-01_2026-04-30_1d.csv",
    "MNQ_2024-01-01_2026-03-28_4h.csv",
    "M2K_2023-01-01_2025-12-31_1d.csv",
    "MES_2020-01-01_2024-01-01_1d.csv",
    "MES_2024-06-01_2026-03-28_5m.csv",  # 'm' accepted since 2026-06-16 (5m/15m history)
    "MNQ_2024-06-01_2026-03-28_15m.csv",
]

INVALID_FILENAMES = [
    "mes_2024-01-01_2026-03-28_1h.csv",  # lowercase symbol
    "MES_20240101_20260328_1h.csv",  # non-ISO dates (no hyphens)
    "MES_2024-01-01_2026-03-28_1H.csv",  # uppercase interval
    "MES_2024-01-01_2026-03-28.csv",  # missing interval segment
    "MES_2024-01-01_2026-03-28_1h",  # missing .csv extension
    "MES_2024-01-01_1h.csv",  # missing end-date segment
    "_MES_2024-01-01_2026-03-28_1h.csv",  # leading underscore
    "MESAS_2024-01-01_2026-03-28_1h.csv",  # 5-char symbol
    "MES_2024-01-01_2026-03-28_100h.csv",  # 3-digit interval
]


def test_regex_accepts_valid():
    failures = []
    for name in VALID_FILENAMES:
        if not CACHE_FILENAME_CONTRACT.match(name):
            failures.append(f"  REJECTED (should accept): {name}")
    if failures:
        raise AssertionError("Regex rejected valid filename(s):\n" + "\n".join(failures))
    print(f"[PASS] Regex accepts {len(VALID_FILENAMES)} valid filenames.")


def test_regex_rejects_invalid():
    failures = []
    for name in INVALID_FILENAMES:
        if CACHE_FILENAME_CONTRACT.match(name):
            failures.append(f"  ACCEPTED (should reject): {name}")
    if failures:
        raise AssertionError("Regex accepted invalid filename(s):\n" + "\n".join(failures))
    print(f"[PASS] Regex rejects {len(INVALID_FILENAMES)} invalid filenames.")


# ---------------------------------------------------------------------------
# _find_latest_cache selector tests
# ---------------------------------------------------------------------------


def test_find_latest_cache_picks_newest_end_date():
    """Selector must pick the file with the latest end-date, not largest file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        # Create files with different end dates — newest end-date wins.
        older = d / "MES_2024-01-01_2025-12-31_1h.csv"
        newer = d / "MES_2024-01-01_2026-03-28_1h.csv"
        newest = d / "MES_2024-01-01_2026-05-07_1h.csv"
        for f in (oldest := older, newer, newest):
            f.write_text("timestamp,open,high,low,close,volume\n")

        result = _find_latest_cache(d, "MES", "_1h.csv")
        assert result.name == newest.name, (
            f"Expected {newest.name!r}, got {result.name!r}. "
            "Selector should pick latest end-date regardless of file order."
        )
    print("[PASS] _find_latest_cache picks newest end-date.")


def test_find_latest_cache_different_intervals():
    """Suffix filter must only match files with the requested interval."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        hourly = d / "MES_2024-01-01_2026-05-07_1h.csv"
        daily = d / "MES_2022-01-01_2026-05-07_1d.csv"
        hourly.write_text("h")
        daily.write_text("d")

        result_h = _find_latest_cache(d, "MES", "_1h.csv")
        result_d = _find_latest_cache(d, "MES", "_1d.csv")
        assert result_h.name == hourly.name, f"Expected {hourly.name}, got {result_h.name}"
        assert result_d.name == daily.name, f"Expected {daily.name}, got {result_d.name}"
    print("[PASS] _find_latest_cache filters by interval suffix correctly.")


def test_find_latest_cache_raises_on_missing():
    """FileNotFoundError when no matching file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        try:
            _find_latest_cache(d, "MES", "_1h.csv")
            raise AssertionError("Should have raised FileNotFoundError")
        except FileNotFoundError:
            pass
    print("[PASS] _find_latest_cache raises FileNotFoundError on empty directory.")


def test_find_latest_cache_off_contract_falls_to_bottom():
    """Off-contract files never beat a contract-conforming sibling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        conforming = d / "MES_2024-01-01_2026-03-28_1h.csv"
        off_contract = d / "MES_latest_1h.csv"  # violates 3-segment split
        conforming.write_text("ok")
        off_contract.write_text("bad")

        result = _find_latest_cache(d, "MES", "_1h.csv")
        assert result.name == conforming.name, f"Off-contract file won selection: {result.name!r}"
    print("[PASS] Off-contract files don't beat contract-conforming siblings.")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main():
    tests = [
        test_regex_accepts_valid,
        test_regex_rejects_invalid,
        test_find_latest_cache_picks_newest_end_date,
        test_find_latest_cache_different_intervals,
        test_find_latest_cache_raises_on_missing,
        test_find_latest_cache_off_contract_falls_to_bottom,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)

    print(f"\n{'='*60}")
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)} tests: {', '.join(failures)}")
        sys.exit(1)
    else:
        print(f"ALL {len(tests)} cache filename contract tests PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
