"""Saty ATR Levels — mechanical strategy (study-framework reference module).

This is the reference implementation that proves the generic
``study_wfo_runner`` is faithful: run through the runner it must reproduce the
standalone Saty WFO verdicts (PR #46). Mechanics are identical to that PR:
prior-session-close anchor, daily Wilder ATR(14) shifted one session (no
look-ahead), +/-0.236 ATR call/put triggers, ATR-fib target bands, and the
day-range-consumed exhaustion filter. GO (trigger-break) + FADE (band reversion).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import ema_ribbon
from backtest.studies._common import (
    atr_5m,
    attach_session_anchors,
    empty_contract,
    restrict_rth,
)

TRIGGER_RATIO = 0.236

MODES = ["go", "fade"]


def grid(mode: str) -> list[dict]:
    if mode == "go":
        return [
            {"target_ratio": tr, "ribbon_filter": rb}
            for tr in (0.618, 1.0) for rb in (False, True)
        ]
    return [
        {"entry_band": eb, "min_range_consumed": mr}
        for eb in (1.0, 1.236) for mr in (0.7, 0.9)
    ]


def generate(
    df: pd.DataFrame,
    mode: str = "go",
    target_ratio: float = 1.0,
    ribbon_filter: bool = False,
    entry_band: float = 1.0,
    min_range_consumed: float = 0.7,
    max_range_consumed: float = 1.0,
    atr_period: int = 14,
) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    rth = restrict_rth(df)
    if rth.empty:
        return empty_contract(rth)
    rth = attach_session_anchors(rth, atr_period=atr_period)
    rth["atr"] = atr_5m(rth)

    ema8, ema21, ema34 = ema_ribbon(rth["close"])
    rb_bull = ((ema8 > ema21) & (ema21 > ema34)).to_numpy(bool)
    rb_bear = ((ema8 < ema21) & (ema21 < ema34)).to_numpy(bool)

    anchor = rth["anchor"]
    day_atr = rth["day_atr"]
    close = rth["close"]
    valid = (anchor.notna() & day_atr.notna() & (day_atr > 0)).to_numpy(bool)

    callv = (anchor + TRIGGER_RATIO * day_atr).to_numpy(float)
    putv = (anchor - TRIGGER_RATIO * day_atr).to_numpy(float)
    upbv = (anchor + entry_band * day_atr).to_numpy(float)
    dnbv = (anchor - entry_band * day_atr).to_numpy(float)
    rused = ((close - anchor).abs() / day_atr.where(day_atr > 0, np.nan)).to_numpy(float)

    closev = close.to_numpy(float)
    anchorv = anchor.to_numpy(float)
    atr_d = day_atr.to_numpy(float)
    sessions = rth["__session"].to_numpy()

    n = len(rth)
    bias = np.full(n, "NEUTRAL", dtype=object)
    entry = np.full(n, "NO_TRADE", dtype=object)
    stop = np.full(n, np.nan)
    t1 = np.full(n, np.nan)
    t2 = np.full(n, np.nan)
    fired: set = set()

    for i in range(n):
        if not valid[i]:
            continue
        sess = sessions[i]
        if sess in fired:
            continue
        atr = atr_d[i]
        if mode == "go":
            if rused[i] >= max_range_consumed:
                continue
            long_ok = closev[i] > callv[i] and (not ribbon_filter or rb_bull[i])
            short_ok = closev[i] < putv[i] and (not ribbon_filter or rb_bear[i])
            if long_ok:
                bias[i], entry[i] = "BULLISH", "ENTRY_NOW"
                stop[i] = anchorv[i]
                t1[i] = anchorv[i] + target_ratio * atr
                t2[i] = anchorv[i] + (target_ratio + 0.5) * atr
                fired.add(sess)
            elif short_ok:
                bias[i], entry[i] = "BEARISH", "ENTRY_NOW"
                stop[i] = anchorv[i]
                t1[i] = anchorv[i] - target_ratio * atr
                t2[i] = anchorv[i] - (target_ratio + 0.5) * atr
                fired.add(sess)
        else:  # fade
            if rused[i] < min_range_consumed:
                continue
            if closev[i] >= upbv[i]:
                bias[i], entry[i] = "BEARISH", "ENTRY_NOW"
                stop[i] = anchorv[i] + (entry_band + 0.5) * atr
                t1[i] = anchorv[i]
                t2[i] = anchorv[i] - 0.236 * atr
                fired.add(sess)
            elif closev[i] <= dnbv[i]:
                bias[i], entry[i] = "BULLISH", "ENTRY_NOW"
                stop[i] = anchorv[i] - (entry_band + 0.5) * atr
                t1[i] = anchorv[i]
                t2[i] = anchorv[i] + 0.236 * atr
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
