"""
Value-Area re-entry signal generator for JARVIS TRADER (candidate sd-116).

Ported from `backtest/research_candidates/run_value_area_reentry_sd116.py`
(gate v2 PASS, 2026-07: 49 OOS trades/4mo, pf_ci_lower=1.19, dsr=1.0). This
module ports ONLY the entry-detection logic (developing Value Area + 2-TPO
state machine) into the live-callable `generate_signals(df) -> df` contract
`backtest/trend_signals.py::generate_sma_trend_signals` establishes, so it can
be dispatched from `backtest/signals.py::generate_instrument_signals` the
same way. The developing-VA/state-machine math below is intentionally
byte-for-byte identical to the research script (`_expand_from_poc`,
`_developing_va_for_session`, the per-session side/consec/event loop) — see
that file's module docstring for the full methodology rationale.

Entry/target/stop, as validated by the backtest:
    Entry : bar T's own close, once price has CLOSED on one side of the
            session's developing Value Area for 2+ consecutive 30-min bars.
    Target: the FROZEN opposite Value-Area boundary as of the event bar.
    Stop  : stop_atr_mult x ATR(14) beyond the FROZEN entry-side boundary.

Live-runner adaptation (intentionally divergent from the backtest, documented
here rather than silently baked in): `paper_runner.py`'s generic position
manager expects three STRICTLY ORDERED targets (T1 < T2 < T3 for a long) and
scales out 1/3 / 1/3 / remainder — the backtest itself uses a single
full-size exit at one target. `target_3` below IS the real, backtest-
validated VA-boundary target; `target_1`/`target_2` are evenly-spaced
waypoints toward it (1/3, 2/3) purely so paper_runner's existing partial-exit
plumbing has strictly increasing levels to key off of. This does not change
ENTRY signal timing, side, or stop — only how a live position is scaled out,
which the original backtest never modeled (it used 1 contract, single exit).

Known gap NOT addressed by this module (belongs to the PR-C wiring
decision): sd-116's backtest force-closes every trade at RTH session end
(never carries a position across the overnight Globex gap). paper_runner.py
has no session-close mechanism today — a live MES_VA30 position opened near
session close could carry overnight, a risk the backtest never tested.
Flagged for explicit handling when this module is wired into paper_runner.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import wilder_atr

# Candidate sd-116's own literal parameters (see research script) -- not
# swept/tunable here; this module reproduces the validated configuration.
BIN_SIZE = 1.0
VA_PCT = 0.70
CONSEC_TPO_THRESHOLD = 2
MIN_VA_WARMUP_BARS = 3
MIN_VA_WIDTH = 2.0
ATR_PERIOD = 14
DEFAULT_STOP_ATR_MULT = 1.0  # research script's IS-selected champion default

RTH_START_HOUR, RTH_START_MIN = 9, 30
RTH_END_HOUR = 16  # exclusive: last bar START time is 15:30


def _bin_index(price: float, bin_size: float) -> int:
    return int(np.floor(price / bin_size))


def _expand_from_poc(vol_at_price: dict[int, float], va_pct: float) -> tuple[int, int, int]:
    """Standard Market-Profile Value-Area algorithm: greedy single-level
    expansion outward from the POC until >= va_pct of accumulated volume is
    included. Returns (poc_bin, hi_bin, lo_bin). Identical to the research
    script -- see its module docstring for the algorithm rationale."""
    poc_bin = max(vol_at_price, key=vol_at_price.get)
    total_vol = sum(vol_at_price.values())
    target = total_vol * va_pct
    lo_bin = poc_bin
    hi_bin = poc_bin
    cum = vol_at_price[poc_bin]
    min_bin = min(vol_at_price)
    max_bin = max(vol_at_price)
    while cum < target and (lo_bin > min_bin or hi_bin < max_bin):
        vol_below = vol_at_price.get(lo_bin - 1, 0.0) if lo_bin > min_bin else -1.0
        vol_above = vol_at_price.get(hi_bin + 1, 0.0) if hi_bin < max_bin else -1.0
        if vol_below < 0 and vol_above < 0:
            break
        if vol_below >= vol_above:
            lo_bin -= 1
            cum += vol_at_price.get(lo_bin, 0.0)
        else:
            hi_bin += 1
            cum += vol_at_price.get(hi_bin, 0.0)
    return poc_bin, hi_bin, lo_bin


def _developing_va_for_session(
    low: np.ndarray, high: np.ndarray, volume: np.ndarray
) -> tuple[list, list, list]:
    """Per-bar developing (cumulative, bars <= T only) POC/VAH/VAL for one
    session, reset at the start of every call (no cross-session state).
    Identical to the research script."""
    vol_at_price: dict[int, float] = {}
    poc_list: list[float] = []
    vah_list: list[float] = []
    val_list: list[float] = []
    for lo, hi, vol in zip(low, high, volume):
        lo_bin = _bin_index(lo, BIN_SIZE)
        hi_bin = _bin_index(hi, BIN_SIZE)
        if hi_bin < lo_bin:
            hi_bin = lo_bin
        n_bins = hi_bin - lo_bin + 1
        if vol > 0 and n_bins > 0:
            per_bin = float(vol) / n_bins
            for b in range(lo_bin, hi_bin + 1):
                vol_at_price[b] = vol_at_price.get(b, 0.0) + per_bin

        if vol_at_price:
            poc_bin, hi_va_bin, lo_va_bin = _expand_from_poc(vol_at_price, VA_PCT)
            poc_list.append((poc_bin + 0.5) * BIN_SIZE)
            vah_list.append((hi_va_bin + 1.0) * BIN_SIZE)
            val_list.append(float(lo_va_bin) * BIN_SIZE)
        else:
            poc_list.append(np.nan)
            vah_list.append(np.nan)
            val_list.append(np.nan)
    return poc_list, vah_list, val_list


def _rth_session_date(index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """Return (in_rth boolean Series, session_date Series) aligned to *index*,
    identical RTH window/session convention as the research script."""
    eastern = (
        index.tz_convert("America/New_York")
        if index.tz is not None
        else index.tz_localize("UTC").tz_convert("America/New_York")
    )
    hour = eastern.hour
    minute = eastern.minute
    weekday = eastern.dayofweek
    in_rth = (weekday < 5) & (
        ((hour == RTH_START_HOUR) & (minute >= RTH_START_MIN)) | ((hour > RTH_START_HOUR) & (hour < RTH_END_HOUR))
    )
    session_date = pd.Series(
        pd.DatetimeIndex(eastern.normalize().tz_localize(None)), index=index
    )
    return pd.Series(in_rth, index=index), session_date


def generate_va_reentry_signals(
    df: pd.DataFrame,
    stop_atr_mult: float = DEFAULT_STOP_ATR_MULT,
) -> pd.DataFrame:
    """
    Generate Value-Area re-entry signals (candidate sd-116), compatible with
    the same live-runner contract as `trend_signals.generate_sma_trend_signals`.

    Non-RTH bars (or bars before the developing-VA warmup) are left as
    NO_TRADE — this function returns one row per input row (same index),
    it does not drop bars, so it's a drop-in replacement in the
    `generate_instrument_signals` dispatch table.

    Args:
        df: OHLCV DataFrame (any session coverage — internally RTH-filtered
            for VA/state-machine purposes; non-RTH bars pass through inert).
        stop_atr_mult: ATR multiple beyond the entry-side VA boundary for the
            stop. Defaults to the research script's IS-selected champion
            value (1.0x, the source claim's own suggested default).

    Returns df with columns:
        entry_signal : "ENTRY_NOW" | "NO_TRADE"
        stop_level   : entry-side boundary +/- stop_atr_mult x ATR
        target_1/2/3 : waypoints toward the frozen opposite VA boundary (see
                        module docstring "Live-runner adaptation") -- target_3
                        is the real backtest-validated target.
        bias         : "STRONG_BULL" (long) | "STRONG_BEAR" (short) | "NEUTRAL"
        regime       : "MEAN_REVERSION" at an event bar, else "RANGE_BOUND"
        atr          : ATR(14) series (Wilder, reused unmodified)
        vah_dev/val_dev/poc_dev : developing Value Area, informational
    """
    out = df.copy()
    n = len(out)

    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)
    bias = np.full(n, "NEUTRAL", dtype=object)
    regime = np.full(n, "RANGE_BOUND", dtype=object)
    vah_dev_out = np.full(n, np.nan)
    val_dev_out = np.full(n, np.nan)
    poc_dev_out = np.full(n, np.nan)

    if n == 0:
        out["entry_signal"] = entry_signal
        out["stop_level"] = stop_level
        out["target_1"] = target_1
        out["target_2"] = target_2
        out["target_3"] = target_3
        out["bias"] = bias
        out["regime"] = regime
        out["atr"] = np.nan
        out["vah_dev"] = vah_dev_out
        out["val_dev"] = val_dev_out
        out["poc_dev"] = poc_dev_out
        return out

    atr_out = np.full(n, np.nan)

    in_rth, session_date = _rth_session_date(out.index)
    rth_positions = np.flatnonzero(in_rth.to_numpy())
    if len(rth_positions) == 0:
        out["entry_signal"] = entry_signal
        out["stop_level"] = stop_level
        out["target_1"] = target_1
        out["target_2"] = target_2
        out["target_3"] = target_3
        out["bias"] = bias
        out["regime"] = regime
        out["atr"] = atr_out
        out["vah_dev"] = vah_dev_out
        out["val_dev"] = val_dev_out
        out["poc_dev"] = poc_dev_out
        return out

    rth_session_dates = session_date.to_numpy()[rth_positions]
    lows = out["low"].to_numpy()[rth_positions]
    highs = out["high"].to_numpy()[rth_positions]
    closes = out["close"].to_numpy()[rth_positions]
    volumes = out["volume"].to_numpy()[rth_positions]
    # ATR computed on the RTH-only bar sequence, matching the research
    # script exactly (`_build_features` runs wilder_atr on the already-
    # RTH-filtered df) -- NOT on the raw full-session series, which would
    # let overnight/Globex bars leak into the EWM and shift stop levels.
    atrs = wilder_atr(
        pd.Series(highs), pd.Series(lows), pd.Series(closes), period=ATR_PERIOD
    ).to_numpy()
    atr_out[rth_positions] = atrs

    # Group RTH positions by session_date, preserving original chronological order.
    session_groups: dict = {}
    for local_i, sd in enumerate(rth_session_dates):
        session_groups.setdefault(sd, []).append(local_i)

    for sd, local_idxs in session_groups.items():
        sess_low = lows[local_idxs]
        sess_high = highs[local_idxs]
        sess_vol = volumes[local_idxs]
        sess_close = closes[local_idxs]
        sess_atr = atrs[local_idxs]

        poc_l, vah_l, val_l = _developing_va_for_session(sess_low, sess_high, sess_vol)
        n_sess = len(local_idxs)

        consec = 0
        cur_side = None
        armed = True
        for pos in range(n_sess):
            orig_pos = rth_positions[local_idxs[pos]]
            vah = vah_l[pos]
            val = val_l[pos]
            close = sess_close[pos]
            is_last = pos == n_sess - 1

            vah_dev_out[orig_pos] = vah
            val_dev_out[orig_pos] = val
            poc_dev_out[orig_pos] = poc_l[pos]

            developed = (
                pos >= MIN_VA_WARMUP_BARS
                and not np.isnan(vah)
                and not np.isnan(val)
                and (vah - val) >= MIN_VA_WIDTH
            )
            if not developed:
                side = "inside"
            elif close > vah:
                side = "above"
            elif close < val:
                side = "below"
            else:
                side = "inside"

            if side == "inside":
                consec = 0
                cur_side = None
                armed = True
                continue

            consec = consec + 1 if side == cur_side else 1
            cur_side = side

            if consec >= CONSEC_TPO_THRESHOLD and armed and not is_last:
                armed = False
                atr_i = sess_atr[pos]
                if atr_i is None or (isinstance(atr_i, float) and np.isnan(atr_i)):
                    continue  # ATR warm-up not ready -- no tradeable signal

                if side == "above":
                    direction = "SHORT"
                    target = val
                    boundary = vah
                    stop_price = boundary + stop_atr_mult * float(atr_i)
                else:
                    direction = "LONG"
                    target = vah
                    boundary = val
                    stop_price = boundary - stop_atr_mult * float(atr_i)

                risk = abs(close - stop_price)
                reward = abs(target - close)
                if risk <= 0 or reward <= 0:
                    continue
                if direction == "SHORT" and close >= stop_price:
                    continue
                if direction == "LONG" and close <= stop_price:
                    continue

                entry_signal[orig_pos] = "ENTRY_NOW"
                stop_level[orig_pos] = stop_price
                target_3[orig_pos] = target
                target_1[orig_pos] = close + (target - close) / 3.0
                target_2[orig_pos] = close + 2.0 * (target - close) / 3.0
                bias[orig_pos] = "STRONG_BULL" if direction == "LONG" else "STRONG_BEAR"
                regime[orig_pos] = "MEAN_REVERSION"

    out["entry_signal"] = entry_signal
    out["stop_level"] = stop_level
    out["target_1"] = target_1
    out["target_2"] = target_2
    out["target_3"] = target_3
    out["bias"] = bias
    out["regime"] = regime
    out["atr"] = atr_out
    out["vah_dev"] = vah_dev_out
    out["val_dev"] = val_dev_out
    out["poc_dev"] = poc_dev_out
    return out
