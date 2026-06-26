"""Tests for the pre-holiday DARK forward paper-shadow (observe-only).

Synthetic daily OHLC with engineered holiday gaps + a tmp ledger dir -- no network,
no live state. Verifies the gap-based pre-holiday mask, the inception boundary (only
strictly-forward pre-holiday days count), idempotency, and the report accumulation gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import preholiday_paper_track as pht


def _daily_bars(
    start: str, end: str, holidays: list[str] | None = None, *, seed: int = 0
) -> pd.DataFrame:
    """Business days between start/end with `holidays` dropped (creating pre-holiday gaps)."""
    days = pd.bdate_range(start, end)
    drop = {pd.Timestamp(h) for h in (holidays or [])}
    days = pd.DatetimeIndex([d for d in days if d not in drop])
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


def test_mask_identifies_day_before_gap():
    # Drop Wed 2025-02-19 -> Tue 2025-02-18 precedes an abnormal gap (pre-holiday).
    idx = pd.DatetimeIndex(
        [d for d in pd.bdate_range("2025-02-10", "2025-02-28") if d != pd.Timestamp("2025-02-19")]
    )
    mask = pht.mask_pre_holiday(idx)
    flagged = {str(d.date()) for d, m in zip(idx, mask, strict=True) if m}
    assert "2025-02-18" in flagged
    # A plain Fri->Mon weekend gap is NOT flagged.
    assert "2025-02-14" not in flagged  # Fri before a normal weekend


def test_first_run_sets_inception_records_no_forward(tmp_path):
    df = _daily_bars("2025-01-01", "2025-02-28", holidays=["2025-01-20"])
    res = pht.run_once(df, track_base=tmp_path)
    assert res["recorded"] == 0  # nothing is forward yet on inception
    state = pht._load_state(pht._track_dir(tmp_path))
    assert state["inception_date"] is not None


def test_forward_preholiday_recorded_after_inception(tmp_path):
    pht.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    # Extend into March with a mid-week holiday -> the day before it is a forward pre-holiday.
    res2 = pht.run_once(
        _daily_bars("2025-01-01", "2025-03-31", holidays=["2025-03-12"]), track_base=tmp_path
    )
    assert res2["recorded"] >= 1
    recs = pht.load_records(tmp_path)
    assert all(r["date"] > res2["inception"] for r in recs)
    assert any(r["date"] == "2025-03-11" for r in recs)  # Tue before dropped Wed


def test_run_once_is_idempotent(tmp_path):
    pht.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    df = _daily_bars("2025-01-01", "2025-03-31", holidays=["2025-03-12"])
    pht.run_once(df, track_base=tmp_path)
    n1 = len(pht.load_records(tmp_path))
    pht.run_once(df, track_base=tmp_path)  # same data again
    n2 = len(pht.load_records(tmp_path))
    assert n1 == n2  # no double-recording


def test_report_empty_is_accumulating(tmp_path):
    pht.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    out = pht.report(tmp_path)
    assert out["forward_n"] == 0
    assert out["status"] == "ACCUMULATING"


def test_report_with_records_computes_stats(tmp_path):
    pht.run_once(_daily_bars("2025-01-01", "2025-02-28"), track_base=tmp_path)
    pht.run_once(
        _daily_bars(
            "2025-01-01",
            "2025-09-30",
            holidays=["2025-03-12", "2025-05-21", "2025-07-09", "2025-09-10"],
        ),
        track_base=tmp_path,
    )
    out = pht.report(tmp_path)
    assert out["forward_n"] > 0
    assert "sharpe_net" in out and "mean_bps_net" in out
    assert out["status"].startswith("ACCUMULATING") or out["status"] == "GRADED"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
