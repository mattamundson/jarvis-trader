"""Bar-data loading for the factory.

Reuses the canonical end-date-keyed cache picker (`_find_latest_cache`) so the
factory always reads the freshest IBKR pull. Bar CSVs are gitignored, so they
live only in the primary checkout's cache; the factory points at it read-only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest._gate_v2_helpers import _find_latest_cache

# Contract specs the factory needs to size + cost futures backtests.
# multiplier = $ per point; tick = min price increment.
CONTRACT_SPECS: dict[str, dict] = {
    "MES": {"multiplier": 5.0, "tick": 0.25},
    "ES": {"multiplier": 50.0, "tick": 0.25},
    "MNQ": {"multiplier": 2.0, "tick": 0.25},
    "NQ": {"multiplier": 20.0, "tick": 0.25},
    "M2K": {"multiplier": 5.0, "tick": 0.10},
    "MGC": {"multiplier": 10.0, "tick": 0.10},
    "GC": {"multiplier": 100.0, "tick": 0.10},
    "MCL": {"multiplier": 100.0, "tick": 0.01},
    "CL": {"multiplier": 1000.0, "tick": 0.01},
    "ZB": {"multiplier": 1000.0, "tick": 0.03125},
    "ZN": {"multiplier": 1000.0, "tick": 0.015625},
    # ETFs trade 1 share-equivalent; multiplier 1, penny tick.
    "SPY": {"multiplier": 1.0, "tick": 0.01},
    "QQQ": {"multiplier": 1.0, "tick": 0.01},
    "IWM": {"multiplier": 1.0, "tick": 0.01},
    "DIA": {"multiplier": 1.0, "tick": 0.01},
    "GLD": {"multiplier": 1.0, "tick": 0.01},
}

# Cache uses MES_F / ES_F style prefixes for some symbols; map symbol -> prefix.
_PREFIX_OVERRIDE = {"ES": "ES_F"}


def load_bars(
    symbol: str,
    timeframe: str,
    cache_dir: str | Path,
    *,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """Load the freshest cached bars for `symbol` at `timeframe`.

    Returns an OHLC(V) frame indexed by tz-aware DatetimeIndex, ascending.
    """
    cache_dir = Path(cache_dir)
    prefix = _PREFIX_OVERRIDE.get(symbol, symbol)
    path = _find_latest_cache(cache_dir, prefix, suffix=f"_{timeframe}.csv")

    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    ts = pd.to_datetime(df[ts_col])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC").dt.tz_convert(tz)
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing columns: {missing}")
    return df


def spec_for(symbol: str) -> dict:
    if symbol not in CONTRACT_SPECS:
        raise KeyError(f"no contract spec for '{symbol}' -- add it to CONTRACT_SPECS")
    return CONTRACT_SPECS[symbol]


def has_cache(symbol: str, timeframe: str, cache_dir: str | Path) -> bool:
    """True if at least one cache file exists for symbol+timeframe (no read)."""
    prefix = _PREFIX_OVERRIDE.get(symbol, symbol)
    return any(Path(cache_dir).glob(f"{prefix}_*_{timeframe}.csv"))
