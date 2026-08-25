#!/usr/bin/env python
"""VIX/VIX3M/VIX9D history fetcher backed by free sources.

CBOE's CDN CSV endpoint (cdn.cboe.com) now returns HTTP 403 to scripted
fetches, and Stooq has a JS proof-of-work wall, so this module pulls the same
daily index history from free sources that need no API key:

  VIX   -> Yahoo Finance  (^VIX)     ~9k rows since 1990
  VIX3M -> FRED (St. Louis Fed)      VXVCLS = CBOE S&P500 3-Month Volatility
                                     Index (VIX3M's former symbol VXV), ~4.9k
                                     rows since 2007
  VIX9D -> Yahoo Finance  (^VIX9D)   Yahoo only carries the latest quote, so
                                     this series is best-effort (often 1 row)

Usage:
  python fetch_cboe_vix.py --symbol VIX --output-dir data/vol_regime/raw/
  python fetch_cboe_vix.py --all --output-dir data/vol_regime/raw/
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Yahoo tickers for the CBOE volatility indices this study consumes.
YAHOO_TICKERS = {
    "VIX": "^VIX",
    "VIX3M": "^VIX3M",
    "VIX9D": "^VIX9D",
}

# FRED series for VIX3M (official CBOE 3-month index under its former VXV symbol).
FRED_SERIES = {
    "VIX3M": "VXVCLS",
}


def _from_yahoo(symbol: str, timeout: float) -> pd.DataFrame:
    import yfinance as yf

    ticker = YAHOO_TICKERS[symbol]
    logger.info("Fetching %s (%s) from Yahoo Finance ...", symbol, ticker)
    raw = yf.download(ticker, period="max", interval="1d", progress=False, timeout=timeout)
    if raw is None or raw.empty:
        raise RuntimeError(f"{symbol}: Yahoo returned no rows for {ticker}")

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce", utc=True).dt.tz_convert(None),
            "close": pd.to_numeric(df["Close"], errors="coerce"),
        }
    ).dropna(subset=["date", "close"])


def _from_fred(symbol: str, timeout: float) -> pd.DataFrame:
    """Fetch a FRED series via the free fredgraph.csv endpoint (no API key)."""
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen

    series = FRED_SERIES[symbol]
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    logger.info("Fetching %s (%s) from FRED ...", symbol, series)
    try:
        with urlopen(url, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"{symbol}: FRED fetch failed: {exc}") from exc

    df = pd.read_csv(pd.io.common.StringIO(text))
    if df.empty or len(df.columns) < 2:
        raise RuntimeError(f"{symbol}: FRED returned no rows for {series}")
    value_col = df.columns[1]
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[df.columns[0]], errors="coerce"),
            "close": pd.to_numeric(df[value_col], errors="coerce"),
        }
    )
    out = out.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
    return out.reset_index(drop=True)


def fetch_yahoo_history(symbol: str, timeout: float = 60.0) -> pd.DataFrame:
    """Fetch daily history for a volatility index (Yahoo or FRED per symbol).

    Args:
        symbol: one of "VIX", "VIX3M", "VIX9D".
        timeout: seconds to wait for the download.

    Returns:
        DataFrame with ``date`` and ``close`` columns (normalized daily).
    """
    if symbol in FRED_SERIES:
        return _from_fred(symbol, timeout)
    if symbol in YAHOO_TICKERS:
        return _from_yahoo(symbol, timeout)
    raise ValueError(f"unsupported symbol: {symbol!r}")


def fetch_vix_series(symbol: str, out_dir: Path, timeout: float = 60.0) -> pd.DataFrame:
    """Fetch one volatility series and cache it to ``out_dir/<symbol>_daily.csv``.

    Returns the fetched DataFrame. An existing cache file is left untouched
    (callers decide freshness); this function always re-fetches.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = fetch_yahoo_history(symbol, timeout=timeout)
    cache_path = out_dir / f"{symbol}_daily.csv"
    df.to_csv(cache_path, index=False)
    logger.info("Cached %s -> %s", symbol, cache_path)
    return df


def fetch_all_vix(out_dir: Path, timeout: float = 60.0) -> dict[str, pd.DataFrame]:
    """Fetch VIX, VIX3M and VIX9D and cache each; return {symbol: df}."""
    result: dict[str, pd.DataFrame] = {}
    for symbol in ("VIX", "VIX3M", "VIX9D"):
        for attempt in range(3):
            try:
                result[symbol] = fetch_vix_series(symbol, out_dir, timeout=timeout)
                break
            except Exception as exc:  # noqa: BLE001 - transient network/rate limits
                logger.warning("%s fetch attempt %d/3 failed: %s", symbol, attempt + 1, exc)
                time.sleep(2 * (attempt + 1))
        else:
            logger.error("Giving up on %s after 3 attempts", symbol)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch CBOE volatility index history (free sources)")
    parser.add_argument("--symbol", choices=["VIX", "VIX3M", "VIX9D"], help="Which index to fetch")
    parser.add_argument("--all", action="store_true", help="Fetch VIX, VIX3M and VIX9D")
    parser.add_argument("--output-dir", type=Path, default="data/vol_regime/raw", help="Cache directory")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if args.all:
        result = fetch_all_vix(args.output_dir)
        print(f"Fetched {len(result)} series into {args.output_dir}")
        for symbol, df in result.items():
            if df.empty:
                print(f"  {symbol}: NO DATA")
            else:
                print(f"  {symbol}: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")
        return 0

    if args.symbol is None:
        parser.error("--symbol is required unless --all is given")

    try:
        df = fetch_vix_series(args.symbol, args.output_dir)
        print(f"{args.symbol}: {len(df)} rows cached to {args.output_dir}")
        print(df.tail(3).to_string(index=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        logging.error("Fetch failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
