"""
Gap signal generator -- Backtester-schema adapter for the RTH overnight-gap family.

GENERATION-ENGINE EXPERIMENT 4. The ledger has no `gap` family (only trend/
breakout/orb/donchian/mean_reversion/tpo), so this is a genuinely novel edge
candidate sourced from the Corey Gapfinder study (gapfinder.py / corey_gapfinder_v1).

THE GAP IS RTH-DEFINED, NOT 24h. Futures trade ~23h/day, so a "gap" measured at an
arbitrary intraday session boundary is just the prior session's net move (continuous
trading through it). The real, tradeable gap is the RTH-session gap: today's RTH open
vs YESTERDAY's RTH close, with the overnight move excluded -- that overnight move IS
the gap. So this adapter RTH-filters (ET 09:30-16:00 by default) and returns ONLY RTH
bars; the backtester runs on them (gap plays are intraday-RTH; the EOD exit fits).

Two near-inverse mechanical readings (a clean A/B, same as the TPO family):
  mode="fade" -- gap up -> SHORT toward the fill; gap down -> LONG toward the fill.
  mode="go"   -- gap up -> LONG (continuation); gap down -> SHORT.

Exit geometry (both modes): entry-anchored multiples of the gap size G = |RTH_open -
prior_RTH_close|, asymmetric so R:R clears the backtester's hard 1.2 floor:
    stop = entry -/+ 0.40*G ; targets = entry +/- {0.60, 1.20, 1.80}*G   (R:R_1 = 1.5)

No look-ahead: the gap uses the PRIOR session's RTH close (shift 1). Entry fires on the
first RTH bar of a session whose |gap| >= min_gap_pct (the swept gate-v2 parameter).
Output columns match backtest/backtester.py:run(): open/high/low/close/entry_signal/
bias/stop_level/target_1/2/3/regime/atr (+exit_signal).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.trend_signals import _wilder_atr

_ATR_PERIOD = 14
_MODES = ("fade", "go")


def generate_gap_signals(
    df: pd.DataFrame,
    mode: str = "fade",
    min_gap_pct: float = 0.002,
    rth_start: str = "09:30",
    rth_end: str = "16:00",
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """Generate RTH-gap entry signals in Backtester schema (RTH-filtered frame).

    df must have a DatetimeIndex (UTC/tz-aware) and open/high/low/close columns.
    Returns ONLY the RTH bars, with signal columns appended.
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")

    out = df.copy()
    idx = out.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    local = idx.tz_convert(tz)

    # RTH filter (inclusive open, exclusive close) on local exchange time.
    mins = local.hour * 60 + local.minute
    sh, sm = (int(x) for x in rth_start.split(":"))
    eh, em = (int(x) for x in rth_end.split(":"))
    rth_mask = (mins >= sh * 60 + sm) & (mins < eh * 60 + em)
    out = out.loc[rth_mask].copy()
    if out.empty:
        out["entry_signal"] = []
        return out

    local_rth = local[rth_mask]
    session_date = pd.Index(local_rth.normalize()).values  # ET calendar date per RTH bar

    out["_sd"] = session_date
    grp = out.groupby("_sd")
    first_open = grp["open"].first()
    last_close = grp["close"].last()
    prior_close = last_close.shift(1)  # no look-ahead: prior session's RTH close
    gap = first_open - prior_close
    gap_pct = (gap / prior_close).abs()

    gmap = gap.to_dict()
    qmap = (gap_pct >= min_gap_pct).to_dict()

    sd_arr = out["_sd"].to_numpy()
    c = out["close"].to_numpy()
    is_first = np.concatenate([[True], sd_arr[1:] != sd_arr[:-1]])

    n = len(out)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    regime = np.full(n, "RANGE_BOUND", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    reg = "GAP_FADE" if mode == "fade" else "GAP_GO"
    for i in range(n):
        if not is_first[i]:
            continue
        sd = sd_arr[i]
        if not qmap.get(sd, False):
            continue
        g = gmap.get(sd, np.nan)
        if not np.isfinite(g) or g == 0:
            continue
        G = abs(g)
        ci = c[i]
        gap_up = g > 0
        # fade: gap up -> SHORT; gap down -> LONG. go: exact inverse.
        go_long = (not gap_up) if mode == "fade" else gap_up
        if go_long:
            entry_signal[i] = "ENTRY_NOW"
            bias[i] = "STRONG_BULL"
            regime[i] = reg
            stop_level[i] = ci - 0.40 * G
            target_1[i] = ci + 0.60 * G
            target_2[i] = ci + 1.20 * G
            target_3[i] = ci + 1.80 * G
        else:
            entry_signal[i] = "ENTRY_NOW"
            bias[i] = "STRONG_BEAR"
            regime[i] = reg
            stop_level[i] = ci + 0.40 * G
            target_1[i] = ci - 0.60 * G
            target_2[i] = ci - 1.20 * G
            target_3[i] = ci - 1.80 * G

    out = out.drop(columns=["_sd"])
    out["entry_signal"] = entry_signal
    out["exit_signal"] = "NO_EXIT"
    out["bias"] = bias
    out["regime"] = regime
    out["stop_level"] = stop_level
    out["target_1"] = target_1
    out["target_2"] = target_2
    out["target_3"] = target_3
    out["atr"] = _wilder_atr(out["high"], out["low"], out["close"], _ATR_PERIOD)
    # ATR(14) warmup: backtester's `atr_val <= 0` guard does not catch NaN -> suppress.
    _no_atr = ~np.isfinite(out["atr"].to_numpy())
    out.loc[_no_atr, ["entry_signal", "bias", "regime"]] = ["NO_TRADE", "NEUTRAL", "RANGE_BOUND"]
    return out
