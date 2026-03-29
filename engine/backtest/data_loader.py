"""
JARVIS TRADER — Backtest Data Loader
Fetches historical OHLCV data via yfinance with futures symbol mapping.
Results are cached to disk to avoid Yahoo Finance rate limits on repeated runs.
"""
from __future__ import annotations
import yfinance as yf
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict

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
    "MES": 5.0,    # $5 per point
    "ES": 50.0,    # $50 per point
    "MNQ": 2.0,    # $2 per point
    "NQ": 20.0,    # $20 per point
    "MCL": 100.0,  # $100 per barrel (micro = 100 barrels)
    "CL": 1000.0,  # $1000 per barrel
    "MGC": 10.0,   # $10 per oz
    "GC": 100.0,   # $100 per oz
    "M2K": 5.0,    # $5 per point
    "RTY": 50.0,   # $50 per point
    "MYM": 0.5,    # $0.50 per point
    "YM": 5.0,     # $5 per point
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

    def load(
        self,
        symbol: str,
        start: str,
        end: str,
        interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data for a symbol.
        Maps futures symbols to yfinance format automatically.
        Returns DataFrame with lowercase columns: open, high, low, close, volume, timestamp.
        Caches results to disk to avoid Yahoo Finance rate limits on repeated runs.
        """
        cache_file = self._cache_path(symbol, start, end, interval)

        # Check primary cache path first, then fall back to alternate naming patterns
        cache_to_try = cache_file if cache_file.exists() else self._find_alternate_cache(
            symbol, start, end, interval
        )

        if cache_to_try is not None:
            try:
                df = pd.read_csv(cache_to_try, parse_dates=["timestamp"])
                df = df.set_index("timestamp")
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
                ticker,
                start=start,
                end=end,
                interval=interval,
                progress=False,
                auto_adjust=True
            )
        except Exception as e:
            print(f"[DataLoader] yf.download failed ({e}), retrying via Ticker.history...")

        # Fallback: Ticker.history() uses a different code path — avoids some rate limits
        if raw is None or raw.empty:
            try:
                t = yf.Ticker(ticker)
                raw = t.history(start=start, end=end, interval=interval, auto_adjust=True)
            except Exception as e2:
                print(f"[DataLoader] Ticker.history also failed: {e2}")
                return None

        if raw is None or raw.empty:
            print(f"[DataLoader] No data returned for {ticker} ({start} to {end})")
            return None

        # Normalize columns — handle both flat and MultiIndex (yfinance >= 0.2.x)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() if isinstance(c, str) else str(c).lower()
                           for c in raw.columns]

        # Ensure standard columns exist
        required = {'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(raw.columns)
        if missing:
            print(f"[DataLoader] Missing columns: {missing}")
            return None

        df = raw[['open', 'high', 'low', 'close', 'volume']].copy()
        df.index = pd.to_datetime(df.index)
        df['timestamp'] = df.index
        df = df.dropna(subset=['open', 'high', 'low', 'close'])

        print(f"[DataLoader] Loaded {len(df)} bars for {symbol} ({ticker})")

        try:
            df.to_csv(cache_file, index=False)
            print(f"[DataLoader] Cached to {cache_file.name}")
        except Exception as e:
            print(f"[DataLoader] Cache write failed (non-fatal): {e}")

        return df

    def load_multi(
        self,
        symbols: List[str],
        start: str,
        end: str,
        interval: str = "1d"
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
