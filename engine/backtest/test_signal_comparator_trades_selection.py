"""Regression test: signal_comparator picks the freshest *trades* file.

Guards the D2 loader bug. The fallback glob `{symbol}_{tf}_*.json` is broad and
also matches non-trade artifacts (sensitivity, optimal_params, monte_carlo,
regime_analysis). A bare `sorted(matches)[-1]` (lexicographic) can return one of
those structurally-wrong files, or a stale one. The fix selects the most-recently
-modified file that actually contains a trades array.

Run:  cd engine && .venv/Scripts/python backtest/test_signal_comparator_trades_selection.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")

from backtest.signal_comparator import _file_has_trades, _pick_latest_trades_file


def _write(path: Path, obj: dict, mtime: float) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_picks_trades_file_over_newer_artifact():
    """A newer non-trade artifact must NOT shadow an older real trades file."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        base = time.time()
        # Older file WITH trades (the correct answer).
        trades = _write(
            d / "MES_1h_2024-06-01_2026-03-27.json",
            {"trades": [{"entry_date": "2025-01-01"}]},
            base - 100,
        )
        # NEWER artifacts WITHOUT trades — these would win on mtime or lexicographic sort.
        _write(d / "MES_1h_sensitivity.json", {"sensitivity": {"x": 1}}, base)
        _write(d / "MES_1h_optimal_params.json", {"params": {"fast": 60}}, base + 10)

        chosen = _pick_latest_trades_file(list(d.glob("MES_1h_*.json")))
        assert chosen is not None and chosen.name == trades.name, (
            f"Expected the real trades file {trades.name!r}, got "
            f"{chosen.name if chosen else None!r}. A non-trade artifact won selection."
        )
    print("[PASS] picks the real trades file over newer non-trade artifacts.")


def test_picks_most_recent_among_trades_files():
    """Among multiple genuine trades files, the freshest by mtime wins."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        base = time.time()
        _write(
            d / "MES_1h_2024-06-01_2025-12-31.json",
            {"trades": [{"entry_date": "2025-06-01"}]},
            base - 50,
        )
        newer = _write(
            d / "MES_1h_2024-06-01_2026-03-27.json",
            {"full_metrics": {"trades": [{"entry_date": "2026-01-01"}]}},
            base,
        )
        chosen = _pick_latest_trades_file(list(d.glob("MES_1h_*.json")))
        assert chosen is not None and chosen.name == newer.name, (
            f"Expected freshest trades file {newer.name!r}, got "
            f"{chosen.name if chosen else None!r}."
        )
    print("[PASS] picks the most recent among genuine trades files.")


def test_returns_none_when_no_trades_files():
    """Only artifacts present -> None (caller logs 'no backtest found')."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        base = time.time()
        _write(d / "MES_1h_sensitivity.json", {"sensitivity": {}}, base)
        _write(d / "MES_1h_monte_carlo.json", {"mc": {}}, base + 5)
        chosen = _pick_latest_trades_file(list(d.glob("MES_1h_*.json")))
        assert chosen is None, f"Expected None, got {chosen!r}"
    print("[PASS] returns None when no file contains trades.")


def test_file_has_trades_detects_all_shapes():
    """_file_has_trades recognizes trades, trades_list, and full_metrics.trades."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        base = time.time()
        a = _write(d / "a.json", {"trades": [{"entry_date": "x"}]}, base)
        b = _write(d / "b.json", {"trades_list": [{"entry_date": "x"}]}, base)
        c = _write(d / "c.json", {"full_metrics": {"trades": [{"entry_date": "x"}]}}, base)
        empty = _write(d / "empty.json", {"trades": []}, base)
        bad = d / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert _file_has_trades(a) and _file_has_trades(b) and _file_has_trades(c)
        assert not _file_has_trades(empty), "empty trades array must be False"
        assert not _file_has_trades(bad), "unparseable file must be False, not raise"
    print("[PASS] _file_has_trades detects all trade shapes and rejects empty/bad.")


def main():
    tests = [
        test_picks_trades_file_over_newer_artifact,
        test_picks_most_recent_among_trades_files,
        test_returns_none_when_no_trades_files,
        test_file_has_trades_detects_all_shapes,
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
    print(f"ALL {len(tests)} signal_comparator trades-selection tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
