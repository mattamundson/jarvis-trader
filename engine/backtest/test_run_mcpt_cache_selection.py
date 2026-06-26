"""Regression test: run_mcpt._find_cache must select by latest END-date.

Guards against the 2026-06 `sorted(glob)[-1]` loader bug. A bare lexicographic
sort orders by START date, so a later-starting-but-shorter (or older-but-longer)
slice could shadow the freshest cache and feed the bar-permutation MCPT wrong-era
bars. The canonical selector (_gate_v2_helpers._find_latest_cache) keys on the
parsed END-date instead.

Run:  cd engine && .venv/Scripts/python backtest/test_run_mcpt_cache_selection.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import backtest.run_mcpt as rm

_HEADER = "timestamp,open,high,low,close\n"


def test_find_cache_picks_latest_end_date_not_lexicographic():
    """The freshest END-date wins even when it is NOT the lexicographic-last name."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Lexicographic-last by START date = the TRAP (later start, EARLIER end).
        trap = d / "MES_2024-06-01_2025-08-01_1h.csv"
        # Correct pick = latest END date (earlier start, but freshest data).
        correct = d / "MES_2024-01-01_2026-03-28_1h.csv"
        trap.write_text(_HEADER)
        correct.write_text(_HEADER)

        rm.CACHE_DIR = d
        chosen = rm._find_cache("MES")
        assert chosen is not None and chosen.name == correct.name, (
            f"Expected {correct.name!r} (latest end-date), got "
            f"{chosen.name if chosen else None!r}. A bare sorted(glob)[-1] would "
            f"wrongly pick {trap.name!r} (lexicographic-last by start date)."
        )
    print("[PASS] _find_cache picks latest end-date, not lexicographic-last.")


def test_find_cache_prefers_real_over_sample():
    """A real cache must beat a SAMPLE_ plumbing file."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "SAMPLE_MES_2024-01-01_2024-12-31_1h.csv").write_text(_HEADER)
        real = d / "MES_2024-01-01_2026-03-28_1h.csv"
        real.write_text(_HEADER)
        rm.CACHE_DIR = d
        chosen = rm._find_cache("MES")
        assert chosen is not None and chosen.name == real.name, (
            f"Expected REAL cache {real.name!r} over SAMPLE, got "
            f"{chosen.name if chosen else None!r}."
        )
    print("[PASS] _find_cache prefers real cache over SAMPLE_.")


def test_find_cache_falls_back_to_sample():
    """With no real cache, the SAMPLE_ plumbing file is returned."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sample = d / "SAMPLE_MES_2024-01-01_2024-12-31_1h.csv"
        sample.write_text(_HEADER)
        rm.CACHE_DIR = d
        chosen = rm._find_cache("MES")
        assert chosen is not None and chosen.name == sample.name, (
            f"Expected SAMPLE fallback {sample.name!r}, got "
            f"{chosen.name if chosen else None!r}."
        )
    print("[PASS] _find_cache falls back to SAMPLE_ when no real cache exists.")


def test_find_cache_returns_none_when_empty():
    """No cache of any kind -> None (caller prints a 'no cache' message)."""
    with tempfile.TemporaryDirectory() as tmp:
        rm.CACHE_DIR = Path(tmp)
        assert rm._find_cache("MES") is None
    print("[PASS] _find_cache returns None when no cache exists.")


def main():
    tests = [
        test_find_cache_picks_latest_end_date_not_lexicographic,
        test_find_cache_prefers_real_over_sample,
        test_find_cache_falls_back_to_sample,
        test_find_cache_returns_none_when_empty,
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
    print(f"ALL {len(tests)} run_mcpt cache-selection tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
