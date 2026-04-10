"""
JARVIS TRADER — Parquet Data Cache
Smart caching with gap detection, incremental fetching, and deduplication.
Inspired by rv64m/autotrade's parquet pipeline.

5-10x smaller than CSV, 50x faster reads, preserves dtypes.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

CACHE_DIR = Path(__file__).parent.parent / "backtest" / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def cache_path(symbol: str, interval: str) -> Path:
    """Canonical parquet cache path for a symbol/interval pair."""
    safe = f"{symbol.upper()}_{interval}".replace("/", "_")
    return CACHE_DIR / f"{safe}.parquet"


def read_cache(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """Read cached parquet file. Returns None if not found."""
    path = cache_path(symbol, interval)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            if "timestamp" in df.columns:
                df = df.set_index(pd.to_datetime(df["timestamp"]))
            else:
                return None
        df = df.sort_index()
        return df
    except Exception:
        return None


def write_cache(symbol: str, interval: str, df: pd.DataFrame) -> None:
    """Write DataFrame to parquet cache."""
    path = cache_path(symbol, interval)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    except Exception as e:
        print(f"[ParquetCache] Write failed (non-fatal): {e}")


def get_cached_range(
    symbol: str, interval: str, start: str, end: str
) -> Optional[pd.DataFrame]:
    """
    Return cached data if it fully covers [start, end].
    Returns None if cache doesn't exist or has gaps.
    """
    df = read_cache(symbol, interval)
    if df is None or df.empty:
        return None

    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)

    # Normalize tz if needed
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    cache_start = df.index.min()
    cache_end = df.index.max()

    # Allow 3-day tolerance on end (weekends, holidays)
    if cache_start <= start_dt and cache_end >= end_dt - pd.Timedelta(days=3):
        return df.loc[start_dt:end_dt]

    return None


def find_gaps(
    symbol: str, interval: str, start: str, end: str
) -> List[Tuple[str, str]]:
    """
    Find date ranges NOT covered by the cache.
    Returns list of (gap_start, gap_end) tuples.
    """
    df = read_cache(symbol, interval)
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)

    if df is None or df.empty:
        return [(start, end)]

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    cache_start = df.index.min()
    cache_end = df.index.max()

    gaps: List[Tuple[str, str]] = []

    # Gap before cache
    if start_dt < cache_start:
        gaps.append((start, str(cache_start.date())))

    # Gap after cache
    if end_dt > cache_end + pd.Timedelta(days=1):
        gaps.append((str(cache_end.date()), end))

    return gaps


def merge_and_store(
    symbol: str, interval: str, new_data: pd.DataFrame
) -> pd.DataFrame:
    """
    Merge new data with existing cache, deduplicate, validate, and save.
    Returns the merged DataFrame.
    """
    existing = read_cache(symbol, interval)

    if existing is not None and not existing.empty:
        # Normalize timezone on both
        if existing.index.tz is not None:
            existing.index = existing.index.tz_localize(None)
        if new_data.index.tz is not None:
            new_data.index = new_data.index.tz_localize(None)

        combined = pd.concat([existing, new_data])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
    else:
        combined = new_data.copy()
        if combined.index.tz is not None:
            combined.index = combined.index.tz_localize(None)
        combined = combined.sort_index()

    # Validate: no NaN close prices, monotonic index
    if "close" in combined.columns:
        combined = combined.dropna(subset=["close"])

    write_cache(symbol, interval, combined)
    return combined


def migrate_csv_to_parquet(csv_path: Path, symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """
    One-time migration: read a CSV cache file and save as parquet.
    Returns the DataFrame if successful.
    """
    try:
        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "timestamp"})
        if "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"]))
            df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
        df = df.sort_index()

        write_cache(symbol, interval, df)
        return df
    except Exception as e:
        print(f"[ParquetCache] CSV migration failed: {e}")
        return None
