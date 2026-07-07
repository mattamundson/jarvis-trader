"""Corey Rangefinder v2 — range-expansion / value strategy.

Reuses ``rangefinder.compute_rangefinder``.

  * breakout : on a new range expansion (rf_expansion_up/down) trade in the
               breakout direction; target a 1x range extension, stop at the
               range POC (midpoint).
  * fade     : at the range VAH/VAL edge, fade back toward POC; stop beyond the
               range extreme.

The expansion/level columns are evaluated on the signal bar's close; the
Backtester enters next-bar open. One entry per session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.rangefinder import compute_rangefinder
from backtest.studies._common import (
    atr_5m,
    clamp_stop_for_rr,
    empty_contract,
    restrict_rth,
    session_dates,
    sides_ok,
)

MODES = ["breakout", "fade"]


def grid(mode: str) -> list[dict]:
    return [{"expansion_multiple": m} for m in (1.0, 1.5)]


def generate(df: pd.DataFrame, mode: str = "breakout", expansion_multiple: float = 1.5) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    rth = restrict_rth(df)
    if rth.empty:
        return empty_contract(rth)
    rf = compute_rangefinder(rth, expansion_multiple=expansion_multiple)
    rf["atr"] = atr_5m(rf)
    sd = session_dates(rf.index).values

    closev = rf["close"].to_numpy(float)
    rhi = rf["rf_range_high"].to_numpy(float)
    rlo = rf["rf_range_low"].to_numpy(float)
    poc = rf["rf_range_poc"].to_numpy(float)
    vah = rf["rf_vah"].to_numpy(float)
    val = rf["rf_val"].to_numpy(float)
    exp_up = rf["rf_expansion_up"].to_numpy(bool)
    exp_dn = rf["rf_expansion_down"].to_numpy(bool)

    n = len(rf)
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
        rng = rhi[i] - rlo[i] if np.isfinite(rhi[i]) and np.isfinite(rlo[i]) else np.nan
        if not np.isfinite(rng) or rng <= 0 or not np.isfinite(poc[i]):
            continue
        if mode == "breakout":
            if exp_up[i]:
                direction, s = "long", "BULLISH"
                target = rhi[i] + rng
                stp = poc[i]
            elif exp_dn[i]:
                direction, s = "short", "BEARISH"
                target = rlo[i] - rng
                stp = poc[i]
            else:
                continue
        else:  # fade
            if np.isfinite(vah[i]) and closev[i] >= vah[i]:
                direction, s = "short", "BEARISH"
                target = poc[i]
                stp = rhi[i]
            elif np.isfinite(val[i]) and closev[i] <= val[i]:
                direction, s = "long", "BULLISH"
                target = poc[i]
                stp = rlo[i]
            else:
                continue
        if abs(target - closev[i]) < 1e-9:
            continue
        stp = clamp_stop_for_rr(closev[i], target, stp, direction)
        if not sides_ok(closev[i], target, stp, direction):
            continue
        bias[i], entry[i] = s, "ENTRY_NOW"
        stop[i] = stp
        t1[i] = target
        t2[i] = closev[i] + (target - closev[i]) * 1.5
        fired.add(sess)

    rf["entry_signal"] = entry
    rf["bias"] = bias
    rf["stop_level"] = stop
    rf["target_1"] = t1
    rf["target_2"] = t2
    rf["target_3"] = t2
    rf["regime"] = ""
    rf["exit_signal"] = "NO_EXIT"
    return rf
