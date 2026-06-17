"""Corey Tscore / TPO-Score — mechanical strategy.

Trades the auction-control score (price vs the PRIOR session's value area).
Reuses ``tpo_profile.compute_tpo_profile`` (already shifts levels to the prior
session -> no look-ahead) and ``tpo_score.compute_tpo_score`` (score in [-1,+1]).

  * trend     : score beyond +/-threshold (price has accepted beyond value) ->
                trade WITH control; stop at VPOC, target a value-area-range
                extension past the breached edge.
  * reversion : score beyond +/-threshold -> FADE back to VPOC; stop beyond the
                profile extreme.

One entry per session, on the first qualifying bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.studies._common import (
    atr_5m,
    clamp_stop_for_rr,
    empty_contract,
    restrict_rth,
    session_dates,
    sides_ok,
)
from backtest.tpo_profile import compute_tpo_profile
from backtest.tpo_score import compute_tpo_score

MODES = ["trend", "reversion"]


def grid(mode: str) -> list[dict]:
    # threshold = score magnitude required to act; small grid (<=4).
    return [{"score_threshold": t} for t in (0.3, 0.6)]


def generate(df: pd.DataFrame, mode: str = "trend", score_threshold: float = 0.5) -> pd.DataFrame:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index)
    # Prior-session VPOC/VA (no look-ahead) on the full frame, then score.
    prof = compute_tpo_profile(work)
    have_va = {"vpoc", "va_high", "va_low"}.issubset(prof.columns)
    if have_va:
        prof = compute_tpo_score(prof)

    rth = restrict_rth(prof)
    if rth.empty or not have_va:
        return empty_contract(restrict_rth(df))
    rth["atr"] = atr_5m(rth)
    sd = session_dates(rth.index).values

    score = rth["tpo_score"].to_numpy(float)
    vpoc = rth["vpoc"].to_numpy(float)
    vah = rth["va_high"].to_numpy(float)
    val = rth["va_low"].to_numpy(float)
    phi = rth["profile_high"].to_numpy(float)
    plo = rth["profile_low"].to_numpy(float)
    closev = rth["close"].to_numpy(float)

    n = len(rth)
    bias = np.full(n, "NEUTRAL", dtype=object)
    entry = np.full(n, "NO_TRADE", dtype=object)
    stop = np.full(n, np.nan)
    t1 = np.full(n, np.nan)
    t2 = np.full(n, np.nan)
    fired: set = set()

    for i in range(n):
        if not np.isfinite(score[i]) or not np.isfinite(vpoc[i]):
            continue
        sess = sd[i]
        if sess in fired:
            continue
        va_range = max(vah[i] - val[i], 1e-9)
        if mode == "trend":
            if score[i] >= score_threshold:  # buyer control, beyond VAH
                direction, s = "long", "BULLISH"
                target = vah[i] + va_range
                stp = vpoc[i]
            elif score[i] <= -score_threshold:  # seller control, beyond VAL
                direction, s = "short", "BEARISH"
                target = val[i] - va_range
                stp = vpoc[i]
            else:
                continue
        else:  # reversion
            if score[i] >= score_threshold:  # stretched above value -> fade short
                direction, s = "short", "BEARISH"
                target = vpoc[i]
                stp = phi[i] if np.isfinite(phi[i]) else closev[i] + va_range
            elif score[i] <= -score_threshold:  # stretched below value -> fade long
                direction, s = "long", "BULLISH"
                target = vpoc[i]
                stp = plo[i] if np.isfinite(plo[i]) else closev[i] - va_range
            else:
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
