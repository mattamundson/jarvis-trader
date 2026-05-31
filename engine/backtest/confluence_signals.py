"""Confluence signal generator -- mechanizes the discretionary Corey/Saty 5m read.

Origin: Amo's 2026-05-30 challenge (the 5/29 /ES 5m session) -- "tell me there is
not an edge here." The discretionary edge he reads is NOT a single trigger; it is a
MULTI-FACTOR CONFLUENCE at a value extreme. gate v2 already killed the single blind
triggers (fade-every-VAH-cross = tpo_signals reversion FAIL; gap-fade FAIL). This
adapter tests the *confluence* the eye actually trades -- a genuinely different object.

Pre-registered thesis = FADE the over-extension back toward value, taken ONLY at a
3-factor confluence (matches the 5/29 chart: price pushed above value -> "sellers
offsides above" -> faded back to value):

  1. VALUE EXTREME  -- close pokes outside the PRIOR session's value area
                       (cross above prior VAH for a SHORT fade; below prior VAL for LONG).
  2. TSCORE CONFIRM -- the Corey Tscore (tpo_score.py, prior-session VA-based) agrees the
                       poke is stretched: score >= +tscore_thr for a short, <= -tscore_thr
                       for a long ("sellers/buyers offsides").
  3. ATR STRETCH    -- price is beyond the Saty daily-ATR band (prior-day close +/- band
                       _mult x WilderATR14(daily)) -- only fade a REAL extension, not a
                       tiny poke. This is the Saty ATR-levels factor on the chart.

This is FADE-only and direction-pre-registered -- NOT an A/B flip of breakout vs reversion
(that flip-flop is the multiple-testing trap that flagged the auction family as noise).

Exit geometry: identical entry-anchored value-area-width R multiples as tpo_signals
(stop 0.40R, targets 0.60/1.20/1.80R, R:R_1 = 1.5) -- clears the backtester's hard 1.2
R:R floor (backtester.py:801) and reuses proven, trap-free geometry.

No look-ahead: prior-session VAH/VAL/VPOC (shifted inside compute_tpo_profile), prior-DAY
Saty band (shift(1)), ATR(14) warmup suppressed. Output columns match backtester.run():
    open, high, low, close, entry_signal, exit_signal, bias, regime,
    stop_level, target_1, target_2, target_3, atr.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.tpo_profile import compute_tpo_profile
from backtest.tpo_score import compute_tpo_score
from backtest.trend_signals import _wilder_atr

_ATR_PERIOD = 14
_DAILY_ATR_PERIOD = 14


def _saty_daily_bands(df: pd.DataFrame, band_mult: float) -> tuple[pd.Series, pd.Series]:
    """Per-bar Saty ATR bands: PRIOR-day close +/- band_mult * WilderATR14(daily).

    Daily bars are calendar-day groupings of the intraday series (ETH included) -- a
    defensible stand-in for Saty's prior-session close+ATR, and free of RTH session-clock
    ambiguity on a continuous contract. Both the close and the ATR are shifted one day
    (prior completed day), so the bands are static from each day's open -- no look-ahead.
    Returns (upper_band, lower_band) reindexed to df's bars.
    """
    day = df.index.normalize()
    daily = pd.DataFrame(
        {
            "high": df["high"].groupby(day).max(),
            "low": df["low"].groupby(day).min(),
            "close": df["close"].groupby(day).last(),
        }
    )
    daily_atr = _wilder_atr(daily["high"], daily["low"], daily["close"], _DAILY_ATR_PERIOD)
    prior_close = daily["close"].shift(1)
    prior_atr = daily_atr.shift(1)
    upper = prior_close + band_mult * prior_atr
    lower = prior_close - band_mult * prior_atr
    # broadcast daily -> per-bar by calendar date
    bar_day = pd.Series(day, index=df.index)
    return bar_day.map(upper), bar_day.map(lower)


def generate_confluence_signals(
    df: pd.DataFrame,
    value_area_pct: float = 0.70,
    tscore_thr: float = 0.33,
    atr_band_mult: float = 1.0,
    session_start_hour: int = 9,
    session_start_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.DataFrame:
    """Generate confluence FADE signals (value extreme + Tscore confirm + ATR stretch).

    tscore_thr: |tpo_score| threshold for the offsides confirmation (0.33 = LEAN edge,
        0.66 = CONTROL edge in tpo_score.py's label bands).
    atr_band_mult: Saty daily-ATR multiple defining the stretch band (1.0 = the chart's
        "+1 ATR"). A short fires only when close >= upper band; a long when <= lower band.
    """
    prof = compute_tpo_profile(
        df,
        value_area_pct=value_area_pct,
        session_start_hour=session_start_hour,
        session_start_minute=session_start_minute,
        tz=tz,
    )
    # Tscore from the same prior-session value area (needs vpoc/va_high/va_low/close).
    prof = compute_tpo_score(prof)

    close = prof["close"]
    vah = prof["va_high"]
    val = prof["va_low"]
    width = (vah - val).abs()  # value-area width R = exit unit
    score = prof["tpo_score"]
    upper_band, lower_band = _saty_daily_bands(df, atr_band_mult)

    c = close.to_numpy()
    w_a = width.to_numpy()
    s_a = score.to_numpy()
    ub = upper_band.to_numpy()
    lb = lower_band.to_numpy()

    above = (close > vah).fillna(False).to_numpy()
    below = (close < val).fillna(False).to_numpy()
    prev_above = np.concatenate([[False], above[:-1]])
    prev_below = np.concatenate([[False], below[:-1]])
    cross_up = above & ~prev_above  # fresh poke above prior value -> SHORT fade
    cross_dn = below & ~prev_below  # fresh poke below prior value -> LONG fade

    n = len(prof)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    regime = np.full(n, "RANGE_BOUND", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    for i in range(n):
        r = w_a[i]
        if not np.isfinite(r) or r <= 0:
            continue
        ci = c[i]
        si = s_a[i]
        if not np.isfinite(si):
            continue

        # SHORT fade: extended ABOVE value AND score confirms stretched-up AND beyond +ATR band.
        go_short = cross_up[i] and si >= tscore_thr and np.isfinite(ub[i]) and ci >= ub[i]
        # LONG fade: extended BELOW value AND score confirms stretched-down AND beyond -ATR band.
        go_long = cross_dn[i] and si <= -tscore_thr and np.isfinite(lb[i]) and ci <= lb[i]

        if go_long:
            entry_signal[i] = "ENTRY_NOW"
            bias[i] = "STRONG_BULL"
            regime[i] = "CONFLUENCE_FADE"
            stop_level[i] = ci - 0.40 * r
            target_1[i] = ci + 0.60 * r
            target_2[i] = ci + 1.20 * r
            target_3[i] = ci + 1.80 * r
        elif go_short:
            entry_signal[i] = "ENTRY_NOW"
            bias[i] = "STRONG_BEAR"
            regime[i] = "CONFLUENCE_FADE"
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
    out["saty_upper"] = upper_band
    out["saty_lower"] = lower_band
    # backtester's `atr_val <= 0` guard does NOT catch NaN; suppress entries during warmup.
    _no_atr = ~np.isfinite(out["atr"].to_numpy())
    out.loc[_no_atr, ["entry_signal", "bias", "regime"]] = ["NO_TRADE", "NEUTRAL", "RANGE_BOUND"]
    return out
