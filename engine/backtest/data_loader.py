"""
JARVIS TRADER — Backtest Data Loader
Fetches historical OHLCV data via yfinance with futures symbol mapping.
Results are cached to disk to avoid Yahoo Finance rate limits on repeated runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


FUTURES_MAP: Dict[str, str] = {
    # Micro futures → yfinance continuous contract
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MCL": "CL=F",
    "MGC": "GC=F",
    "M2K": "RTY=F",
    "MYM": "YM=F",
    # Standard futures
    "ES": "ES=F",
    "NQ": "NQ=F",
    "CL": "CL=F",
    "GC": "GC=F",
    "RTY": "RTY=F",
    "YM": "YM=F",
    "SI": "SI=F",
    "ZB": "ZB=F",
    "ZN": "ZN=F",
}

CONTRACT_MULTIPLIERS: Dict[str, float] = {
    "MES": 5.0,  # $5 per point
    "ES": 50.0,  # $50 per point
    "MNQ": 2.0,  # $2 per point
    "NQ": 20.0,  # $20 per point
    "MCL": 100.0,  # $100 per barrel (micro = 100 barrels)
    "CL": 1000.0,  # $1000 per barrel
    "MGC": 10.0,  # $10 per oz
    "GC": 100.0,  # $100 per oz
    "M2K": 5.0,  # $5 per point
    "RTY": 50.0,  # $50 per point
    "MYM": 0.5,  # $0.50 per point
    "YM": 5.0,  # $5 per point
    # ETFs (no multiplier)
    "SPY": 1.0,
    "QQQ": 1.0,
    "IWM": 1.0,
}


class BacktestDataLoader:
    """Load historical OHLCV data for backtesting."""

    def _cache_path(self, symbol: str, start: str, end: str, interval: str) -> Path:
        safe = f"{symbol}_{start}_{end}_{interval}".replace("/", "-").replace(":", "-")
        return CACHE_DIR / f"{safe}.csv"

    def _find_alternate_cache(
        self, symbol: str, start: str, end: str, interval: str
    ) -> Optional[Path]:
        """
        Look for any existing cache file for this symbol/interval that covers the
        requested date range.  Checks two patterns:
          1. {SYMBOL}_{interval}_*.csv   (e.g. MNQ_1h_730d.csv)
          2. {SYMBOL}_*_{interval}.csv   (the canonical pattern with different dates)
        Returns the Path of the first matching file whose data actually spans [start, end],
        or None if nothing suitable is found.
        """
        sym_up = symbol.upper()
        candidates: list[Path] = []
        for pat in (f"{sym_up}_{interval}_*.csv", f"{sym_up}_*_{interval}.csv"):
            candidates.extend(CACHE_DIR.glob(pat))

        if not candidates:
            return None

        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)

        for path in candidates:
            try:
                # Read only the timestamp column to check coverage cheaply
                tmp = pd.read_csv(path, usecols=["timestamp"], parse_dates=["timestamp"])
                tmp_ts = pd.to_datetime(tmp["timestamp"])
                if tmp_ts.min() <= start_dt and tmp_ts.max() >= end_dt - pd.Timedelta(days=3):
                    print(
                        f"[DataLoader] Alternate cache match: {path.name} "
                        f"(covers {tmp_ts.min().date()} -> {tmp_ts.max().date()})"
                    )
                    return path
            except Exception:
                continue
        return None

    def _fetch_direct_yahoo(self, ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        """
        Bypass yfinance rate limits by hitting Yahoo Finance v8 API directly.
        Uses browser User-Agent to avoid detection.
        Fetches in 60-day chunks for 1h data (Yahoo limit), concatenates.
        """
        from datetime import datetime, timedelta

        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        base_url = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

        # For 1h intervals Yahoo caps each request at ~60 days; use smaller chunks
        # to stay well under the limit. For daily/weekly data use larger windows.
        if interval in ("1h", "60m", "30m", "15m", "5m", "2m", "1m"):
            chunk_days = 58
        else:
            chunk_days = 365

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        all_frames: list[pd.DataFrame] = []
        chunk_start = start_dt

        while chunk_start < end_dt:
            chunk_end = min(chunk_start + timedelta(days=chunk_days), end_dt)
            period1 = int(chunk_start.timestamp())
            period2 = int(chunk_end.timestamp())

            url = base_url.format(ticker=ticker)
            params = {
                "interval": interval,
                "period1": period1,
                "period2": period2,
                "includePrePost": "false",
                "events": "div,splits",
            }

            try:
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                result = data.get("chart", {}).get("result")
                if not result:
                    error = data.get("chart", {}).get("error")
                    print(
                        f"[DataLoader] v8 API returned no result for chunk "
                        f"{chunk_start.date()}–{chunk_end.date()}: {error}"
                    )
                    chunk_start = chunk_end
                    continue

                meta = result[0]
                timestamps = meta.get("timestamp", [])
                quotes = meta.get("indicators", {}).get("quote", [{}])[0]

                if not timestamps:
                    chunk_start = chunk_end
                    continue

                chunk_df = pd.DataFrame(
                    {
                        "timestamp": pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(
                            None
                        ),
                        "open": quotes.get("open", []),
                        "high": quotes.get("high", []),
                        "low": quotes.get("low", []),
                        "close": quotes.get("close", []),
                        "volume": quotes.get("volume", []),
                    }
                )
                chunk_df = chunk_df.dropna(subset=["open", "high", "low", "close"])
                all_frames.append(chunk_df)
                print(
                    f"[DataLoader] v8 chunk {chunk_start.date()}–{chunk_end.date()}: "
                    f"{len(chunk_df)} bars"
                )

            except Exception as exc:
                print(
                    f"[DataLoader] v8 API error for chunk "
                    f"{chunk_start.date()}–{chunk_end.date()}: {exc}"
                )

            chunk_start = chunk_end

        if not all_frames:
            return pd.DataFrame()

        df = pd.concat(all_frames, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        df = df.set_index("timestamp")
        df["timestamp"] = df.index
        return df

    def load(
        self, symbol: str, start: str, end: str, interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data for a symbol.
        Maps futures symbols to yfinance format automatically.
        Returns DataFrame with lowercase columns: open, high, low, close, volume, timestamp.
        Caches results to disk to avoid Yahoo Finance rate limits on repeated runs.
        """
        cache_file = self._cache_path(symbol, start, end, interval)

        # Check primary cache path first, then fall back to alternate naming patterns
        cache_to_try = (
            cache_file
            if cache_file.exists()
            else self._find_alternate_cache(symbol, start, end, interval)
        )

        if cache_to_try is not None:
            try:
                df = pd.read_csv(cache_to_try)
                # Normalize column names (handle both 'timestamp' and 'Datetime')
                df.columns = [c.lower() for c in df.columns]
                if "datetime" in df.columns:
                    df = df.rename(columns={"datetime": "timestamp"})
                df = df.set_index(pd.to_datetime(df["timestamp"]))
                # Normalize to UTC then strip tz — handles mixed-tz CSV files
                df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
                df["timestamp"] = df.index
                # Trim to requested date window (index is tz-naive after normalization)
                start_dt = pd.Timestamp(start)
                end_dt = pd.Timestamp(end)
                df = df[(df.index >= start_dt) & (df.index <= end_dt)]
                print(f"[DataLoader] Cache hit: {cache_to_try.name} ({len(df)} bars)")
                # If loaded from an alternate path, save under the canonical name so
                # future runs hit the primary path immediately
                if cache_to_try != cache_file and not cache_file.exists():
                    try:
                        df.to_csv(cache_file, index=False)
                        print(f"[DataLoader] Saved canonical cache: {cache_file.name}")
                    except Exception:
                        pass
                return df
            except Exception as e:
                print(f"[DataLoader] Cache read failed ({e}), re-fetching...")

        ticker = FUTURES_MAP.get(symbol.upper(), symbol)

        raw = None
        try:
            raw = yf.download(
                ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True
            )
        except Exception as e:
            print(f"[DataLoader] yf.download failed ({e}), retrying via Ticker.history...")

        # Fallback 2: Ticker.history() uses a different code path — avoids some rate limits
        if raw is None or raw.empty:
            try:
                t = yf.Ticker(ticker)
                raw = t.history(start=start, end=end, interval=interval, auto_adjust=True)
            except Exception as e2:
                print(f"[DataLoader] Ticker.history also failed: {e2}")

        # Fallback 3: Direct Yahoo v8 API bypass
        if raw is None or raw.empty:
            print(f"[DataLoader] Trying direct Yahoo v8 API for {ticker}...")
            raw = self._fetch_direct_yahoo(ticker, start, end, interval)

        if raw is None or raw.empty:
            print(f"[DataLoader] No data returned for {ticker} ({start} to {end})")
            return None

        # Normalize columns — handle both flat and MultiIndex (yfinance >= 0.2.x)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in raw.columns]

        # Ensure standard columns exist
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(raw.columns)
        if missing:
            print(f"[DataLoader] Missing columns: {missing}")
            return None

        df = raw[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index)
        df["timestamp"] = df.index
        df = df.dropna(subset=["open", "high", "low", "close"])

        print(f"[DataLoader] Loaded {len(df)} bars for {symbol} ({ticker})")

        try:
            df.to_csv(cache_file, index=False)
            print(f"[DataLoader] Cached to {cache_file.name}")
        except Exception as e:
            print(f"[DataLoader] Cache write failed (non-fatal): {e}")

        return df

    def load_multi(
        self, symbols: List[str], start: str, end: str, interval: str = "1d"
    ) -> Dict[str, pd.DataFrame]:
        """Load multiple symbols. Returns dict of {symbol: DataFrame}."""
        result = {}
        for sym in symbols:
            df = self.load(sym, start, end, interval)
            if df is not None:
                result[sym] = df
        return result

    def get_multiplier(self, symbol: str) -> float:
        """Return contract multiplier for position sizing."""
        return CONTRACT_MULTIPLIERS.get(symbol.upper(), 1.0)
