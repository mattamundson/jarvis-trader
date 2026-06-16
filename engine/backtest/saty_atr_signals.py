"""
JARVIS TRADER — Corey "Saty ATR Levels" mechanical strategy -> Backtester contract.

NEW FILE (do not import into production routing). Built for the honest gate-v2
backtest of the Saty ATR Levels system (Corey Surles / Saty Mahajan). The Saty
primitives already exist as *indicators* (backtest/indicators.py::atr_fib_levels,
range_consumed_pct, ema_ribbon) feeding the LLM analysts, but no mechanical,
gate-tested entry system was ever built on them. This wrapper closes that gap so
Saty gets the same WFO + gate-v2 scrutiny as the IB / gap / TPO families.

Mechanics (faithful to the AA_SatyATRLevels study):
  * Anchor      = prior RTH-session close (the "0" line).
  * Daily ATR   = Wilder ATR(14) on the per-session OHLC, known as of the PRIOR
                  session close (shift 1) — no look-ahead.
  * Triggers    = anchor +/- 0.236 * ATR  (the Calls / Puts trigger lines).
  * Fib bands   = anchor +/- {0.382, 0.5, 0.618, 0.786, 1.0, 1.236} * ATR.
  * Range used  = |close - anchor| / ATR  (the "X% of ATR" exhaustion readout).

Two mechanical modes (mirrors the IB go/fade discipline):
  * GO   : first close beyond the call trigger -> LONG (beyond put -> SHORT),
           targeting the +target_ratio ATR band; stop back at the anchor.
           Optional EMA-ribbon (8/21/34) trend filter. Skips entries once the
           day's range is already exhausted (chasing a spent move has no edge).
  * FADE : first touch of a stretched band (>= entry_band ATR) WHILE the day's
           range is exhausted (range_used >= min_range_consumed) -> fade back
           toward the anchor; stop a half-ATR beyond the band. This is the lever
           the live screenshot highlighted ("85% of ATR consumed" -> fade).

Emits the columns Backtester.run() consumes:
    entry_signal in {ENTRY_NOW, NO_TRADE}
    bias         in {BULLISH, BEARISH, NEUTRAL}
    stop_level, target_1, target_2, target_3, atr, regime, exit_signal

No look-ahead: anchor + daily ATR come from prior sessions (shift 1); the
trigger/band condition is evaluated on the signal bar's CLOSE and the Backtester
enters on the NEXT bar's open (pending_entry). One entry per session (fresh flag).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import ema_ribbon, wilder_atr

# Corey canonical trigger ratio — NOT a free parameter (kept fixed so the WFO
# grid stays small and DSR n_trials honest).
TRIGGER_RATIO = 0.236


def _rth_mask(idx: pd.DatetimeIndex, tz: str = "America/New_York") -> np.ndarray:
    """Boolean mask for RTH bars: ET 09:30 <= t < 16:00, Mon-Fri."""
    if idx.tz is not None:
        et = idx.tz_convert(tz)
    else:
        et = idx.tz_localize("UTC").tz_convert(tz)
    t = et.time
    open_t = pd.Timestamp("09:30").time()
    close_t = pd.Timestamp("16:00").time()
    in_session = np.array([(open_t <= x < close_t) for x in t])
    weekday = et.dayofweek < 5
    return in_session & np.asarray(weekday)


def _atr_5m(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Intraday Wilder ATR on the working (5m) bars — the Backtester's unit."""
    return wilder_atr(df["high"], df["low"], df["close"], period=period)


def _session_anchors(
    rth: pd.DataFrame, tz: str, atr_period: int
) -> pd.DataFrame:
    """Attach per-bar ``anchor`` (prior-session close) and ``day_atr`` (prior
    session's Wilder ATR(14) on session OHLC). Both shifted one session so they
    are fully known at the open of the session they label — no look-ahead."""
    et = rth.index.tz_convert(tz) if rth.index.tz is not None else rth.index.tz_localize("UTC").tz_convert(tz)
    session_date = pd.Index(et.date, name="session_date")

    grp = rth.groupby(session_date)
    sess = pd.DataFrame({
        "high": grp["high"].max(),
        "low": grp["low"].min(),
        "close": grp["close"].last(),
    })
    sess = sess.sort_index()
    sess["day_atr"] = wilder_atr(sess["high"], sess["low"], sess["close"], period=atr_period)
    # Prior-session values (known at this session's open).
    sess["anchor"] = sess["close"].shift(1)
    sess["day_atr_prior"] = sess["day_atr"].shift(1)

    anchor_map = sess["anchor"].to_dict()
    atr_map = sess["day_atr_prior"].to_dict()
    out = rth.copy()
    out["anchor"] = [anchor_map.get(d, np.nan) for d in session_date]
    out["day_atr"] = [atr_map.get(d, np.nan) for d in session_date]
    out["__session"] = session_date.values
    return out


def generate_saty_atr_signals(
    df: pd.DataFrame,
    mode: str = "go",
    target_ratio: float = 1.0,
    ribbon_filter: bool = False,
    entry_band: float = 1.0,
    min_range_consumed: float = 0.7,
    max_range_consumed: float = 1.0,
    atr_period: int = 14,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """Add Backtester-contract signal columns for the Saty ATR Levels strategy.

    Parameters
    ----------
    mode : "go" (trigger-break continuation) or "fade" (band-exhaustion reversion).
    target_ratio : GO target as a multiple of daily ATR from the anchor (band).
    ribbon_filter : GO only — require EMA 8/21/34 stacked in the trade direction.
    entry_band : FADE only — stretched-band threshold (ATR multiples) to fade.
    min_range_consumed : FADE only — minimum |close-anchor|/ATR (exhaustion gate).
    max_range_consumed : GO only — skip entries once this much ATR is already spent.
    """
    if mode not in ("go", "fade"):
        raise ValueError(f"mode must be 'go' or 'fade', got {mode!r}")

    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    rth = df[_rth_mask(df.index, tz=tz)].copy()
    if rth.empty:
        rth["entry_signal"] = []
        return rth

    rth = _session_anchors(rth, tz=tz, atr_period=atr_period)
    rth["atr"] = _atr_5m(rth, period=14)

    # EMA ribbon on the intraday close for the GO trend filter.
    ema8, ema21, ema34 = ema_ribbon(rth["close"])
    ribbon_bull = (ema8 > ema21) & (ema21 > ema34)
    ribbon_bear = (ema8 < ema21) & (ema21 < ema34)

    anchor = rth["anchor"]
    day_atr = rth["day_atr"]
    close = rth["close"]
    valid = anchor.notna() & day_atr.notna() & (day_atr > 0)

    call_trigger = anchor + TRIGGER_RATIO * day_atr
    put_trigger = anchor - TRIGGER_RATIO * day_atr
    up_band = anchor + entry_band * day_atr
    dn_band = anchor - entry_band * day_atr
    range_used = (close - anchor).abs() / day_atr.where(day_atr > 0, np.nan)

    n = len(rth)
    bias = np.full(n, "NEUTRAL", dtype=object)
    entry = np.full(n, "NO_TRADE", dtype=object)
    stop = np.full(n, np.nan)
    t1 = np.full(n, np.nan)
    t2 = np.full(n, np.nan)

    closev = close.to_numpy(float)
    anchorv = anchor.to_numpy(float)
    atr_d = day_atr.to_numpy(float)
    callv = call_trigger.to_numpy(float)
    putv = put_trigger.to_numpy(float)
    upbv = up_band.to_numpy(float)
    dnbv = dn_band.to_numpy(float)
    rused = range_used.to_numpy(float)
    validv = valid.to_numpy(bool)
    rb_bull = ribbon_bull.to_numpy(bool)
    rb_bear = ribbon_bear.to_numpy(bool)
    sessions = rth["__session"].to_numpy()

    fired: set = set()  # one entry per session
    for i in range(n):
        if not validv[i]:
            continue
        sess = sessions[i]
        if sess in fired:
            continue
        atr = atr_d[i]
        if mode == "go":
            if rused[i] >= max_range_consumed:
                continue  # day's move already spent — no continuation edge
            long_ok = closev[i] > callv[i] and (not ribbon_filter or rb_bull[i])
            short_ok = closev[i] < putv[i] and (not ribbon_filter or rb_bear[i])
            if long_ok:
                bias[i] = "BULLISH"
                entry[i] = "ENTRY_NOW"
                stop[i] = anchorv[i]
                t1[i] = anchorv[i] + target_ratio * atr
                t2[i] = anchorv[i] + (target_ratio + 0.5) * atr
                fired.add(sess)
            elif short_ok:
                bias[i] = "BEARISH"
                entry[i] = "ENTRY_NOW"
                stop[i] = anchorv[i]
                t1[i] = anchorv[i] - target_ratio * atr
                t2[i] = anchorv[i] - (target_ratio + 0.5) * atr
                fired.add(sess)
        else:  # fade
            if rused[i] < min_range_consumed:
                continue  # not exhausted yet — no reversion edge
            # Stretched UP to the band -> fade SHORT back toward anchor.
            if closev[i] >= upbv[i]:
                bias[i] = "BEARISH"
                entry[i] = "ENTRY_NOW"
                stop[i] = anchorv[i] + (entry_band + 0.5) * atr
                t1[i] = anchorv[i]
                t2[i] = anchorv[i] - 0.236 * atr
                fired.add(sess)
            # Stretched DOWN to the band -> fade LONG back toward anchor.
            elif closev[i] <= dnbv[i]:
                bias[i] = "BULLISH"
                entry[i] = "ENTRY_NOW"
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
