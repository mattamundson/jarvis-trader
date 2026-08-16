"""
JARVIS TRADER — Fast Cache Loader (Polars-backed, drop-in for pd.read_csv)

Speeds up the backtest data hot path. Every runner's `_load_data()` does
`pd.read_csv` + datetime-parse + set_index on the cached OHLCV CSVs. Polars
reads CSVs 5-10x faster than pandas on typical bar counts, which matters
when a WFO campaign loads the same 12k-100k-row frame dozens of times
(IS grid + OOS windows + fixed-params + cost sweep).

This module provides:
    load_cache_fast(path) -> pd.DataFrame
        Reads a cache CSV with Polars, normalizes to the EXACT contract the
        runners expect (lowercase columns, timestamp->index, sorted).

    benchmark_loads(path)
        Head-to-head pandas vs polars timing on a real cache file.

Usage (drop-in):
    from backtest.cache_loader_polars import load_cache_fast
    df = load_cache_fast(data_file)   # same shape as pd.read_csv path

ArcticDB note: polars is the zero-install first step (already present in the
engine env). The loader seam is designed so ArcticDB can replace the CSV
source later without touching runner code.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import polars as pl

    _HAS_POLARS = True
except ImportError:  # pragma: no cover
    _HAS_POLARS = False


def load_cache_fast(path: Path | str, verbose: bool = False) -> pd.DataFrame:
    """Read a cache CSV with Polars and return the runner-standard DataFrame.

    Output contract (identical to `_load_data` in the runners):
        - lowercase column names
        - DatetimeIndex named timestamp (falls back to 'datetime' if that's
          the source column)
        - sorted ascending
        - columns: open, high, low, close, volume (+ any extras)

    Falls back to pandas read_csv if polars is unavailable or the file has
    a shape polars can't parse (e.g. malformed rows) — never breaks a run.
    """
    path = Path(path)
    if not _HAS_POLARS:
        return _load_pandas(path, verbose=verbose)

    try:
        lf = pl.read_csv(path)
    except Exception as exc:
        if verbose:
            print(f"[FastCache] polars read failed ({exc}); falling back to pandas")
        return _load_pandas(path, verbose=verbose)

    # Normalize to the runner contract
    lf = lf.rename({c: c.lower() for c in lf.columns})
    ts_col = "timestamp" if "timestamp" in lf.columns else "datetime"
    if ts_col not in lf.columns:
        # Polars may infer a non-string col name; search case-insensitively
        lower_map = {c.lower(): c for c in lf.columns}
        ts_col = "timestamp" if "timestamp" in lower_map else "datetime"
        actual = lower_map.get(ts_col)
        if actual is None:
            return _load_pandas(path, verbose=verbose)
        lf = lf.rename({actual: ts_col})

    lf = lf.with_columns(
        pl.col(ts_col).str.to_datetime(time_unit="us", strict=False).alias(ts_col)
    )
    df = lf.to_pandas()
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    return df


def _load_pandas(path: Path, verbose: bool = False) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    return df


def benchmark_loads(path: Path | str, repeats: int = 3) -> dict:
    """Time pandas vs polars on the same cache file; returns timing dict."""
    path = Path(path)
    pandas_times: list[float] = []
    polars_times: list[float] = []

    for _ in range(repeats):
        t0 = time.perf_counter()
        _load_pandas(path)
        pandas_times.append(time.perf_counter() - t0)

    if _HAS_POLARS:
        for _ in range(repeats):
            t0 = time.perf_counter()
            load_cache_fast(path)
            polars_times.append(time.perf_counter() - t0)

    result = {
        "file": path.name,
        "pandas_mean_s": float(np.mean(pandas_times)),
        "polars_mean_s": float(np.mean(polars_times)) if polars_times else None,
        "speedup_x": (
            float(np.mean(pandas_times) / np.mean(polars_times))
            if polars_times
            else None
        ),
    }
    print(
        f"[FastCache] {path.name}: pandas {result['pandas_mean_s']:.3f}s | "
        f"polars {result['polars_mean_s']:.3f}s"
        + (f" | speedup {result['speedup_x']:.1f}x" if result["speedup_x"] else "")
    )
    return result


if __name__ == "__main__":
    import glob
    import sys

    cache_dir = Path(__file__).parent / "cache"
    files = sorted(glob.glob(str(cache_dir / "*_1h.csv")))
    if not files:
        print("No cache files found")
        sys.exit(0)
    # Benchmark the widest MES + MGC files (the hot ones for the runners)
    target = None
    for f in files:
        if ("MES" in f or "MGC" in f) and "1h" in f:
            if target is None or Path(f).stat().st_size > Path(target).stat().st_size:
                target = f
    if target:
        benchmark_loads(target)
    else:
        print("No MES/MGC 1h cache found for benchmark")
