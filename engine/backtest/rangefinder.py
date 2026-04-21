"""
JARVIS TRADER — Rangefinder v2 (Python port)

Source: thinkorswim-scripts/AA_CoreyRFv2STUDY.ts (Corey Surles, @coreysurles)
Spec:   thinkorswim-scripts/docs/corey_rangefinder_v2.md

Ported logic:
- Range expansion detection: high > prior range_high  OR  low < prior range_low,
  conditioned on the move exceeding expansion_multiple × ATR.  This replaces the
  TOS `exHigh` trigger (trigger1 > trigger4[1] && trigger2 < trigger2[1]) with an
  ATR-gated version so the threshold is adaptive to current volatility.
- POC (Point of Control) is approximated as the midpoint of the current range.
  The original study uses TOS VolumeProfile() to compute the true highest-volume
  price node; a full volume-weighted POC requires tick-level or per-bar volume
  data and is not implemented here.  All downstream values (VAH, VAL, control
  zone) inherit this approximation.
- VAH / VAL use 0.85 / 0.15 fractional offsets from range_low as proxies for the
  70% value area; the original uses VP.GetHighestValueArea() / GetLowestValueArea().
- Control zone: 38.2% – 61.8% of range (Fibonacci), matching TPOext38 / TPOext61
  in the source.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import wilder_atr


def compute_rangefinder(
    df: pd.DataFrame,
    atr_period: int = 14,
    expansion_multiple: float = 1.5,
) -> pd.DataFrame:
    """
    Compute Rangefinder v2 columns on *df* (must have open, high, low, close).

    Returns *df* with additional columns:
        rf_range_high         — upper bound of the current expansion range
        rf_range_low          — lower bound of the current expansion range
        rf_range_poc          — midpoint of current range (POC approximation; see module docstring)
        rf_vah                — 0.85 fractile of range (value area high proxy)
        rf_val                — 0.15 fractile of range (value area low proxy)
        rf_control_zone_high  — 61.8% of range from low (Fibonacci upper control)
        rf_control_zone_low   — 38.2% of range from low (Fibonacci lower control)
        rf_in_control_zone    — bool: close is within [control_zone_low, control_zone_high]
        rf_expansion_up       — bool: new upward range expansion on this bar
        rf_expansion_down     — bool: new downward range expansion on this bar

    Parameters
    ----------
    df : pd.DataFrame
        OHLC data. Index may be anything; must contain columns
        ``high``, ``low``, ``close`` (and ``open`` for completeness).
    atr_period : int
        Lookback for Wilder ATR used to gate expansion threshold.
    expansion_multiple : float
        Price must breach the current range bound by this many ATR units
        before a new expansion is declared.

    Notes
    -----
    POC simplification: The original TOS VolumeProfile() POC is the price
    level with the highest cumulative traded volume within the expansion range.
    This port uses the simple midpoint (range_high + range_low) / 2 instead,
    because per-bar OHLC data does not carry intra-bar volume distribution.
    Downstream columns (VAH, VAL, control zone) are therefore also approximate.
    """
    if df.empty:
        out = df.copy()
        for col in (
            "rf_range_high",
            "rf_range_low",
            "rf_range_poc",
            "rf_vah",
            "rf_val",
            "rf_control_zone_high",
            "rf_control_zone_low",
            "rf_in_control_zone",
            "rf_expansion_up",
            "rf_expansion_down",
        ):
            out[col] = np.nan if col not in ("rf_in_control_zone", "rf_expansion_up", "rf_expansion_down") else False
        return out

    atr = wilder_atr(df["high"], df["low"], df["close"], period=atr_period)

    n = len(df)
    range_high = np.full(n, np.nan)
    range_low = np.full(n, np.nan)
    exp_up = np.zeros(n, dtype=bool)
    exp_down = np.zeros(n, dtype=bool)

    cur_high = df["high"].iloc[0]
    cur_low = df["low"].iloc[0]

    for i in range(n):
        h = df["high"].iloc[i]
        lo = df["low"].iloc[i]
        atr_i = atr.iloc[i]
        threshold = expansion_multiple * atr_i if not np.isnan(atr_i) else 0.0

        if h > cur_high + threshold:
            cur_high = h
            cur_low = lo
            exp_up[i] = True
        elif lo < cur_low - threshold:
            cur_low = lo
            cur_high = h
            exp_down[i] = True

        range_high[i] = cur_high
        range_low[i] = cur_low

    rng = range_high - range_low
    poc = (range_high + range_low) / 2.0
    vah = range_low + 0.85 * rng
    val = range_low + 0.15 * rng
    cz_high = range_low + 0.618 * rng
    cz_low = range_low + 0.382 * rng
    close_arr = df["close"].to_numpy()
    in_cz = (close_arr >= cz_low) & (close_arr <= cz_high)

    out = df.copy()
    out["rf_range_high"] = range_high
    out["rf_range_low"] = range_low
    out["rf_range_poc"] = poc
    out["rf_vah"] = vah
    out["rf_val"] = val
    out["rf_control_zone_high"] = cz_high
    out["rf_control_zone_low"] = cz_low
    out["rf_in_control_zone"] = in_cz
    out["rf_expansion_up"] = exp_up
    out["rf_expansion_down"] = exp_down
    return out
