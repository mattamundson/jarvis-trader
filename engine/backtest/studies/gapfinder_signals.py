"""Corey Gapfinder — gap-fill mechanical strategy.

Reuses ``gapfinder.compute_gaps`` (gap zones defined off the prior close, so no
look-ahead). Gaps act as magnets: an unfilled gap is a price target.

  * Unfilled gap-UP (price gapped up; zone [prior_close, open]) -> fade SHORT
    toward the gap bottom (prior_close), entered when price sits above the gap.
  * Unfilled gap-DOWN -> LONG toward the gap top (prior_close), entered when
    price sits below the gap.

Stop sits beyond the gap origin; clamped so R:R clears the Backtester floor.
One entry per session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.gapfinder import compute_gaps
from backtest.studies._common import (
    atr_5m,
    clamp_stop_for_rr,
    empty_contract,
    restrict_rth,
    session_dates,
    sides_ok,
)

MODES = ["fill"]


def grid(mode: str) -> list[dict]:
    return [{"min_gap_pct": g} for g in (0.001, 0.002)]


def _gap_signals(df: pd.DataFrame, min_gap_pct: float) -> pd.DataFrame:
    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index)
    gapped = compute_gaps(work, min_gap_pct=min_gap_pct)
    rth = restrict_rth(gapped)
    if rth.empty:
        return empty_contract(restrict_rth(df))
    rth["atr"] = atr_5m(rth)
    sd = session_dates(rth.index).values

    closev = rth["close"].to_numpy(float)
    gu_top = rth["gap_up_top"].to_numpy(float)
    gu_bot = rth["gap_up_bottom"].to_numpy(float)
    gd_top = rth["gap_down_top"].to_numpy(float)
    gd_bot = rth["gap_down_bottom"].to_numpy(float)

    n = len(rth)
    bias = np.full(n, "NEUTRAL", dtype=object)
    entry = np.full(n, "NO_TRADE", dtype=object)
    stop = np.full(n, np.nan)
    t1 = np.full(n, np.nan)
    t2 = np.full(n, np.nan)
    fired: set = set()

    for i in range(n):
        sess = sd[i]
        if sess in fired:
            continue
        # Prefer the gap the price is positioned to fill.
        if np.isfinite(gu_bot[i]) and closev[i] > gu_top[i]:
            # price above an unfilled gap-up -> fade short toward gap bottom
            direction, s = "short", "BEARISH"
            target = gu_bot[i]
            stp = gu_top[i] + (gu_top[i] - gu_bot[i])  # beyond gap origin
        elif np.isfinite(gd_top[i]) and closev[i] < gd_bot[i]:
            # price below an unfilled gap-down -> long toward gap top
            direction, s = "long", "BULLISH"
            target = gd_top[i]
            stp = gd_bot[i] - (gd_top[i] - gd_bot[i])
        else:
            continue
        if not np.isfinite(target) or abs(target - closev[i]) < 1e-9:
            continue
        stp = clamp_stop_for_rr(closev[i], target, stp, direction)
        if not sides_ok(closev[i], target, stp, direction):
            continue
        bias[i], entry[i] = s, "ENTRY_NOW"
        stop[i] = stp
        t1[i] = target
        t2[i] = closev[i] + (target - closev[i]) * 1.5
        fired.add(sess)

    rth["entry_signal"] = entry
    rth["bias"] = bias
    rth["stop_level"] = stop
    rth["target_1"] = t1
    rth["target_2"] = t2
    rth["target_3"] = t2
    rth["regime"] = ""
    rth["exit_signal"] = "NO_EXIT"
    return rth


def generate(df: pd.DataFrame, mode: str = "fill", min_gap_pct: float = 0.001) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    return _gap_signals(df, min_gap_pct)
