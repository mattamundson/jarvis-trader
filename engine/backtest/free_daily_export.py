"""Free deep daily OHLCV ingestion (yfinance primary, Stooq fallback).

The IB free-data ceiling binds only futures INTRADAY (~26mo 1h, ~4.4yr 1d for the
micros). Cash equities/ETFs have DECADES of free daily history via yfinance -- the
unlock that resolved the turn-of-month edge on 33yr of SPY. This tool pulls that
depth for the index/sector ETFs and writes it in the canonical cache-filename
convention so the discovery factory + backtests load it unchanged.

Writes to the MAIN-checkout cache (``engine/backtest/cache``) so the data lands
where the engine + factory read it and survives a worktree prune. Free data only;
no spend, no live anything.

    .venv/Scripts/python -m backtest.free_daily_export                  # default ETFs
    .venv/Scripts/python -m backtest.free_daily_export --symbols SPY QQQ
    .venv/Scripts/python -m backtest.free_daily_export --dry-run        # plan only
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

# Single source of truth for the cache-filename contract (ib_async is imported
# lazily inside that module, so this top-level import pulls in no IB deps).
from backtest.export_ibkr_history import CACHE_FILENAME_CONTRACT

# Canonical cache (main checkout) -- never the ephemeral worktree.
CACHE_DIR = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")
INTERVAL = "1d"
# Index/sector ETFs with deep free daily history. All 2-4 chars (contract-valid).
# Cross-asset breadth added 2026-06-26: bonds/silver/EM (TLT/SLV/EEM) + the
# duration/credit/intl family (XLU/HYG/LQD/EFA) that localized month-end to rates.
DEFAULT_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "GLD",
    "DIA",
    "TLT",
    "SLV",
    "EEM",
    "XLU",
    "HYG",
    "LQD",
    "EFA",
)
_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

Fetcher = tuple[str, Callable[[str], "pd.DataFrame | None"]]


# ── pure core (no IO) ────────────────────────────────────────────────────────
def cache_filename(symbol: str, start_date: str, end_date: str, interval: str = INTERVAL) -> str:
    """Build a cache filename and assert it satisfies the canonical contract."""
    name = f"{symbol}_{start_date}_{end_date}_{interval}.csv"
    if not CACHE_FILENAME_CONTRACT.match(name):
        raise ValueError(
            f"cache filename '{name}' violates the contract "
            "(<SYMBOL 2-4 chars>_<YYYY-MM-DD>_<YYYY-MM-DD>_<INTERVAL>.csv)"
        )
    return name


def normalize_daily(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize a yfinance/Stooq daily frame to the canonical cache schema.

    Accepts a DatetimeIndex'd frame (Stooq, possibly newest-first) or a Date-indexed
    yfinance frame whose columns may be a MultiIndex. Returns columns
    ``timestamp,open,high,low,close,volume`` with ISO-date timestamps, sorted
    oldest-first, deduped on date, with null-close rows dropped.
    """
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    lower = {str(c).lower() for c in df.columns}
    if not ({"date", "timestamp"} & lower):
        df = df.reset_index()  # bring the DatetimeIndex into a column
    df.columns = [str(c).lower() for c in df.columns]
    date_col = next((c for c in ("date", "timestamp", "index") if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"no date column found in {list(df.columns)}")

    out = pd.DataFrame()
    out["timestamp"] = pd.to_datetime(df[date_col]).dt.date.astype(str)
    for c in ("open", "high", "low", "close", "volume"):
        if c not in df.columns:
            raise ValueError(f"missing required column '{c}' in {list(df.columns)}")
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out = (
        out.dropna(subset=["close"])
        .drop_duplicates(subset=["timestamp"], keep="first")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return out[_COLS]


# ── source fetchers (network; thin, exercised live) ──────────────────────────
def fetch_yfinance(symbol: str) -> "pd.DataFrame | None":  # pragma: no cover - network
    import yfinance as yf

    return yf.download(symbol, period="max", interval="1d", auto_adjust=True, progress=False)


def fetch_stooq(symbol: str) -> "pd.DataFrame | None":  # pragma: no cover - network
    import pandas_datareader.data as web

    return web.DataReader(symbol, "stooq")  # newest-first; normalize_daily re-sorts


def _default_fetchers() -> list[Fetcher]:
    return [("yfinance", fetch_yfinance), ("stooq", fetch_stooq)]


# ── pipeline ─────────────────────────────────────────────────────────────────
def export_symbol(
    symbol: str,
    *,
    cache_dir: Path = CACHE_DIR,
    dry_run: bool = False,
    fetchers: Sequence[Fetcher] | None = None,
) -> dict:
    """Fetch (primary then fallback) -> normalize -> write one symbol's deep daily
    cache. Returns a stats dict; never raises on a single source's failure."""
    raw: pd.DataFrame | None = None
    source: str | None = None
    for name, fn in fetchers or _default_fetchers():
        try:
            r = fn(symbol)
        except Exception:  # noqa: BLE001 - source variance; fall through to next source
            continue
        if r is not None and len(r):
            raw, source = r, name
            break

    if raw is None or not len(raw):
        return {"symbol": symbol, "status": "NO_DATA"}

    norm = normalize_daily(raw)
    if norm.empty:
        return {"symbol": symbol, "status": "EMPTY_AFTER_NORM", "source": source}

    start, end = norm["timestamp"].iloc[0], norm["timestamp"].iloc[-1]
    fname = cache_filename(symbol, start, end)
    out = {
        "symbol": symbol,
        "status": "OK",
        "source": source,
        "rows": int(len(norm)),
        "start": start,
        "end": end,
        "file": fname,
    }
    if not dry_run:
        cache_dir.mkdir(parents=True, exist_ok=True)
        norm.to_csv(cache_dir / fname, index=False)
        out["path"] = str(cache_dir / fname)
    return out


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="free deep daily OHLCV ingestion")
    ap.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument("--dry-run", action="store_true", help="fetch + report, do not write")
    args = ap.parse_args()
    for sym in args.symbols:
        res = export_symbol(sym, cache_dir=args.cache_dir, dry_run=args.dry_run)
        print(json.dumps(res))


if __name__ == "__main__":  # pragma: no cover
    main()
