"""Tests for the turn-of-month DARK forward paper-shadow (observe-only).

Synthetic daily OHLC + a tmp ledger dir — no network, no live state. Verifies the
inception boundary (only strictly-forward TOM days count), idempotency, and the
report accumulation/grading gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import tom_paper_track as tpt


def _daily_bars(start: str, end: str, *, seed: int = 0) -> pd.DataFrame:
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    close = 500 * np.cumprod(1 + rng.normal(0.0004, 0.008, len(days)))
    return pd.DataFrame(
        {
            "date": [str(d.date()) for d in days],
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000_000,
        }
    )


def test_first_run_sets_inception_records_no_forward(tmp_path):
    df = _daily_bars("2025-01-01", "2025-02-28")
    res = tpt.run_once(df, track_base=tmp_path)
    assert res["recorded"] == 0  # nothing is forward yet on inception
    state = tpt._load_state(tpt._track_dir(tmp_path))
    assert state["inception_date"] is not None


def test_forward_tom_days_recorded_after_inception(tmp_path):
    tpt.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    # Extend the series into March -> new TOM days (early-March) are forward.
    res2 = tpt.run_once(_daily_bars("2025-01-01", "2025-03-31"), track_base=tmp_path)
    assert res2["recorded"] >= 3  # ~first 3 trading days of March
    recs = tpt.load_records(tmp_path)
    assert all(r["date"] > res2["inception"] for r in recs)


def test_run_once_is_idempotent(tmp_path):
    tpt.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    df = _daily_bars("2025-01-01", "2025-03-31")
    tpt.run_once(df, track_base=tmp_path)
    n1 = len(tpt.load_records(tmp_path))
    tpt.run_once(df, track_base=tmp_path)  # same data again
    n2 = len(tpt.load_records(tmp_path))
    assert n1 == n2  # no double-recording


def test_report_empty_is_accumulating(tmp_path):
    tpt.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    out = tpt.report(tmp_path)
    assert out["forward_n"] == 0
    assert out["status"] == "ACCUMULATING"


def test_report_with_records_computes_stats(tmp_path):
    tpt.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    tpt.run_once(_daily_bars("2025-01-01", "2025-06-30"), track_base=tmp_path)
    out = tpt.report(tmp_path)
    assert out["forward_n"] > 0
    assert "sharpe_net" in out and "mean_bps_net" in out
    # Short forward span -> not yet enough for a gate verdict.
    assert out["status"].startswith("ACCUMULATING") or out["status"] == "GRADED"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
