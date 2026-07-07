"""
analytics.regime — shared regime / bias helpers for JARVIS reports.

Extracted from daily_post_trade_report.py (outlook section) so both the
post-trade report and the morning briefing can share the same logic without
duplication.

Public API
----------
load_recent_bars(symbol, n_bars, db_path)  -> pd.DataFrame | None
compute_bar_regime(symbol, df)             -> dict  (one row per symbol)

The dict returned by compute_bar_regime has keys:
  regime   str   TRENDING_BULL | RANGE_BOUND | UNKNOWN
  bias     str   STRONG_BULL | STRONG_BEAR | NEUTRAL | UNKNOWN
  close    float | None
  atr      float | None
  sma_fast float | None
  sma_slow float | None
  fast     int
  slow     int
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Default DB path — scripts override this via the db_path param.
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db"


def load_recent_bars(
    symbol: str,
    n_bars: int,
    db_path: Path | None = None,
) -> pd.DataFrame | None:
    """
    Load the most recent *n_bars* 1h OHLCV rows for *symbol* from SQLite.

    Queries market_data_bars first; falls back to legacy table names.
    Returns None if no data found or DB unavailable.
    """
    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(str(path))

        # Tier 1: canonical table (migration_024)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_data_bars'"
        )
        if cur.fetchone():
            df = pd.read_sql_query(
                """
                SELECT ts_utc AS timestamp, open, high, low, close, volume
                FROM market_data_bars
                WHERE symbol = ? AND interval = '1h'
                ORDER BY ts_utc DESC
                LIMIT ?
                """,
                con,
                params=(symbol.upper(), n_bars),
                parse_dates=["timestamp"],
            )
            if not df.empty:
                con.close()
                return df.sort_values("timestamp").reset_index(drop=True)

        # Tier 2: legacy table names
        for tbl in ("market_data", "bars", "ohlcv"):
            cur = con.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'"
            )
            if cur.fetchone():
                df = pd.read_sql_query(
                    f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {tbl}
                    WHERE symbol = ? AND interval = '1h'
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    con,
                    params=(symbol, n_bars),
                    parse_dates=["timestamp"],
                )
                if not df.empty:
                    con.close()
                    return df.sort_values("timestamp").reset_index(drop=True)
        con.close()
    except Exception as exc:
        logger.debug("load_recent_bars failed for %s: %s", symbol, exc)
    return None


def compute_bar_regime(
    symbol: str,
    df: pd.DataFrame,
    fast: int | None = None,
    slow: int | None = None,
) -> dict[str, Any]:
    """
    Compute the current regime / bias state from a bar DataFrame.

    Parameters
    ----------
    symbol : str
        Instrument symbol (used to look up default SMA params from SMA_TREND_PARAMS).
    df : pd.DataFrame
        Must have columns: open, high, low, close, volume.
        Must be sorted ascending by timestamp (oldest first).
    fast, slow : int | None
        Override SMA periods; if None, looked up from SMA_TREND_PARAMS.

    Returns
    -------
    dict with keys: regime, bias, close, atr, sma_fast, sma_slow, fast, slow
    """
    _unknown: dict[str, Any] = {
        "regime": "UNKNOWN",
        "bias": "UNKNOWN",
        "close": None,
        "atr": None,
        "sma_fast": None,
        "sma_slow": None,
        "fast": fast or 0,
        "slow": slow or 0,
    }

    if df is None or df.empty:
        return _unknown

    try:
        from backtest.trend_signals import SMA_TREND_PARAMS, generate_sma_trend_signals
    except ImportError:
        logger.warning("trend_signals not importable — regime classification unavailable")
        return _unknown

    params = SMA_TREND_PARAMS.get(symbol.upper(), {})
    _fast = fast or params.get("fast", 60)
    _slow = slow or params.get("slow", 200)

    if len(df) < _slow:
        return {
            **_unknown,
            "regime": "INSUFFICIENT_DATA",
            "fast": _fast,
            "slow": _slow,
        }

    try:
        df_sig = generate_sma_trend_signals(
            df,
            fast=_fast,
            slow=_slow,
            atr_trail_mult=params.get("atr_trail_mult", 2.0),
        )
        last = df_sig.iloc[-1]
        regime = last.get("regime", "UNKNOWN")
        bias = last.get("bias", "UNKNOWN")
        atr_val = last.get("atr", None)
        close_val = float(df["close"].iloc[-1])
        sma_f = float(df["close"].rolling(_fast).mean().iloc[-1]) if len(df) >= _fast else None
        sma_s = float(df["close"].rolling(_slow).mean().iloc[-1]) if len(df) >= _slow else None

        return {
            "regime": regime if pd.notna(regime) else "UNKNOWN",
            "bias": bias if pd.notna(bias) else "UNKNOWN",
            "close": close_val,
            "atr": float(atr_val) if atr_val is not None and pd.notna(atr_val) else None,
            "sma_fast": sma_f,
            "sma_slow": sma_s,
            "fast": _fast,
            "slow": _slow,
        }
    except Exception as exc:
        logger.debug("compute_bar_regime failed for %s: %s", symbol, exc)
        return {**_unknown, "fast": _fast, "slow": _slow}
