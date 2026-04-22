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
  1. Try MGC futures via Polygon.io (primary)
  2. If unavailable, raise RuntimeError — no proxy fallback to maintain data integrity

Output:
    engine/backtest/cache/MGC_2022-01-01_2026-03-30_1d.csv

Usage:
    cd engine
    .venv/Scripts/python -m backtest.fetch_mgc_history_2022

    # Custom date range:
    .venv/Scripts/python -m backtest.fetch_mgc_history_2022 --start 2021-01-01 --end 2026-03-30
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_START = "2022-01-01"
DEFAULT_END = datetime.now().strftime("%Y-%m-%d")

# MGC (Micro Gold): 10 troy oz — price levels identical to GC (both quoted $/oz)
# We store raw price levels; walk_forward.py applies the configured multiplier.
MGC_TICKER = "MGC"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def fetch_mgc_polygon(start: str, end: str) -> pd.DataFrame | None:
    """Fetch MGC daily bars from Polygon.io."""
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key or api_key == "your_polygon_key_here":
        logger.error("POLYGON_API_KEY not set — cannot fetch from Polygon.io")
        return None

    try:
        from polygon import RESTClient
    except ImportError:
        logger.error("polygon-api-client not installed: pip install polygon-api-client")
        return None

    logger.info(f"Fetching MGC daily bars from Polygon.io ({start} -> {end})...")
    try:
        client = RESTClient(api_key)
        bars = []
        for agg in client.list_aggs(MGC_TICKER, 1, "day", start, end, limit=50000):
            bars.append(
                {
                    "timestamp": datetime.fromtimestamp(agg.timestamp / 1000).strftime("%Y-%m-%d"),
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": int(agg.volume) if agg.volume else 0,
                }
            )

        if not bars:
            logger.warning(f"Polygon returned no MGC bars for {start} -> {end}")
            return None

        df = pd.DataFrame(bars)
        df = (
            df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        )

        if len(df) < 50:
            logger.warning(f"Polygon MGC returned only {len(df)} rows — likely incomplete")
            return None

        logger.info(
            f"Polygon MGC: {len(df)} rows ({df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]})"
        )
        return df

    except Exception as exc:
        logger.warning(f"Polygon MGC fetch failed: {exc}")
        return None


def build_cache(
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
) -> Path:
    """
    Fetch MGC historical data, cache to CSV, and return the output path.
    Fetches from Polygon.io — raises RuntimeError if unavailable.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    safe_end = end.replace(":", "-")
    out_path = CACHE_DIR / f"MGC_{start}_{safe_end}_1d.csv"

    if out_path.exists():
        df_existing = pd.read_csv(out_path)
        if len(df_existing) > 200:
            logger.info(
                f"Cache hit: {out_path} ({len(df_existing)} rows). Use --force to re-download."
            )
            return out_path

    df = fetch_mgc_polygon(start, end)

    if df is None or df.empty:
        raise RuntimeError(
            "Polygon.io MGC fetch failed. "
            "Ensure POLYGON_API_KEY is set in engine/.env and polygon-api-client is installed."
        )

    # Filter to requested date range
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[(df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] <= pd.Timestamp(end))]
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d")

    df.to_csv(out_path, index=False)

    logger.info(f"\n{'=' * 60}")
    logger.info("MGC 2022+ history cached:")
    logger.info(f"  File:   {out_path}")
    logger.info(f"  Rows:   {len(df)}")
    logger.info(f"  Range:  {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
    logger.info("  Source: Polygon.io")
    logger.info(f"  Close range: {df['close'].min():.2f} – {df['close'].max():.2f}")
    logger.info(f"{'=' * 60}\n")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch MGC (Micro Gold) daily OHLCV data from 2022 via Polygon.io",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", default=DEFAULT_START, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=DEFAULT_END, help="End date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Re-download even if cache exists")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("JARVIS TRADER — MGC 2022+ History Builder (Polygon.io)")
    logger.info(f"Range: {args.start} -> {args.end}")
    logger.info("=" * 60)

    if args.force:
        # Remove existing cache to force re-download
        safe_end = args.end.replace(":", "-")
        out_path = CACHE_DIR / f"MGC_{args.start}_{safe_end}_1d.csv"
        if out_path.exists():
            out_path.unlink()
            logger.info(f"Removed existing cache: {out_path.name}")

    try:
        out = build_cache(start=args.start, end=args.end)
        print(f"\nMGC history cached: {out}")
    except Exception as exc:
        logger.error(f"FAILED: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
