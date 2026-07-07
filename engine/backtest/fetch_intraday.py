"""
JARVIS TRADER — Intraday Data Fetcher
Fetches intraday (1h, 15m, 5m) data via Polygon.io.
Saves to backtest/cache/ for use by backtester and optimizer.

Usage:
    python -m backtest.fetch_intraday --symbol SPY --interval 1h --days 180
    python -m backtest.fetch_intraday --symbol MES --interval 1h --days 730
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta

import pandas as pd

from backtest.data_loader import CACHE_DIR, FUTURES_MAP


def _fetch_via_polygon(
    symbol: str,
    interval: str,
    days: int,
) -> pd.DataFrame | None:
    """
    Fetch intraday data via Polygon.io REST API.
    Requires POLYGON_API_KEY env var or set in engine/.env.
    Free tier: 5 calls/min, unlimited history.
    """
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key or api_key == "your_polygon_key_here":
        return None

    try:
        from polygon import RESTClient
    except ImportError:
        print("[Fetcher] polygon-api-client not installed: pip install polygon-api-client")
        return None

    # Map interval to Polygon timespan/multiplier
    tf_map = {
        "1m": ("minute", 1),
        "5m": ("minute", 5),
        "15m": ("minute", 15),
        "30m": ("minute", 30),
        "1h": ("hour", 1),
        "1d": ("day", 1),
    }
    timespan, multiplier = tf_map.get(interval, ("hour", 1))
    ticker_sym = FUTURES_MAP.get(symbol.upper(), symbol)

    end = datetime.now()
    start = end - timedelta(days=days)
    from_date = start.strftime("%Y-%m-%d")
    to_date = end.strftime("%Y-%m-%d")

    print(f"[Fetcher] Trying Polygon.io for {symbol} ({ticker_sym}) {interval}...")
    try:
        client = RESTClient(api_key)
        bars = []
        for agg in client.list_aggs(
            ticker_sym,
            multiplier,
            timespan,
            from_date,
            to_date,
            limit=50000,
        ):
            bars.append(
                {
                    "timestamp": datetime.fromtimestamp(agg.timestamp / 1000),
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": agg.volume,
                }
            )

        if not bars:
            print(f"[Fetcher] Polygon returned no bars for {symbol}")
            return None

        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        df["timestamp"] = df.index
        print(f"[Fetcher] Polygon: {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        print(f"[Fetcher] Polygon failed: {e}")
        return None


def fetch_intraday(
    symbol: str,
    interval: str = "1h",
    days: int = 180,
    force: bool = False,
) -> pd.DataFrame | None:
    cache_file = CACHE_DIR / f"{symbol}_{interval}_{days}d.csv"

    if cache_file.exists() and not force:
        df = pd.read_csv(cache_file, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        df.index = pd.to_datetime(df.index)
        df["timestamp"] = df.index
        print(f"[Fetcher] Cache hit: {cache_file.name} ({len(df)} bars)")
        return df

    # Fetch from Polygon (no rate limit issues, unlimited history)
    df = _fetch_via_polygon(symbol, interval, days)
    if df is not None and not df.empty:
        df.to_csv(cache_file, index=False)
        print(f"[Fetcher] Saved {len(df)} bars to {cache_file.name}")
        return df

    print(f"[Fetcher] No data retrieved for {symbol} — check POLYGON_API_KEY")
    return None


def main():
    parser = argparse.ArgumentParser(description="JARVIS Intraday Data Fetcher")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--interval", default="1h", choices=["1m", "5m", "15m", "30m", "1h", "1d"])
    parser.add_argument("--days", type=int, default=180, help="How many days back to fetch")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    args = parser.parse_args()

    df = fetch_intraday(args.symbol, args.interval, args.days, args.force)
    if df is not None:
        print(f"\nReady: {len(df)} {args.interval} bars for {args.symbol}")
        print(f"Date range: {df.index[0]} → {df.index[-1]}")
    else:
        print("\nFetch failed — check POLYGON_API_KEY is set in engine/.env")


if __name__ == "__main__":
    main()
