"""Regime-conditional performance breakdown for gate-v2 strategies.

DIAGNOSTIC ONLY — does not affect any gate pass/fail decision.

Breaks each strategy's profit factor / trade stats out by:
  - REGIME: TRENDING vs RANGE (ADX >= 25 => TRENDING)
  - VOLATILITY bucket: LOW / MID / HIGH (33rd/67th percentile terciles)

All functions are pure (no file I/O, no side effects).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

# Annualization constant for 5-min bars (same formula as trend_signals.py lines 115-116)
# 252 trading days * 6.5 trading hours * 12 bars/hour
_BARS_PER_YEAR_DEFAULT = 252 * 6.5 * 12  # ~19,656

_RV_WINDOW = 20  # rolling window for realized-vol calculation

_VOL_BUCKETS = ("LOW", "MID", "HIGH")


def tag_regime_vol(df: pd.DataFrame, *, bar_minutes: int = 5) -> pd.DataFrame:
    """Add two diagnostic columns to *df* (copy; does not mutate input).

    Columns added:
        rc_regime     : "TRENDING" if ADX >= 25 else "RANGE"
        rc_rv_ann_pct : 20-bar annualised realized vol expressed as a percent

    Args:
        df:           OHLCV DataFrame with a DatetimeIndex.
        bar_minutes:  Bar size in minutes (default 5).  Used to derive the
                      annualisation factor (bars / year).

    Returns:
        A copy of *df* with the two new columns appended.
    """
    from backtest.indicators import compute_adx

    df = df.copy()

    # --- ADX regime tag -------------------------------------------------
    try:
        adx_df = compute_adx(df)
        adx_series = adx_df["adx"]
    except Exception:
        # Degenerate data (e.g. constant prices) — default to RANGE.
        adx_series = pd.Series(0.0, index=df.index)

    df["rc_regime"] = adx_series.apply(
        lambda v: "TRENDING" if (pd.notna(v) and v >= 25) else "RANGE"
    )

    # --- Realized vol (exact formula from trend_signals.py lines 115-116) ---
    # bars_per_year  =  (6.5 h * 60 min) / bar_minutes * 252 trading days
    bars_per_year = (6.5 * 60.0 / bar_minutes) * 252
    log_ret = np.log(df["close"] / df["close"].shift(1))
    rv_ann = log_ret.rolling(_RV_WINDOW).std() * np.sqrt(bars_per_year) * 100.0
    df["rc_rv_ann_pct"] = rv_ann

    return df


def assign_vol_terciles(rv_series: pd.Series) -> tuple[float, float]:
    """Return (p33, p67) cut-points for splitting *rv_series* into LOW/MID/HIGH buckets.

    Handles:
        - NaN values (dropped before computing percentiles)
        - Constant / degenerate series (returns same value for both cut-points)
        - Fewer than 3 observations (returns (min, max) of the series)

    Returns:
        A tuple (p33, p67) where p33 <= p67.
    """
    clean = rv_series.dropna()
    if len(clean) == 0:
        return 0.0, 0.0
    if len(clean) < 3:
        mn, mx = float(clean.min()), float(clean.max())
        return mn, mx
    p33 = float(np.percentile(clean, 33.0))
    p67 = float(np.percentile(clean, 67.0))
    if p33 == p67:
        # Degenerate constant series — prevent empty buckets by widening slightly.
        # Both cut-points equal the constant; callers should treat as single bucket.
        pass
    return p33, p67


def _vol_bucket(rv_val: float, p33: float, p67: float) -> str:
    """Map a realized-vol value to a bucket label."""
    if math.isnan(rv_val):
        return "MID"  # missing vol defaults to mid bucket
    if rv_val <= p33:
        return "LOW"
    if rv_val <= p67:
        return "MID"
    return "HIGH"


def _pf_from_pnls(pnl_list: list[float]) -> float:
    """Profit factor from a list of PnL values. Returns inf if no losers."""
    gross_profit = sum(p for p in pnl_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_list if p <= 0))
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _bucket_stats(trades_in_bucket: list[Any]) -> dict:
    """Compute summary statistics for a list of Trade objects."""
    n = len(trades_in_bucket)
    if n == 0:
        return {}  # empty bucket — omit rather than crash
    pnls = [t.pnl for t in trades_in_bucket]
    wins = [p for p in pnls if p > 0]
    return {
        "trades": n,
        "win_rate": round(len(wins) / n, 4),
        "profit_factor": round(_pf_from_pnls(pnls), 4),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / n, 2),
    }


def bucket_trades(
    trades: list[Any],
    regime_by_entry: dict[Any, str],
    rv_by_entry: dict[Any, float],
    vol_edges: tuple[float, float],
) -> dict:
    """Group trades by (rc_regime, vol_bucket) and compute per-cell statistics.

    Args:
        trades:           List of Trade objects (must have .entry_date and .pnl).
        regime_by_entry:  Mapping entry_date -> "TRENDING"/"RANGE".
        rv_by_entry:      Mapping entry_date -> annualised RV percent (may be NaN).
        vol_edges:        (p33, p67) from assign_vol_terciles().

    Returns:
        dict with keys:
            by_regime_vol  : {f"{regime}_{vol_bucket}": {trades, win_rate, pf, total_pnl, avg_pnl}}
            by_regime      : {regime: stats}
            by_vol         : {vol_bucket: stats}
        Empty cells are omitted (not crashing).
    """
    p33, p67 = vol_edges

    by_regime_vol: dict[str, list] = {}
    by_regime: dict[str, list] = {}
    by_vol: dict[str, list] = {}

    for t in trades:
        key = t.entry_date
        regime = regime_by_entry.get(key, "RANGE")
        rv_val = rv_by_entry.get(key, float("nan"))
        vol_bkt = _vol_bucket(rv_val if rv_val is not None else float("nan"), p33, p67)

        cell = f"{regime}_{vol_bkt}"
        by_regime_vol.setdefault(cell, []).append(t)
        by_regime.setdefault(regime, []).append(t)
        by_vol.setdefault(vol_bkt, []).append(t)

    return {
        "by_regime_vol": {k: _bucket_stats(v) for k, v in by_regime_vol.items() if v},
        "by_regime": {k: _bucket_stats(v) for k, v in by_regime.items() if v},
        "by_vol": {k: _bucket_stats(v) for k, v in by_vol.items() if v},
    }
