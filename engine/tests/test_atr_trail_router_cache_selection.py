"""Regression test: GET /backtest/atr-trail/trades must pick the cache file by
parsed date range (via _pick_cache_file), not by raw mtime.

Picking by mtime silently prefers whichever file was touched last -- a short,
recently-refreshed recent-tail file would win over a longer, older-mtime
full-history file even though the page presents the result as "full period,
all trades" (see docs/runbooks/ATR_TRAIL_VISUALIZER.md and
run_atr_trail_bounce.py's _pick_cache_file, which this endpoint must reuse).
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CACHE_DIR = Path(__file__).resolve().parent.parent / "backtest" / "cache"
SYMBOL = "ZZTESTPICK"


def _write_csv(path: Path, n_bars: int, start: str, mtime_offset_s: float) -> None:
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n_bars))
    idx = pd.date_range(start, periods=n_bars, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        }
    )
    df.to_csv(path, index=False)
    now = time.time()
    os.utime(path, (now + mtime_offset_s, now + mtime_offset_s))


@pytest.fixture
def conflicting_cache_files():
    """A long, older-mtime, later-end-date file vs a short, newer-mtime,
    earlier-end-date file -- the two selection strategies must disagree."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    long_path = CACHE_DIR / f"{SYMBOL}_2025-01-01_2026-06-01_5m.csv"
    short_path = CACHE_DIR / f"{SYMBOL}_2026-05-01_2026-05-15_5m.csv"
    try:
        # Long file: touched FIRST (older mtime) but covers far more bars and
        # ends later -- this is the one _pick_cache_file must choose.
        _write_csv(long_path, n_bars=4000, start="2025-01-01", mtime_offset_s=-100)
        # Short file: touched LAST (newest mtime) -- a naive max(mtime) pick
        # would wrongly choose this one.
        _write_csv(short_path, n_bars=50, start="2026-05-01", mtime_offset_s=0)
        yield long_path, short_path
    finally:
        long_path.unlink(missing_ok=True)
        short_path.unlink(missing_ok=True)


def test_endpoint_picks_by_date_range_not_mtime(conflicting_cache_files):
    from routers.backtest_router import get_atr_trail_trades

    long_path, short_path = conflicting_cache_files
    assert short_path.stat().st_mtime > long_path.stat().st_mtime  # sanity check

    result = asyncio.run(
        get_atr_trail_trades(symbol=SYMBOL, timeframe="5m", period=5, factor=3.5, max_points=3000)
    )
    assert result["source_file"] == long_path.name
    assert result["bars"] == 4000
