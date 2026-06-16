"""
analytics.regime_analysis — Regime-conditional returns analysis.

Public API
----------
regime_conditional_analysis(returns, regime_labels) -> dict

For each regime in [RISK_ON, RISK_OFF, NORMAL], slices ``returns`` where
``regime_labels == regime`` and computes via quantstats:

    sharpe, sortino, max_dd, win_rate, tail_ratio, skew, calmar, n_days

Regimes with fewer than MIN_OBS observations return
``{"n_days": N, "note": "insufficient data"}``.

The function is pure (Series in, dict out); no I/O.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Canonical regime labels expected by the spec.
KNOWN_REGIMES: tuple[str, ...] = ("RISK_ON", "RISK_OFF", "NORMAL")

# Minimum number of observations to compute meaningful statistics.
MIN_OBS: int = 5

# Annualisation factor (252 trading days).
_PERIODS_PER_YEAR: int = 252


def regime_conditional_analysis(
    returns: pd.Series,
    regime_labels: pd.Series,
) -> dict[str, Any]:
    """Compute per-regime quantstats metrics.

    Parameters
    ----------
    returns : pd.Series
        Daily return values (fractional; e.g. 0.01 = +1 %).
        Index should be a DatetimeIndex but any index works as long as it
        aligns with ``regime_labels``.
    regime_labels : pd.Series
        Per-day regime strings.  Only rows whose label is in
        ``KNOWN_REGIMES`` are considered.  Labels are uppercased before
        comparison so "risk_on" / "RISK_ON" both match.

    Returns
    -------
    dict  keyed by regime name.  Each value is either:

    * ``{"n_days": int, "sharpe": float|None, "sortino": float|None,
         "max_dd": float|None, "win_rate": float|None,
         "tail_ratio": float|None, "skew": float|None,
         "calmar": float|None}``
    * ``{"n_days": int, "note": "insufficient data"}``  (< MIN_OBS obs)
    * ``{"n_days": 0, "note": "no data"}``  (regime absent from labels)

    The top-level dict always contains all three canonical regime keys.
    An ``"_meta"`` sub-key carries overall alignment diagnostics.
    """
    try:
        import quantstats as qs
    except ImportError as exc:
        raise RuntimeError("quantstats is not installed in this venv") from exc

    # ------------------------------------------------------------------
    # 1. Normalise inputs
    # ------------------------------------------------------------------
    if returns is None or not isinstance(returns, pd.Series):
        returns = pd.Series(dtype=float)
    if regime_labels is None or not isinstance(regime_labels, pd.Series):
        regime_labels = pd.Series(dtype=str)

    # Drop NaN from returns before alignment
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

    # Uppercase regime labels; keep dtype=str
    regime_labels = regime_labels.dropna().astype(str).str.upper()

    # Align on index (inner join) so mismatched lengths are handled gracefully
    if returns.empty or regime_labels.empty:
        aligned_returns = pd.Series(dtype=float)
        aligned_labels = pd.Series(dtype=str)
    else:
        aligned = pd.DataFrame({"ret": returns, "regime": regime_labels}).dropna()
        aligned_returns = aligned["ret"]
        aligned_labels = aligned["regime"]

    n_aligned = len(aligned_returns)

    result: dict[str, Any] = {}

    for regime in KNOWN_REGIMES:
        mask = aligned_labels == regime
        slice_ret = aligned_returns[mask]
        n_days = int(mask.sum())

        if n_days == 0:
            result[regime] = {"n_days": 0, "note": "no data"}
            continue

        if n_days < MIN_OBS:
            result[regime] = {"n_days": n_days, "note": "insufficient data"}
            continue

        def _safe(fn, *args, **kwargs):
            """Call a qs scalar function; return None on any error or non-finite result."""
            try:
                val = fn(*args, **kwargs)
                if isinstance(val, pd.Series):
                    val = val.iloc[-1]
                if val is None or (isinstance(val, float) and not np.isfinite(val)):
                    return None
                return float(val)
            except Exception:
                return None

        result[regime] = {
            "n_days": n_days,
            "sharpe": _safe(
                qs.stats.sharpe,
                slice_ret,
                rf=0.0,
                periods=_PERIODS_PER_YEAR,
                annualize=True,
            ),
            "sortino": _safe(
                qs.stats.sortino,
                slice_ret,
                rf=0.0,
                periods=_PERIODS_PER_YEAR,
                annualize=True,
            ),
            "max_dd": _safe(qs.stats.max_drawdown, slice_ret),
            "win_rate": _safe(qs.stats.win_rate, slice_ret),
            "tail_ratio": _safe(qs.stats.tail_ratio, slice_ret),
            "skew": _safe(qs.stats.skew, slice_ret),
            "calmar": _safe(qs.stats.calmar, slice_ret, periods=_PERIODS_PER_YEAR),
        }

    result["_meta"] = {
        "n_returns": len(returns),
        "n_labels": len(regime_labels),
        "n_aligned": n_aligned,
        "known_regimes": list(KNOWN_REGIMES),
        "min_obs": MIN_OBS,
    }

    return result
