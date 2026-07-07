"""Schaff Trend Cycle (STC) — momentum cross strategy.

Reuses ``indicators.stc`` (fast=23, slow=50, K=10, D=3 — Corey's params). STC is
computed on the full continuous series (so it sees overnight price), then entries
are taken on RTH bars only.

  * go : STC crossing UP out of oversold -> long; crossing DOWN out of
         overbought -> short. ATR stop/target. One entry per session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import stc
from backtest.studies._common import atr_5m, empty_contract, restrict_rth, session_dates

MODES = ["go"]

OVERSOLD = 25.0
OVERBOUGHT = 75.0


def grid(mode: str) -> list[dict]:
    return [
        {"stop_atr": sa, "target_atr": ta}
        for sa in (1.0, 1.5) for ta in (2.0, 3.0)
    ]


def generate(
    df: pd.DataFrame, mode: str = "go", stop_atr: float = 1.0, target_atr: float = 2.0
) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index)
    work["__stc"] = stc(work["close"])
    work["__stc_prev"] = work["__stc"].shift(1)

    rth = restrict_rth(work)
    if rth.empty:
        return empty_contract(rth)
    rth["atr"] = atr_5m(rth)
    sd = session_dates(rth.index).values

    closev = rth["close"].to_numpy(float)
    atrv = rth["atr"].to_numpy(float)
    cur = rth["__stc"].to_numpy(float)
    prev = rth["__stc_prev"].to_numpy(float)

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
        atr = atrv[i]
        if not (np.isfinite(atr) and atr > 0 and np.isfinite(cur[i]) and np.isfinite(prev[i])):
            continue
        cross_up = prev[i] <= OVERSOLD < cur[i]
        cross_dn = prev[i] >= OVERBOUGHT > cur[i]
        if cross_up:
            bias[i], entry[i] = "BULLISH", "ENTRY_NOW"
            stop[i] = closev[i] - stop_atr * atr
            t1[i] = closev[i] + target_atr * atr
            t2[i] = closev[i] + (target_atr + 1.0) * atr
            fired.add(sess)
        elif cross_dn:
            bias[i], entry[i] = "BEARISH", "ENTRY_NOW"
            stop[i] = closev[i] + stop_atr * atr
            t1[i] = closev[i] - target_atr * atr
            t2[i] = closev[i] - (target_atr + 1.0) * atr
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
