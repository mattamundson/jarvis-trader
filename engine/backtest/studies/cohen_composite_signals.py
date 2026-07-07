"""Cohen MES Composite — regime-weighted multi-factor strategy.

Faithful to COHEN_MES_COMPOSITE.ts: a regime-adaptive blend of three factors —
STC momentum, opening-range breakout (first 30 min RTH), and VWAP +/- ATR band
position. Weights shift with regime (trend vs range):

    trend : STC 0.60, ORB 0.30, VWAP 0.10
    range : STC 0.50, ORB 0.20, VWAP 0.30

Regime = trend when |close - VWAP| > 1 ATR, else range. Entry when the composite
score crosses +/- threshold (default 0.35). ATR stop/target. One entry per
session, only after the opening range is complete (no look-ahead). MES-tuned but
evaluated on all four symbols.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import compute_vwap, stc
from backtest.studies._common import (
    atr_5m,
    empty_contract,
    restrict_rth,
    session_dates,
    to_et,
)

MODES = ["composite"]

OR_MINUTES = 30  # opening-range window
TREND_W = {"stc": 0.60, "orb": 0.30, "vwap": 0.10}
RANGE_W = {"stc": 0.50, "orb": 0.20, "vwap": 0.30}


def grid(mode: str) -> list[dict]:
    return [
        {"threshold": th, "target_atr": ta}
        for th in (0.30, 0.40) for ta in (2.0, 3.0)
    ]


def generate(
    df: pd.DataFrame,
    mode: str = "composite",
    threshold: float = 0.35,
    target_atr: float = 2.0,
    stop_atr: float = 1.5,
) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index)
    work["__stc"] = stc(work["close"])

    rth = restrict_rth(work)
    if rth.empty:
        return empty_contract(rth)
    rth["atr"] = atr_5m(rth)
    rth["__vwap"] = compute_vwap(rth)
    sd = session_dates(rth.index).values
    et = to_et(rth.index)
    minute_of_day = np.asarray(et.hour * 60 + et.minute)
    open_min = 9 * 60 + 30

    # Opening range (first OR_MINUTES) high/low per session — known only after it
    # completes, so entries are gated to minute_of_day >= open_min + OR_MINUTES.
    or_done = minute_of_day >= (open_min + OR_MINUTES)
    or_high: dict = {}
    or_low: dict = {}
    highs = rth["high"].to_numpy(float)
    lows = rth["low"].to_numpy(float)
    for i in range(len(rth)):
        s = sd[i]
        if minute_of_day[i] < open_min + OR_MINUTES:
            or_high[s] = max(or_high.get(s, -np.inf), highs[i])
            or_low[s] = min(or_low.get(s, np.inf), lows[i])

    closev = rth["close"].to_numpy(float)
    atrv = rth["atr"].to_numpy(float)
    stcv = rth["__stc"].to_numpy(float)
    vwapv = rth["__vwap"].to_numpy(float)

    n = len(rth)
    bias = np.full(n, "NEUTRAL", dtype=object)
    entry = np.full(n, "NO_TRADE", dtype=object)
    stop = np.full(n, np.nan)
    t1 = np.full(n, np.nan)
    t2 = np.full(n, np.nan)
    regime_col = np.full(n, "", dtype=object)
    fired: set = set()

    for i in range(n):
        s = sd[i]
        if s in fired or not or_done[i]:
            continue
        atr = atrv[i]
        if not (np.isfinite(atr) and atr > 0 and np.isfinite(stcv[i]) and np.isfinite(vwapv[i])):
            continue
        orh = or_high.get(s, np.nan)
        orl = or_low.get(s, np.nan)
        if not (np.isfinite(orh) and np.isfinite(orl)):
            continue

        stc_dir = float(np.clip((stcv[i] - 50.0) / 50.0, -1.0, 1.0))
        if closev[i] > orh:
            orb_dir = 1.0
        elif closev[i] < orl:
            orb_dir = -1.0
        else:
            orb_dir = 0.0
        vwap_dir = float(np.clip((closev[i] - vwapv[i]) / atr, -1.0, 1.0))

        is_trend = abs(closev[i] - vwapv[i]) > atr
        w = TREND_W if is_trend else RANGE_W
        score = w["stc"] * stc_dir + w["orb"] * orb_dir + w["vwap"] * vwap_dir

        if score >= threshold:
            bias[i], entry[i] = "BULLISH", "ENTRY_NOW"
            stop[i] = closev[i] - stop_atr * atr
            t1[i] = closev[i] + target_atr * atr
            t2[i] = closev[i] + (target_atr + 1.0) * atr
            regime_col[i] = "trend" if is_trend else "range"
            fired.add(s)
        elif score <= -threshold:
            bias[i], entry[i] = "BEARISH", "ENTRY_NOW"
            stop[i] = closev[i] + stop_atr * atr
            t1[i] = closev[i] - target_atr * atr
            t2[i] = closev[i] - (target_atr + 1.0) * atr
            regime_col[i] = "trend" if is_trend else "range"
            fired.add(s)

    rth["entry_signal"] = entry
    rth["bias"] = bias
    rth["stop_level"] = stop
    rth["target_1"] = t1
    rth["target_2"] = t2
    rth["target_3"] = t2
    rth["regime"] = regime_col
    rth["exit_signal"] = "NO_EXIT"
    return rth
