"""
JARVIS TRADER — Databento cross-check adapter
==============================================
Standalone, offline cross-check against CME's own GLBX.MDP3 feed for the
futures symbols JARVIS trades. Ships dark: with no DATABENTO_API_KEY set,
every entry point returns a clean "skipped" status and touches no data.
See docs/decisions/market-data-vendor-roadmap-2026-07-28.md for the context.

Intentionally NOT wired into MarketDataManager's live waterfall
(data/market_data.py). Unlike IBKR/Polygon/CSV cache, an unverified new
vendor must never silently become a fallback PRICE SOURCE feeding signals —
that is exactly how the Polygon CL=Colgate-Palmolive incident happened
(docs/data-source-audit-2026-04-16.md). Instead this is a standalone
comparison tool: pull Databento's own minute bars for a symbol, diff them
against whatever the SQLite bars cache already holds, and report divergence.
Pattern ported from amo-arbitrage's backend/cloud_feed.py adapter (also
built dark there), adapted from daily to minute OHLCV.

UNVERIFIED: the Databento symbology/schema below (stype_in="continuous",
"{root}.c.0", dataset GLBX.MDP3, schema "ohlcv-1m") is written from
documented API shape, not exercised against a live key. Confirm against
Databento's actual response the first time DATABENTO_API_KEY is set and
the `databento` package is installed.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DATABENTO_API_KEY = os.getenv("DATABENTO_API_KEY", "")

# CME Globex dataset covering CME/CBOT/NYMEX/COMEX — the exchanges JARVIS trades.
DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"

# Root symbol -> Databento continuous front-month symbol (stype_in="continuous").
# Mirrors FUTURES_MAP in market_data.py (micro contracts share the parent's price).
SYMBOL_MAP: dict[str, str] = {
    "ES": "ES.c.0", "MES": "ES.c.0",
    "NQ": "NQ.c.0", "MNQ": "NQ.c.0",
    "GC": "GC.c.0", "MGC": "GC.c.0",
    "CL": "CL.c.0", "MCL": "CL.c.0",
    "RTY": "RTY.c.0", "M2K": "RTY.c.0",
}


class DatabentoAdapter:
    """Minute-bar OHLCV adapter over Databento's Historical API.

    Import-safe: the `databento` SDK is only imported inside
    fetch_minute_bars, so this module loads fine without the package
    installed (mirrors amo-arbitrage's DatabentoAdapter).
    """

    name = "databento"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_minute_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        db_symbol = SYMBOL_MAP.get(symbol.upper())
        if db_symbol is None:
            raise ValueError(f"No Databento continuous-symbol mapping for {symbol!r}")
        try:
            import databento as db
        except ImportError as e:
            raise RuntimeError(
                "DATABENTO_API_KEY is set but the `databento` package is not "
                "installed. Add `databento` to requirements.txt and re-run."
            ) from e

        client = db.Historical(self.api_key)
        store = client.timeseries.get_range(
            dataset=DATASET,
            schema=SCHEMA,
            symbols=[db_symbol],
            stype_in="continuous",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )
        df = store.to_df()
        if df.empty:
            return df
        df = df.reset_index().rename(columns={"ts_event": "timestamp"})
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df.attrs["source"] = "databento"
        df.attrs["symbol"] = symbol
        return df


def get_adapter() -> Optional[DatabentoAdapter]:
    """Return the configured adapter, or None when dark (no key set)."""
    if not DATABENTO_API_KEY:
        return None
    return DatabentoAdapter(DATABENTO_API_KEY)


def reconcile_vs_cache(
    symbol: str,
    timeframe: str = "1m",
    lookback_days: int = 7,
    tolerance_pct: float = 0.1,
) -> dict:
    """Compare Databento's own minute bars against the SQLite bars cache
    (data/bars_repository.py) that IBKR/TV already populated for `symbol`.

    Returns a typed status dict, never raises — mirrors amo-arbitrage's
    reconcile_primary_vs_backup contract (status: skipped/no_cache/empty/
    no_overlap/error/compared).
    """
    adapter = get_adapter()
    if adapter is None:
        return {
            "status": "skipped",
            "reason": "DATABENTO_API_KEY not set -- cross-check is dark "
            "(see docs/decisions/market-data-vendor-roadmap-2026-07-28.md)",
        }

    try:
        from data.bars_repository import load_bars
    except Exception as e:
        return {"status": "error", "reason": f"bars_repository unavailable: {e}"}

    cached = load_bars(symbol, timeframe)
    if cached.empty:
        return {"status": "no_cache", "reason": f"no cached bars for {symbol}/{timeframe}"}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    try:
        live = adapter.fetch_minute_bars(symbol, start, end)
    except Exception as e:
        logger.error("Databento fetch failed for %s: %s", symbol, e)
        return {"status": "error", "reason": str(e)}
    if live.empty:
        return {"status": "empty", "reason": f"Databento returned 0 rows for {symbol}"}

    cached = cached.copy()
    cached["timestamp"] = pd.to_datetime(cached["timestamp"], utc=True)
    live["timestamp"] = pd.to_datetime(live["timestamp"], utc=True)
    merged = cached.merge(live, on="timestamp", suffixes=("_cache", "_databento"))
    if merged.empty:
        return {
            "status": "no_overlap",
            "cache_rows": len(cached),
            "databento_rows": len(live),
        }

    merged["div_pct"] = (
        (merged["close_databento"] - merged["close_cache"]).abs()
        / merged["close_cache"].abs().replace(0, pd.NA)
        * 100.0
    )
    over = int((merged["div_pct"] > tolerance_pct).sum())
    return {
        "status": "compared",
        "compared_bars": len(merged),
        "max_div_pct": round(float(merged["div_pct"].max()), 4),
        "mean_div_pct": round(float(merged["div_pct"].mean()), 4),
        "over_tolerance_bars": over,
        "tolerance_pct": tolerance_pct,
    }


def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Databento cross-check vs cached bars (market-data-vendor-roadmap)"
    )
    parser.add_argument("symbol", help="e.g. MES, MGC, MCL, MNQ")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--lookback", type=int, default=7)
    parser.add_argument("--tolerance", type=float, default=0.1)
    args = parser.parse_args()
    print(json.dumps(
        reconcile_vs_cache(args.symbol, args.timeframe, args.lookback, args.tolerance),
        indent=2,
    ))


if __name__ == "__main__":
    main()
