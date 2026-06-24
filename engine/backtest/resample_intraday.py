#!/usr/bin/env python
"""JARVIS TRADER -- offline intraday resampler (lever 3, no-Gateway variant).

The discovery factory's MGC 5m cont cache spans ~24 months while its 15m cache
spans only ~15 -- so the deepest 15m history we can get WITHOUT a live IB Gateway
is to resample the deeper 5m series up to 15m. This is a pure offline OHLCV
aggregation (open=first, high=max, low=min, close=last, volume=sum over each
bin), valid on a roll-adjusted (_cont) continuous series.

It does NOT call IB and does NOT touch the engine. It writes a new
``<SYM>_<start>_<end>_15m_cont.csv`` that the factory's loader can consume via
``--cache-dir`` (kept in an isolated dir so it does not shadow the fresher,
shallower real 15m cache via the freshest-end-date rule).

Usage (from engine/):
    .venv/Scripts/python -m backtest.resample_intraday \
        --src  <path>/MGC_2024-05-01_2026-05-29_5m_cont.csv \
        --rule 15min --out-dir <dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Pandas resample aggregation for OHLCV bars.
_OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate an OHLCV frame to a coarser bar `rule` (e.g. '15min').

    Expects a 'timestamp' column (tz-aware ISO) plus open/high/low/close/volume.
    Bins are left-closed/left-labelled (a 15min bar stamped HH:00 covers
    HH:00..HH:14), matching how intraday futures bars are conventionally stamped.
    Empty bins (no underlying 5m bars -- e.g. session gaps) are dropped.
    """
    missing = {"timestamp", "open", "high", "low", "close", "volume"} - set(df.columns)
    if missing:
        raise ValueError(f"resample_ohlcv: missing columns {sorted(missing)}")
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.set_index("timestamp").sort_index()
    agg = out.resample(rule, label="left", closed="left").agg(_OHLCV_AGG)
    agg = agg.dropna(subset=["open", "high", "low", "close"])
    return agg.reset_index()


def _out_name(src: Path, df: pd.DataFrame, interval_suffix: str) -> str:
    """`<SYM>_<startdate>_<enddate>_<suffix>_cont.csv` from the resampled span."""
    symbol = src.name.split("_", 1)[0]
    start = pd.to_datetime(df["timestamp"].iloc[0]).strftime("%Y-%m-%d")
    end = pd.to_datetime(df["timestamp"].iloc[-1]).strftime("%Y-%m-%d")
    return f"{symbol}_{start}_{end}_{interval_suffix}_cont.csv"


def main() -> int:
    p = argparse.ArgumentParser(description="Resample an intraday OHLCV cache to a coarser bar.")
    p.add_argument("--src", required=True, help="Source CSV (e.g. a 5m _cont cache)")
    p.add_argument("--rule", default="15min", help="Pandas offset alias (default 15min)")
    p.add_argument(
        "--suffix", default="15m", help="Interval suffix for the output filename (default 15m)"
    )
    p.add_argument("--out-dir", required=True, help="Directory to write the resampled cache into")
    args = p.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"ERROR: src not found: {src}", file=sys.stderr)
        return 1
    df = resample_ohlcv(pd.read_csv(src), args.rule)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _out_name(src, df, args.suffix)
    df.to_csv(out_path, index=False)
    print(f"wrote {len(df)} {args.rule} bars -> {out_path}")
    print(f"span {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
