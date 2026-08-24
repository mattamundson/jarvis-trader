#!/usr/bin/env python
"""Run a read-only SPY/QQQ volatility-regime study from local daily caches.

This script intentionally does not trade, route orders, mutate config, or call the
broker. It produces regime labels and forward-return analysis for research.

Usage:
  python vol_regime_study.py --symbols SPY,QQQ --start-date 2020-01-01 --end-date 2023-12-31
  python vol_regime_study.py --symbols SPY,QQQ --fetch-cboe --output-dir data/vol_regime/

Features:
- Regime classification based on realized volatility and VIX context
- Forward return analysis (1d, 3d, 5d)
- Era splits for robustness
- Bootstrap confidence intervals
- CSV/JSON output for dashboard integration

Data sources:
- SPY/QQQ daily OHLCV from local cache
- VIX/VIX3M from local cache, or fetched from Yahoo Finance (yfinance) with --fetch-cboe
- No broker, API keys, or live market access
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

# Add current directory to path for script execution
ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from analysis.volatility_regime import (
    RegimeThresholds,
    build_regime_frame,
    summarize_by_regime,
    latest_regime_snapshot,
)


def _score_cache(path: Path) -> tuple[int, pd.Timestamp, pd.Timestamp]:
    """Score a cache file by row count and date range."""
    df = pd.read_csv(path, usecols=lambda c: c.lower() in {"timestamp", "date", "close"})
    tcol = "timestamp" if "timestamp" in df.columns else "date" if "date" in df.columns else None
    if tcol is None:
        return (0, pd.Timestamp.min, pd.Timestamp.min)
    ts = pd.to_datetime(df[tcol], errors="coerce", utc=True).dt.tz_convert(None)
    return (int(ts.notna().sum()), ts.min(), ts.max())


def find_best_daily_cache(cache_dir: Path, symbol: str) -> Path:
    """Pick the longest daily cache for a symbol."""
    candidates = list(cache_dir.glob(f"{symbol}_*_1d.csv")) + list(cache_dir.glob(f"{symbol}_daily.csv"))
    if not candidates:
        raise FileNotFoundError(f"no daily cache found for {symbol} in {cache_dir}")
    ranked = []
    for path in candidates:
        try:
            score, start, end = _score_cache(path)
            ranked.append((score, start, end, path))
        except Exception:
            continue
    if not ranked:
        raise FileNotFoundError(f"no valid cache found for {symbol} in {cache_dir}")
    ranked.sort(reverse=True)
    return ranked[0][3]


def read_cache(path: Path) -> pd.DataFrame:
    """Read a cache file with date normalization."""
    if not path.exists():
        raise FileNotFoundError(f"cache not found: {path}")
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        df["date"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dt.tz_convert(None)
    elif "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_convert(None)
    else:
        raise ValueError(f"no date/timestamp column in {path}")
    df = df.dropna(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def maybe_find_vix(dirs: list[Path], patterns: list[str], *, exclude_prefixes: tuple[str, ...] = ()) -> Path | None:
    """Find VIX/VIX3M cache in standard locations.

    ``exclude_prefixes`` filters out files that belong to a longer-named index
    (e.g. when looking for VIX, skip VIX3M_daily.csv so the loose ``VIX*.csv``
    glob cannot capture the wrong series).
    """
    for directory in dirs:
        for pattern in patterns:
            matches = list(directory.glob(pattern))
            if exclude_prefixes:
                matches = [
                    m for m in matches
                    if not any(m.name.upper().startswith(p) for p in exclude_prefixes)
                ]
            if matches:
                return matches[0]
    return None


def fetch_vix_if_needed(vix_path: Path | None, vix3m_path: Path | None, raw_dir: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetch VIX/VIX3M from Yahoo Finance when not already cached, return dataframes."""
    try:
        from scripts.fetch_cboe_vix import fetch_all_vix
    except ImportError:
        logging.warning("fetch_cboe_vix.py not found, skipping VIX fetch")
        return None, None

    vix_df = None
    vix3m_df = None

    if vix_path is None:
        try:
            logging.info("Fetching VIX history from Yahoo Finance...")
            fetched = fetch_all_vix(raw_dir, timeout=60.0)
            if "VIX" in fetched and not fetched["VIX"].empty:
                vix_df = fetched["VIX"]
                logging.info("Saved VIX to %s", raw_dir / "VIX_daily.csv")
        except Exception as exc:
            logging.error("Failed to fetch VIX: %s", exc)

    if vix3m_path is None:
        try:
            logging.info("Fetching VIX3M history from Yahoo Finance...")
            fetched = fetch_all_vix(raw_dir, timeout=60.0)
            if "VIX3M" in fetched and not fetched["VIX3M"].empty:
                vix3m_df = fetched["VIX3M"]
                logging.info("Saved VIX3M to %s", raw_dir / "VIX3M_daily.csv")
        except Exception as exc:
            logging.error("Failed to fetch VIX3M: %s", exc)

    return vix_df, vix3m_df


def run(
    symbols: list[str],
    cache_dir: Path,
    out_dir: Path,
    fetch_cboe: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Run the volatility regime study.

    Returns a dict with the test-contract shape:
      {
        "symbols": {symbol: {"rows": int, "frame_csv": Path, "summary_csv": Path, "latest": dict}},
        "data_gaps": [str, ...],
      }
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    # Load SPY/QQQ data
    price_dfs = {}
    for symbol in symbols:
        try:
            path = find_best_daily_cache(cache_dir, symbol)
            df = read_cache(path)
            if start_date:
                df = df[df["date"] >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df["date"] <= pd.Timestamp(end_date)]
            price_dfs[symbol] = df
            logging.info(f"Loaded {symbol}: {len(df)} rows, {df['date'].min()} to {df['date'].max()}")
        except Exception as exc:
            logging.error(f"Failed to load {symbol}: {exc}")
            return {"error": f"Failed to load {symbol}: {exc}", "symbols": {}, "data_gaps": []}

    # Locate VIX/VIX3M caches (exclude the longer-named indices from the loose globs)
    search_dirs = [cache_dir, raw_dir]
    vix_path = maybe_find_vix(
        search_dirs, ["VIX*_1d.csv", "VIX*_daily.csv", "VIX*.csv"],
        exclude_prefixes=("VIX3M", "VIX9D"),
    )
    vix3m_path = maybe_find_vix(
        search_dirs, ["VIX3M*_1d.csv", "VIX3M*_daily.csv", "VIX3M*.csv"],
    )
    vix_df = read_cache(vix_path) if vix_path else None
    vix3m_df = read_cache(vix3m_path) if vix3m_path else None

    data_gaps = []
    if vix_df is None:
        data_gaps.append("VIX daily cache missing")
    if vix3m_df is None:
        data_gaps.append("VIX3M daily cache missing")

    # Fetch from Yahoo if requested and not cached
    if fetch_cboe and (vix_df is None or vix3m_df is None):
        fetched_vix, fetched_vix3m = fetch_vix_if_needed(vix_path, vix3m_path, raw_dir)
        if vix_df is None:
            vix_df = fetched_vix
            if vix_df is not None:
                data_gaps = [g for g in data_gaps if g != "VIX daily cache missing"]
        if vix3m_df is None:
            vix3m_df = fetched_vix3m
            if vix3m_df is not None:
                data_gaps = [g for g in data_gaps if g != "VIX3M daily cache missing"]

    # Build regime frames
    thresholds = RegimeThresholds()
    symbols_out = {}

    for symbol, price_df in price_dfs.items():
        try:
            # Full pipeline: prep -> realized vol -> trend -> VIX context -> labels -> forward outcomes
            frame = build_regime_frame(
                underlying=price_df,
                symbol=symbol,
                vix=vix_df,
                vix3m=vix3m_df,
                thresholds=thresholds,
            )

            summary = summarize_by_regime(frame)
            latest = latest_regime_snapshot(frame)

            # Save artifacts
            frame_csv = out_dir / f"{symbol}_regime_frame.csv"
            summary_csv = out_dir / f"{symbol}_regime_summary.csv"
            frame.to_csv(frame_csv, index=False)
            summary.to_csv(summary_csv, index=False)
            logging.info(f"Saved {symbol} frame -> {frame_csv}, summary -> {summary_csv}")

            symbols_out[symbol] = {
                "rows": int(len(frame)),
                "frame_csv": str(frame_csv),
                "summary_csv": str(summary_csv),
                "latest": latest,
            }
        except Exception as exc:
            logging.error(f"Failed to process {symbol}: {exc}")
            symbols_out[symbol] = {"error": str(exc), "rows": 0}

    # Save combined results
    results = {"symbols": symbols_out, "data_gaps": data_gaps}
    results_path = out_dir / "vol_regime_study.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logging.info(f"Saved results to {results_path}")

    return results


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run SPY/QQQ volatility regime study")
    parser.add_argument(
        "--symbols",
        type=str,
        default="SPY,QQQ",
        help="Comma-separated symbols to study",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("../../jarvis-trader/.claude/worktrees/wt-dash-wire-shells-20260818/engine/backtest/cache"),
        help="Directory containing daily cache files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default="data/vol_regime",
        help="Directory to save output files",
    )
    parser.add_argument(
        "--fetch-cboe",
        action="store_true",
        help="Fetch VIX/VIX3M from Yahoo Finance if not cached",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    symbols = [s.strip() for s in args.symbols.split(",")]
    cache_dir = args.cache_dir.resolve()
    output_dir = args.output_dir.resolve()

    try:
        results = run(symbols, cache_dir, output_dir, args.fetch_cboe, args.start_date, args.end_date)
        print(f"Study complete. Results saved to {output_dir}")
        for symbol, info in results.get("symbols", {}).items():
            print(f"  {symbol}: {info.get('rows', 0)} rows, regime={info.get('latest', {}).get('regime')}")
        if results.get("data_gaps"):
            print("Data gaps:")
            for gap in results["data_gaps"]:
                print(f"  - {gap}")
        return 0
    except Exception as exc:
        logging.error(f"Study failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
