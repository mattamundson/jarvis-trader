"""KAMA / NextSignal Momentum — adaptive-MA cross strategy.

Reuses ``indicators.kama`` (period=10). KAMA is computed on the full continuous
series; entries are taken on RTH bars only.

  * go : close crossing ABOVE KAMA -> long; crossing BELOW -> short. ATR
         stop/target. One entry per session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import kama
from backtest.studies._common import atr_5m, empty_contract, restrict_rth, session_dates

MODES = ["go"]


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
    k = kama(work["close"], period=10)
    work["__k"] = k
    work["__above"] = (work["close"] > k)
    work["__above_prev"] = work["__above"].shift(1)

    rth = restrict_rth(work)
    if rth.empty:
        return empty_contract(rth)
    rth["atr"] = atr_5m(rth)
    sd = session_dates(rth.index).values

    closev = rth["close"].to_numpy(float)
    atrv = rth["atr"].to_numpy(float)
    above = rth["__above"].to_numpy()
    above_prev = rth["__above_prev"].to_numpy()
    kv = rth["__k"].to_numpy(float)

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
        if not (np.isfinite(atr) and atr > 0 and np.isfinite(kv[i])):
            continue
        if above_prev[i] is None or (isinstance(above_prev[i], float) and np.isnan(above_prev[i])):
            continue
        cross_up = bool(above[i]) and not bool(above_prev[i])
        cross_dn = (not bool(above[i])) and bool(above_prev[i])
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
