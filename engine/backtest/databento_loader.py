"""
JARVIS TRADER — Databento Loader (research data upgrade)

Fetches deep CME futures history (16+ years) from Databento, parallel to the
existing Polygon loader. Same output contract as `data_loader.py`:
    pd.DataFrame with DatetimeIndex + open/high/low/close/volume
(optionally + bid/ask/depth columns for the SOTA execution layer).

WHY (see docs/databento-integration-plan.md):
  - Polygon limit=50000 caps ~2y of 1h bars -> INSUFFICIENT_SAMPLE wall
  - Databento: 16+ years CME history, MBO/MBP depth for MEASURED impact,
    point-in-time instrument defs (no look-ahead), smart rollover symbology

USAGE:
    # set DATABENTO_API_KEY in engine/.env (never commit)
    from backtest.databento_loader import fetch_ohlcv
    df = fetch_ohlcv("MES", start="2015-01-01", end="2026-08-04", interval="1h")

    # returns an empty DataFrame + prints a clear message when no key / no pkg

NOTE: This is a research-data loader only. It never touches live/paper
trading. Runners opt into it via the `source` seam; default remains polygon.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Dataset code for CME Globex (CME + CBOT + NYMEX + COMEX futures/options)
DATASET = "GLBX.MDP3"

# Micro futures -> Databento parent symbology (smart rollover handled by
# stype_in="parent" so the continuous series is built without look-ahead)
SYMBOL_MAP: dict[str, str] = {
    "MES": "MES.FUT",
    "MNQ": "MNQ.FUT",
    "MCL": "MCL.FUT",
    "MGC": "MGC.FUT",
    "M2K": "M2K.FUT",
    "MYM": "MYM.FUT",
    "ES": "ES.FUT",
    "NQ": "NQ.FUT",
    "CL": "CL.FUT",
    "GC": "GC.FUT",
    "RTY": "RTY.FUT",
    "YM": "YM.FUT",
    "SI": "SI.FUT",
    "ZB": "ZB.FUT",
    "ZN": "ZN.FUT",
}

# Databento OHLCV schemas by interval (bar schemas exist for 1m/1h/1d etc.)
_SCHEMA_BY_INTERVAL: dict[str, str] = {
    "1m": "ohlcv-1m",
    "5m": "ohlcv-5m",
    "15m": "ohlcv-15m",
    "30m": "ohlcv-30m",
    "1h": "ohlcv-1h",
    "1d": "ohlcv-1d",
}

# Where fetched frames are cached (same dir as Polygon caches, distinct prefix)
CACHE_DIR = Path(__file__).parent / "cache"


def _api_key() -> str:
    if not os.environ.get("DATABENTO_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(".env load skipped: %s", exc)
    return os.environ.get("DATABENTO_API_KEY", "").strip()


def _db_available() -> bool:
    try:
        import databento  # noqa: F401

        return True
    except ImportError:
        return False


def fetch_ohlcv(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1h",
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV for a JARVIS symbol from Databento, cached to CSV.

    Returns a DataFrame with the runner-standard contract (lowercase cols,
    DatetimeIndex 'timestamp', sorted). Returns empty DataFrame (with a
    printed reason) if: no API key, package missing, or fetch fails.
    """
    sym_up = symbol.upper()
    db_sym = SYMBOL_MAP.get(sym_up, f"{sym_up}.FUT")
    # Continuous symbology: [ROOT].[ROLL_RULE].[RANK] -- stype_in="parent"
    # returns EVERY constituent contract AND calendar-spread instruments
    # (e.g. "MGCG5-MGCJ5", which legitimately prints negative prices), so a
    # single "deep" fetch must use the continuous lead-month symbol instead.
    # ROLL_RULE "c" = calendar (nearest expiry), RANK 0 = lead month.
    db_root = db_sym.split(".")[0]
    db_cont = f"{db_root}.c.0"
    schema = _SCHEMA_BY_INTERVAL.get(interval, "ohlcv-1h")

    if use_cache:
        cached = _find_cache(sym_up, start, end, interval)
        if cached is not None:
            print(f"[DatabentoLoader] Using cached {cached.name}")
            return _read_cache(cached)

    key = _api_key()
    if not key or key == "your_databento_key_here":
        print("[DatabentoLoader] DATABENTO_API_KEY not set — cannot fetch from Databento.")
        print("  Add to engine/.env: DATABENTO_API_KEY=...  (https://databento.com)")
        return pd.DataFrame()

    if not _db_available():
        print("[DatabentoLoader] databento package not installed: pip install databento")
        return pd.DataFrame()

    try:
        import databento as db

        client = db.Historical(key)
        print(
            f"[DatabentoLoader] Fetching {sym_up} ({db_sym}) {schema} "
            f"{start} -> {end} from {DATASET}..."
        )
        data = client.timeseries.get_range(
            dataset=DATASET,
            schema=schema,
            symbols=db_cont,
            stype_in="continuous",
            start=start,
            end=end,
        )
        df = data.to_df()
        if df is None or df.empty:
            print(f"[DatabentoLoader] Databento returned no rows for {sym_up}")
            return pd.DataFrame()

        # Normalize to runner contract
        if df.index.name and df.index.name.lower() in ("ts_event", "ts", "timestamp"):
            # databento's to_df() returns the event time as the index
            # (named ts_event) rather than a column — pull it back into a
            # column so the rest of this function can treat it uniformly.
            df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        if "ts_event" in df.columns:
            df["timestamp"] = pd.to_datetime(df["ts_event"], utc=True)
        elif "timestamp" not in df.columns and "ts" in df.columns:
            df["timestamp"] = pd.to_datetime(df["ts"], utc=True)
        if "timestamp" not in df.columns:
            print(f"[DatabentoLoader] No timestamp column in response for {sym_up}")
            return pd.DataFrame()

        # OHLCV schema frames are already one row per bar; keep o/h/l/c/v
        keep = ["timestamp", "open", "high", "low", "close", "volume"]
        existing = [c for c in keep if c in df.columns]
        df = df[existing].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()

        if use_cache and len(df):
            _write_cache(df, sym_up, start, end, interval)
        print(f"[DatabentoLoader] Databento: {len(df)} bars for {sym_up} ({interval})")
        return df

    except Exception as exc:
        print(f"[DatabentoLoader] Databento fetch failed: {exc}")
        return pd.DataFrame()


def fetch_with_depth(
    symbol: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Fetch MBP-1 (10-level) data for a recent window — measured impact.

    Returns frame with timestamp + bid/ask levels (or empty + reason).
    Used by the SOTA execution layer to replace estimated POV impact with
    measured depth-at-touch.
    """
    sym_up = symbol.upper()
    db_sym = SYMBOL_MAP.get(sym_up, f"{sym_up}.FUT")
    key = _api_key()
    if not key:
        print("[DatabentoLoader] DATABENTO_API_KEY not set (depth fetch).")
        return pd.DataFrame()
    if not _db_available():
        print("[DatabentoLoader] databento package not installed.")
        return pd.DataFrame()

    try:
        import databento as db

        client = db.Historical(key)
        data = client.timeseries.get_range(
            dataset=DATASET,
            schema="mbp-1",
            symbols=db_sym,
            stype_in="parent",
            start=start,
            end=end,
        )
        df = data.to_df()
        if df is None or df.empty:
            return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        df["timestamp"] = pd.to_datetime(df.get("ts_event", df.index))
        return df.set_index("timestamp").sort_index()
    except Exception as exc:
        print(f"[DatabentoLoader] Depth fetch failed: {exc}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Cache helpers (same dir + contract as the Polygon loader)
# ---------------------------------------------------------------------------


def _cache_path(symbol: str, start: str, end: str, interval: str) -> Path:
    safe = f"{symbol}_{start}_{end}_{interval}".replace("/", "-").replace(":", "-")
    return CACHE_DIR / f"{safe}.csv"


def _find_cache(symbol: str, start: str, end: str, interval: str) -> Optional[Path]:
    # Caches are written from a UTC DatetimeIndex (see _write_cache), so CSV
    # timestamps round-trip as tz-aware (+00:00). Compare in tz-aware UTC —
    # a naive pd.Timestamp(start) used to raise TypeError against tz-aware
    # data, which the except-continue swallowed silently, so deep 2015-*
    # caches NEVER matched and every deep fetch re-downloaded from Databento.
    start_dt = pd.Timestamp(start, tz="UTC")
    end_dt = pd.Timestamp(end, tz="UTC") - pd.Timedelta(days=3)
    for pat in (f"{symbol}_{interval}_*.csv", f"{symbol}_*_{interval}.csv"):
        for path in CACHE_DIR.glob(pat):
            try:
                tmp = pd.read_csv(path, usecols=["timestamp"], parse_dates=["timestamp"])
                ts = pd.to_datetime(tmp["timestamp"], utc=True)
                if ts.min() <= start_dt and ts.max() >= end_dt:
                    return path
            except Exception as exc:  # unreadable/partial cache: skip, never crash
                logger.debug("cache skip %s: %s", path.name, exc)
    return None


def _read_cache(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    return df.set_index(ts_col).sort_index()


def _write_cache(df: pd.DataFrame, symbol: str, start: str, end: str, interval: str) -> None:
    path = _cache_path(symbol, start, end, interval)
    out = df.reset_index()
    out.to_csv(path, index=False)
    print(f"[DatabentoLoader] Cached -> {path.name}")


if __name__ == "__main__":
    # Quick smoke test (no key = graceful message)
    print(f"API key present: {bool(_api_key())}")
    print(f"databento package: {_db_available()}")
    df = fetch_ohlcv("MGC", "2024-01-01", "2026-08-04", "1h")
    print(f"result rows: {len(df)}")
