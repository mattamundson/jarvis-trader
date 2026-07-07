"""
Build 2025 daily OHLCV cache.
- SPY: resample from SPY_1h_730d.csv (already in cache).
- MES: Polygon.io ES daily data, with SPY-return proxy as fallback.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
START = "2025-01-01"
END = "2026-01-01"


def spy_daily_from_hourly() -> Path:
    src = CACHE_DIR / "SPY_1h_730d.csv"
    if not src.exists():
        raise FileNotFoundError(f"Missing {src}")
    df = pd.read_csv(src, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    df = df.set_index("timestamp").sort_index()
    # Align to calendar day in local exchange tz already in index
    daily = df.resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    daily = daily.dropna(subset=["open", "high", "low", "close"])
    daily = daily[
        (daily.index >= pd.Timestamp(START, tz=daily.index.tz))
        & (daily.index < pd.Timestamp(END, tz=daily.index.tz))
    ]
    daily = daily.reset_index()
    if daily.columns[0] != "timestamp":
        daily = daily.rename(columns={daily.columns[0]: "timestamp"})
    daily["timestamp"] = pd.to_datetime(daily["timestamp"]).dt.strftime("%Y-%m-%d")
    out = CACHE_DIR / f"SPY_{START}_{END}_1d.csv"
    daily.to_csv(out, index=False)
    return out


def mes_daily_from_spy_returns_proxy() -> Path:
    """
    When Yahoo rate-limits ES=F, approximate ES daily OHLC by chaining
    off the last real ES close (MES cache 2024) with SPY close-to-close returns.
    PnL levels are in ES points × MES $5/pt — suitable for strategy/signal OOS checks only.
    """
    hist_2024 = CACHE_DIR / "MES_2024-01-01_2025-01-01_1d.csv"
    spy_2024 = CACHE_DIR / "SPY_2024-01-01_2025-01-01_1d.csv"
    spy_2025 = CACHE_DIR / f"SPY_{START}_{END}_1d.csv"
    for p in (hist_2024, spy_2024, spy_2025):
        if not p.exists():
            raise FileNotFoundError(f"Missing {p} for MES proxy")

    es = pd.read_csv(hist_2024)
    spy24 = pd.read_csv(spy_2024, parse_dates=["timestamp"])
    spy25 = pd.read_csv(spy_2025, parse_dates=["timestamp"])

    es_last = float(es["close"].iloc[-1])
    spy_last = float(spy24["close"].iloc[-1])

    prev_spy_c = spy_last
    prev_es_c = es_last

    rows = []
    for _, row in spy25.iterrows():
        o, h, low, c, vol = row["open"], row["high"], row["low"], row["close"], row["volume"]
        es_o = prev_es_c * (o / prev_spy_c)
        es_h = prev_es_c * (h / prev_spy_c)
        es_l = prev_es_c * (low / prev_spy_c)
        es_c = prev_es_c * (c / prev_spy_c)
        rows.append(
            {
                "open": es_o,
                "high": max(es_o, es_h, es_l, es_c),
                "low": min(es_o, es_h, es_l, es_c),
                "close": es_c,
                "volume": float(vol),
                "timestamp": pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%d"),
            }
        )
        prev_spy_c, prev_es_c = float(c), es_c

    out = CACHE_DIR / f"MES_{START}_{END}_1d.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def mes_daily_from_polygon() -> Path:
    """Fetch ES (MES proxy) daily data from Polygon.io, fall back to SPY return proxy."""
    from datetime import datetime

    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key or api_key == "your_polygon_key_here":
        print("[warn] POLYGON_API_KEY not set — building MES daily from SPY return proxy")
        return mes_daily_from_spy_returns_proxy()

    try:
        from polygon import RESTClient
    except ImportError:
        print("[warn] polygon-api-client not installed — building MES daily from SPY return proxy")
        return mes_daily_from_spy_returns_proxy()

    print(f"[info] Fetching MES daily bars from Polygon.io ({START} -> {END})...")
    try:
        client = RESTClient(api_key)
        bars = []
        for agg in client.list_aggs("MES", 1, "day", START, END, limit=50000):
            bars.append(
                {
                    "timestamp": datetime.fromtimestamp(agg.timestamp / 1000).strftime("%Y-%m-%d"),
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": agg.volume,
                }
            )
        if not bars:
            print("[warn] Polygon returned no MES bars — building from SPY return proxy")
            return mes_daily_from_spy_returns_proxy()
        df = pd.DataFrame(bars)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        out = CACHE_DIR / f"MES_{START}_{END}_1d.csv"
        df.to_csv(out, index=False)
        print(f"[ok] Polygon MES: {len(df)} rows")
        return out
    except Exception as exc:
        print(f"[warn] Polygon MES fetch failed ({exc}) — building from SPY return proxy")
        return mes_daily_from_spy_returns_proxy()


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--mes-only", action="store_true", help="Only fetch MES/ES=F daily (SPY cache unchanged)"
    )
    args = p.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not args.mes_only:
        p1 = spy_daily_from_hourly()
        print(f"[ok] {p1.name} ({len(pd.read_csv(p1))} rows)")
    p2 = mes_daily_from_polygon()
    print(f"[ok] {p2.name} ({len(pd.read_csv(p2))} rows)")


if __name__ == "__main__":
    main()
