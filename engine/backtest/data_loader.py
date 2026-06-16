"""
JARVIS TRADER — Backtest Data Loader
Fetches historical OHLCV data via Polygon.io with futures symbol mapping.
Results are cached to disk to avoid API rate limits on repeated runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


FUTURES_MAP: Dict[str, str] = {
    # Micro futures → Polygon continuous contract tickers
    "MES": "MES",
    "MNQ": "MNQ",
    "MCL": "MCL",
    "MGC": "MGC",
    "M2K": "M2K",
    "MYM": "MYM",
    # Standard futures
    "ES": "ES",
    "NQ": "NQ",
    "CL": "CL",
    "GC": "GC",
    "RTY": "RTY",
    "YM": "YM",
    "SI": "SI",
    "ZB": "ZB",
    "ZN": "ZN",
}

# Multipliers are derived from the canonical CONTRACT_SPECS source.
# See engine/backtest/contract_specs.py for the single source of truth.
from .contract_specs import CONTRACT_MULTIPLIERS  # noqa: E402,F401


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

    def _fetch_via_polygon(self, ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        """
        Fetch OHLCV data from Polygon.io REST API.
        Requires POLYGON_API_KEY env var or set in engine/.env.
        Free tier: 5 calls/min, unlimited history.
        """
        from datetime import datetime

        api_key = os.environ.get("POLYGON_API_KEY", "")
        if not api_key or api_key == "your_polygon_key_here":
            print("[DataLoader] POLYGON_API_KEY not set — cannot fetch from Polygon")
            return pd.DataFrame()

        try:
            from polygon import RESTClient
        except ImportError:
            print("[DataLoader] polygon-api-client not installed: pip install polygon-api-client")
            return pd.DataFrame()

        tf_map = {
            "1m": ("minute", 1),
            "5m": ("minute", 5),
            "15m": ("minute", 15),
            "30m": ("minute", 30),
            "1h": ("hour", 1),
            "1d": ("day", 1),
        }
        timespan, multiplier = tf_map.get(interval, ("hour", 1))

        print(f"[DataLoader] Fetching {ticker} from Polygon.io ({interval}, {start} -> {end})...")
        try:
            client = RESTClient(api_key)
            bars = []
            for agg in client.list_aggs(
                ticker,
                multiplier,
                timespan,
                start,
                end,
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
                print(f"[DataLoader] Polygon returned no bars for {ticker}")
                return pd.DataFrame()

            df = pd.DataFrame(bars)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp").sort_index()
            df["timestamp"] = df.index
            print(f"[DataLoader] Polygon: {len(df)} bars for {ticker}")
            return df

        except Exception as exc:
            print(f"[DataLoader] Polygon failed: {exc}")
            return pd.DataFrame()

    def _screen_bar_quality(
        self, df: Optional[pd.DataFrame], symbol: str, interval: str
    ) -> Optional[pd.DataFrame]:
        """Drop contaminated bars before the backtester ever sees them.

        Reuses the pure ``bar_quality_gate.screen_bars`` screen (the same logic
        that guards live storage) to catch the impossible-OHLC / range-explosion
        / lone-tick classes that produced the fake "PF 22" backtest edges.

        Unlike the live storage path — which defaults to *shadow* mode so prod
        rows are never silently dropped during rollout — backtests **always**
        drop rejected rows: a backtest computed on a known-poison tick is
        meaningless, so cleaning is non-negotiable. The drop is loud (printed),
        never silent. Honour the same ``BAR_QUALITY_GATE_ENABLED`` kill-switch.

        Screens on every load (not just on write) because cache files predate
        the gate and may already hold contamination from before it existed.
        """
        if df is None or df.empty:
            return df
        try:
            from data.bar_quality_gate import gate_enabled, screen_bars
        except Exception:
            return df
        if not gate_enabled():
            return df

        ts = df["timestamp"] if "timestamp" in df.columns else df.index
        vol = df["volume"] if "volume" in df.columns else [0] * len(df)
        # Row layout expected by screen_bars: (sym, interval, ts, o, h, l, c, vol, source, fetched_at)
        rows = [
            (symbol, interval, t, o, h, low, c, v, "backtest_cache", "")
            for t, o, h, low, c, v in zip(
                list(ts), df["open"], df["high"], df["low"], df["close"], list(vol), strict=True
            )
        ]
        rejects = screen_bars(rows)
        if not rejects:
            return df

        by_reason: Dict[str, int] = {}
        for rj in rejects:
            by_reason[rj.reason] = by_reason.get(rj.reason, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
        print(
            f"[DataLoader][bar_quality] {symbol} {interval} - DROPPED "
            f"{len(rejects)}/{len(df)} contaminated bars ({summary})"
        )
        bad = {rj.index for rj in rejects}
        keep_pos = [i for i in range(len(df)) if i not in bad]
        return df.iloc[keep_pos]

    def load(
        self, symbol: str, start: str, end: str, interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data for a symbol via Polygon.io.
        Maps futures symbols via FUTURES_MAP automatically.
        Returns DataFrame with lowercase columns: open, high, low, close, volume, timestamp.
        Caches results to disk to avoid API rate limits on repeated runs.
        Every returned frame is screened by the bar-quality gate first.
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
                return self._screen_bar_quality(df, symbol, interval)
            except Exception as e:
                print(f"[DataLoader] Cache read failed ({e}), re-fetching...")

        ticker = FUTURES_MAP.get(symbol.upper(), symbol)

        # Polygon free plan returns the WRONG asset for futures tickers
        # (e.g. CL = Colgate-Palmolive stock, not crude oil). Block the call
        # entirely for known-bad symbols. See market_data.POLYGON_FUTURES_BLOCKLIST
        # and docs/data-source-audit-2026-04-16.md (incident T1.1 / T1.5).
        try:
            from data.market_data import POLYGON_FUTURES_BLOCKLIST
        except ImportError:
            POLYGON_FUTURES_BLOCKLIST = frozenset()
        if symbol.upper() in POLYGON_FUTURES_BLOCKLIST or ticker.upper() in POLYGON_FUTURES_BLOCKLIST:
            print(
                f"[DataLoader] Polygon SKIPPED for {symbol} (futures, blocklisted "
                "since 2026-04-16 incident — Polygon free plan has no futures data). "
                "Use IBKR-sourced cache or upgrade plan."
            )
            return None

        raw = self._fetch_via_polygon(ticker, start, end, interval)

        if raw is None or raw.empty:
            print(f"[DataLoader] No data returned for {ticker} ({start} to {end})")
            return None

        # Normalize columns
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
        df = self._screen_bar_quality(df, symbol, interval)

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
