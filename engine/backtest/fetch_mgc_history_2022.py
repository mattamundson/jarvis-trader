"""
JARVIS TRADER — MGC 2022–2026 Daily History Fetcher
====================================================
Downloads Micro Gold (MGC) daily OHLCV data starting from 2022-01-01 to cover:
  - 2022 bear market + Fed rate hike cycle (gold ranging / declining)
  - 2023 recovery / SVB crisis spike
  - 2024–2026 gold bull run

This extended dataset is required for a valid walk-forward re-evaluation
of the MGC 1d STC+ATR strategy (see EXECUTIVE_BRIEFING.md §MGC 1d).

Strategy:
  1. Try GC=F (Gold futures CMX) via yfinance — best source
  2. If rate-limited, fallback to GLD ETF returns (proxy)
  3. Scale proxy prices to approximate MGC point values

Output:
    engine/backtest/cache/MGC_2022-01-01_2026-03-30_1d.csv

Usage:
    cd engine
    .venv/Scripts/python -m backtest.fetch_mgc_history_2022

    # Force GLD proxy (skip GC=F):
    .venv/Scripts/python -m backtest.fetch_mgc_history_2022 --proxy

    # Custom date range:
    .venv/Scripts/python -m backtest.fetch_mgc_history_2022 --start 2021-01-01 --end 2026-03-30
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

# ── Config ────────────────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_START = "2022-01-01"
DEFAULT_END = datetime.now().strftime("%Y-%m-%d")

# GC=F standard contract: 100 troy oz
# MGC (Micro Gold): 10 troy oz (0.10 × GC)
# Price levels are the SAME (both quoted $/oz) — only multiplier differs for P&L.
# We store raw price levels; walk_forward.py multiplies by the configured `multiplier`.
GC_TICKER = "GC=F"  # Gold futures (Yahoo Finance)
GLD_TICKER = "GLD"  # SPDR Gold ETF (proxy fallback)
GLD_TO_GC_RATIO = 10.0  # GLD ≈ 1/10 of gold spot; adjust to approximate GC point levels

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _normalize_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize a yfinance DataFrame to JARVIS OHLCV format."""
    df = df.copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    df = df.sort_index()

    col_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=col_map)
    needed = ["open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker} missing columns: {missing}. Available: {list(df.columns)}")

    df = df[needed].dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).astype(int)
    df = df.reset_index()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d")
    return df


def fetch_gc_direct(start: str, end: str) -> pd.DataFrame | None:
    """Fetch GC=F (gold futures) directly from Yahoo Finance."""
    logger.info(f"Fetching GC=F (Gold Futures) {start} → {end}...")
    try:
        ticker = yf.Ticker(GC_TICKER)
        df = ticker.history(start=start, end=end, interval="1d", auto_adjust=True, actions=False)
        if df.empty:
            logger.warning("GC=F returned empty dataframe (rate limit or market data unavailable)")
            return None
        df = _normalize_df(df, GC_TICKER)
        if len(df) < 50:
            logger.warning(f"GC=F returned only {len(df)} rows — likely incomplete")
            return None
        logger.info(
            f"GC=F: {len(df)} rows ({df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]})"
        )
        return df
    except Exception as e:
        logger.warning(f"GC=F fetch failed: {e}")
        return None


def fetch_gc_batched(start: str, end: str, batch_years: int = 2) -> pd.DataFrame | None:
    """
    Fetch GC=F in yearly batches to avoid rate limiting.
    Adds a 3-second sleep between batches.
    """
    from datetime import date

    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()

    frames = []
    cursor = start_d
    while cursor < end_d:
        batch_end = min(date(cursor.year + batch_years, cursor.month, cursor.day), end_d)
        batch_start_str = cursor.strftime("%Y-%m-%d")
        batch_end_str = batch_end.strftime("%Y-%m-%d")
        logger.info(f"  Batch: {batch_start_str} → {batch_end_str}")
        try:
            ticker = yf.Ticker(GC_TICKER)
            df = ticker.history(
                start=batch_start_str,
                end=batch_end_str,
                interval="1d",
                auto_adjust=True,
                actions=False,
            )
            if not df.empty:
                frames.append(_normalize_df(df, f"GC=F[{batch_start_str}]"))
                logger.info(f"    Got {len(df)} rows")
            else:
                logger.warning(f"    Empty batch {batch_start_str}–{batch_end_str}")
        except Exception as e:
            logger.warning(f"    Batch error: {e}")
        cursor = batch_end
        if cursor < end_d:
            logger.info("  Sleeping 3s between batches...")
            time.sleep(3)

    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    return combined


def fetch_gld_proxy(start: str, end: str) -> pd.DataFrame | None:
    """
    Fetch GLD ETF as a proxy for gold price when GC=F is unavailable.
    GLD ≈ 1/10 oz gold. Scale to approximate GC/MGC price levels.
    Note: GLD price × GLD_TO_GC_RATIO approximates GC ($/oz) levels.
    """
    logger.info(f"Fetching GLD (proxy) {start} → {end}...")
    try:
        ticker = yf.Ticker(GLD_TICKER)
        df = ticker.history(start=start, end=end, interval="1d", auto_adjust=True, actions=False)
        if df.empty:
            logger.error("GLD proxy also returned empty — check network or Yahoo Finance status")
            return None
        df = _normalize_df(df, GLD_TICKER)

        # Scale GLD to approximate GC price levels
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * GLD_TO_GC_RATIO
        df["volume"] = (df["volume"] / 10).astype(int)  # Approximate volume scale

        logger.info(
            f"GLD proxy: {len(df)} rows ({df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}). "
            f"Sample close: {df['close'].iloc[-1]:.2f} (GC-scale)"
        )
        return df
    except Exception as e:
        logger.error(f"GLD proxy fetch failed: {e}")
        return None


def build_cache(
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    force_proxy: bool = False,
) -> Path:
    """
    Fetch MGC historical data, cache to CSV, and return the output path.

    Tries GC=F direct → GC=F batched → GLD proxy in order.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    safe_end = end.replace(":", "-")
    out_path = CACHE_DIR / f"MGC_{start}_{safe_end}_1d.csv"

    if out_path.exists() and not force_proxy:
        df_existing = pd.read_csv(out_path)
        if len(df_existing) > 200:
            logger.info(
                f"Cache hit: {out_path} ({len(df_existing)} rows). Use --force to re-download."
            )
            return out_path

    if force_proxy:
        logger.info("--proxy flag set — using GLD ETF directly")
        df = fetch_gld_proxy(start, end)
        source = "GLD_proxy"
    else:
        # Attempt 1: direct download
        df = fetch_gc_direct(start, end)
        source = "GC=F_direct"

        if df is None:
            logger.info("Direct download failed — trying batched download...")
            time.sleep(5)
            df = fetch_gc_batched(start, end, batch_years=2)
            source = "GC=F_batched"

        if df is None:
            logger.warning("GC=F unavailable — falling back to GLD proxy...")
            df = fetch_gld_proxy(start, end)
            source = "GLD_proxy"

    if df is None or df.empty:
        raise RuntimeError(
            "All data sources failed (GC=F direct, GC=F batched, GLD proxy). "
            "Check network connectivity and Yahoo Finance status."
        )

    # Add metadata column for traceability
    df["source"] = source

    # Filter to requested date range
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[(df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] <= pd.Timestamp(end))]
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d")

    df.to_csv(out_path, index=False)

    logger.info(f"\n{'=' * 60}")
    logger.info("MGC 2022+ history cached:")
    logger.info(f"  File:   {out_path}")
    logger.info(f"  Rows:   {len(df)}")
    logger.info(f"  Range:  {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
    logger.info(f"  Source: {source}")
    logger.info(f"  Close range: {df['close'].min():.2f} – {df['close'].max():.2f}")
    logger.info(f"{'=' * 60}\n")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch MGC (Micro Gold) daily OHLCV data from 2022 for walk-forward re-evaluation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", default=DEFAULT_START, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=DEFAULT_END, help="End date (YYYY-MM-DD)")
    parser.add_argument("--proxy", action="store_true", help="Force GLD ETF proxy instead of GC=F")
    parser.add_argument("--force", action="store_true", help="Re-download even if cache exists")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("JARVIS TRADER — MGC 2022+ History Builder")
    logger.info(f"Range: {args.start} → {args.end}")
    logger.info(f"Proxy: {args.proxy}")
    logger.info("=" * 60)

    try:
        out = build_cache(start=args.start, end=args.end, force_proxy=args.proxy)
        print(f"\n✅ MGC history cached: {out}")
    except Exception as e:
        logger.error(f"FAILED: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
