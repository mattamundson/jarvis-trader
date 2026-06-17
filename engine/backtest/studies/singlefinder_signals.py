"""Corey Singlefinder — single-print magnet strategy.

Reuses ``singlefinder.compute_single_prints``. Single prints (price levels the
TPO profile visited only once) act as magnets — price tends to return and fill
them. Bullish singles sit below price, bearish singles above.

  * Unfilled BEARISH single above -> LONG toward its near (lower) edge.
  * Unfilled BULLISH single below -> SHORT toward its near (upper) edge.

CRITICAL no-look-ahead note: ``compute_single_prints`` builds each session's
single-print zones from that session's *full* bar range and stamps them on every
bar of the SAME session — so the raw columns are look-ahead-contaminated (price
is guaranteed to revisit zones defined by its own session). This module shifts
the zones to the NEXT session (session D trades on session D-1's singles), the
same discipline ``tpo_profile.compute_tpo_profile`` applies. The within-session
columns are never used for entry.

Stop is an ATR distance on the risk side, clamped so R:R clears the floor.
One entry per session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.singlefinder import compute_single_prints
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
    return [{"min_single_ticks": t} for t in (2, 3)]


def generate(df: pd.DataFrame, mode: str = "fill", min_single_ticks: int = 2) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index)
    sp = compute_single_prints(work, min_single_ticks=min_single_ticks)
    rth = restrict_rth(sp)
    if rth.empty:
        return empty_contract(restrict_rth(df))
    rth["atr"] = atr_5m(rth)
    sd = session_dates(rth.index)

    # Shift zones to the PRIOR session to kill the within-session look-ahead:
    # the raw sf_* columns are constant within a session but derived from that
    # session's full range. Take one value per session, shift by one session,
    # and remap onto each bar so session D trades on session D-1's singles.
    rth["__sd"] = sd.values
    zone_cols = ["sf_bearish_single_bottom", "sf_bullish_single_top"]
    per_sess = rth.groupby("__sd")[zone_cols].first().sort_index().shift(1)
    bear_bot = rth["__sd"].map(per_sess["sf_bearish_single_bottom"]).to_numpy(float)
    bull_top = rth["__sd"].map(per_sess["sf_bullish_single_top"]).to_numpy(float)
    sd = sd.values

    closev = rth["close"].to_numpy(float)
    atrv = rth["atr"].to_numpy(float)

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
        atr = atrv[i] if np.isfinite(atrv[i]) and atrv[i] > 0 else np.nan
        if not np.isfinite(atr):
            continue
        if np.isfinite(bear_bot[i]) and closev[i] < bear_bot[i]:
            direction, s = "long", "BULLISH"
            target = bear_bot[i]
            stp = closev[i] - atr
        elif np.isfinite(bull_top[i]) and closev[i] > bull_top[i]:
            direction, s = "short", "BEARISH"
            target = bull_top[i]
            stp = closev[i] + atr
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

    rth["entry_signal"] = entry
    rth["bias"] = bias
    rth["stop_level"] = stop
    rth["target_1"] = t1
    rth["target_2"] = t2
    rth["target_3"] = t2
    rth["regime"] = ""
    rth["exit_signal"] = "NO_EXIT"
    return rth
