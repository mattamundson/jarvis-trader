"""
TPO auction signal generator -- Backtester-schema adapter for the Corey Tscore family.

Turns the descriptive TPO profile (engine/backtest/tpo_profile.py, which already
carries PRIOR-session vpoc/va_high/va_low/profile_high/profile_low -- no look-ahead)
into mechanical entry/exit signals in the JARVIS Backtester schema. Two near-inverse
mechanical readings of the auction framework, selected by `mode`:

  mode="breakout"  (Rule A) -- continuation: trade WITH acceptance OUTSIDE prior value.
      cross above prior VAH -> LONG; cross below prior VAL -> SHORT.

  mode="reversion" (Rule B) -- fade: trade AGAINST a poke outside prior value.
      cross below prior VAL -> LONG; cross above prior VAH -> SHORT.

The two modes are exact DIRECTION-INVERSES on the same VAH/VAL-cross events with
identical exit geometry -- a clean A/B test that isolates continuation-vs-fade as the
only variable for gate v2 to judge.

Exit geometry (both modes): stop and targets are measured in units of the prior-session
value-area width R = |VAH - VAL| (the auction's natural scale), anchored to the entry
price, asymmetric so R:R clears the backtester's hard 1.2 floor:
    stop = entry -/+ 0.40*R ; targets = entry +/- {0.60, 1.20, 1.80}*R  (R:R_1 = 1.5)
The ENTRY is purely auction-structural (a cross of the prior session's value edge -- the
Corey/TPO signal); R-multiple exits are an honest standardization forced by the
backtester recomputing levels as ATR multiples and rejecting R:R < 1.2 (backtester.py:801).

Both are no-look-ahead: today's bar is evaluated against the PRIOR completed session's
profile (the shift is done inside compute_tpo_profile). Output columns match what
backtest/backtester.py:run() requires:
    open, high, low, close, entry_signal, bias, stop_level, target_1, target_2,
    target_3, regime, atr.

The swept gate-v2 parameter is `value_area_pct` (the runner grids it for IS selection,
fixed-params sweep, and DSR n_trials).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.tpo_profile import compute_tpo_profile
from backtest.trend_signals import _wilder_atr  # Wilder ATR(14), same as trend family

_ATR_PERIOD = 14
_MODES = ("breakout", "reversion")


def generate_tpo_signals(
    df: pd.DataFrame,
    mode: str = "breakout",
    value_area_pct: float = 0.70,
    session_start_hour: int = 9,
    session_start_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.DataFrame:
    """Generate auction (TPO) entry signals in Backtester schema.

    df must have a DatetimeIndex and open/high/low/close columns.
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")

    prof = compute_tpo_profile(
        df,
        value_area_pct=value_area_pct,
        session_start_hour=session_start_hour,
        session_start_minute=session_start_minute,
        tz=tz,
    )

    close = prof["close"]
    vah = prof["va_high"]
    val = prof["va_low"]
    width = (vah - val).abs()  # prior-session value-area width R = exit unit

    n = len(prof)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    regime = np.full(n, "RANGE_BOUND", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    above = (close > vah).fillna(False).to_numpy()
    below = (close < val).fillna(False).to_numpy()
    # fresh-cross: this bar outside value, previous bar not outside on that side
    prev_above = np.concatenate([[False], above[:-1]])
    prev_below = np.concatenate([[False], below[:-1]])
    cross_up = above & ~prev_above
    cross_dn = below & ~prev_below

    c = close.to_numpy()
    w_a = width.to_numpy()

    for i in range(n):
        r = w_a[i]
        if not np.isfinite(r) or r <= 0:
            continue

        ci = c[i]
        # Long-direction events differ by mode; exit geometry is identical and
        # entry-anchored in units of value-area width R (asymmetric, R:R_1 = 1.5).
        if mode == "breakout":
            go_long, go_short, reg = cross_up[i], cross_dn[i], "TPO_BREAKOUT"
        else:  # reversion -- exact direction-inverse
            go_long, go_short, reg = cross_dn[i], cross_up[i], "TPO_REVERSION"

        if go_long:
            entry_signal[i] = "ENTRY_NOW"
            bias[i] = "STRONG_BULL"
            regime[i] = reg
            stop_level[i] = ci - 0.40 * r
            target_1[i] = ci + 0.60 * r
            target_2[i] = ci + 1.20 * r
            target_3[i] = ci + 1.80 * r
        elif go_short:
            entry_signal[i] = "ENTRY_NOW"
            bias[i] = "STRONG_BEAR"
            regime[i] = reg
            stop_level[i] = ci + 0.40 * r
            target_1[i] = ci - 0.60 * r
            target_2[i] = ci - 1.20 * r
            target_3[i] = ci - 1.80 * r

    out = prof.copy()
    out["entry_signal"] = entry_signal
    out["exit_signal"] = "NO_EXIT"
    out["bias"] = bias
    out["regime"] = regime
    out["stop_level"] = stop_level
    out["target_1"] = target_1
    out["target_2"] = target_2
    out["target_3"] = target_3
    out["atr"] = _wilder_atr(out["high"], out["low"], out["close"], _ATR_PERIOD)
    # Can't size a trade without ATR; the backtester's `atr_val <= 0` guard does
    # NOT catch NaN (NaN <= 0 is False), so a signal firing during ATR(14) warmup
    # would propagate NaN into position sizing. Suppress entries until ATR is finite.
    _no_atr = ~np.isfinite(out["atr"].to_numpy())
    out.loc[_no_atr, ["entry_signal", "bias", "regime"]] = ["NO_TRADE", "NEUTRAL", "RANGE_BOUND"]
    return out
