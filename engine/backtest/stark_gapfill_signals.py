"""
JARVIS TRADER — Stark TPO SHORT_GAP_FILL signal -> Backtester contract.

NEW FILE (do not import into production routing). Built for the honest gate-v2
WFO of the Stark TPO strategy's SHORT_GAP_FILL signal — the signal currently
quarantined in VALIDATION_ONLY_STRATEGIES (agents/pipeline.py) and the only
signal the autonomous pipeline has been generating on MES. Mirrors the
ib_breakout_signals.py / gap family discipline:

  * TPO profile (POC/VAH/VAL, 70% value area) computed per bar from the
    trailing 24h window (96 x 15m bars) via StarkTPOStrategy's OWN
    _calculate_tpo_profile — the exact production code path, not a re-derivation.
  * GAP_IMBALANCE structure per the production classifier
    (strategies/stark_tpo_strategy.py::evaluate_structure): price outside the
    value area AND last-bar volume <= trailing-window mean volume (above-mean
    volume classifies as BREAKOUT, a different signal — excluded here).
  * SHORT_GAP_FILL: close > VAH under GAP_IMBALANCE -> short, target POC
    ("gap pulls towards POC" — the production mandate).
  * Fresh-transition entries only: signal fires on the FIRST bar entering the
    SHORT_GAP_FILL state (prev bar not in state), one live setup at a time —
    prevents re-firing every bar while price sits above VAH.
  * RTH-only entries (ET 09:30-16:00 weekdays), EOD exit via Backtester
    eod_close=True — family standard for intraday mean-reversion plays.
  * Stop: ATR multiple above entry (grid param). NOTE: production Stark TPO
    defines NO stop (that gap is the #287/#286 naked-stop incident class);
    the backtest overlays one because gate v2's MC-drawdown metric is
    meaningless for an unbounded-loss strategy. Flagged in runner lineage.

Emits the columns Backtester.run() consumes (identical to ib_breakout_signals):
    entry_signal in {ENTRY_NOW, NO_TRADE}
    bias         in {BULLISH, BEARISH, NEUTRAL}
    stop_level, target_1, target_2, target_3, atr, regime, exit_signal

No look-ahead: the TPO profile at bar t uses bars (t-95..t] and the signal is
evaluated on bar t's close; Backtester enters on the NEXT bar's open
(pending_entry mechanism).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.stark_tpo_strategy import StarkTPOStrategy

TPO_WINDOW_BARS = 96  # trailing 24h of 15m bars — production evaluate_structure window
TICK_SIZE = 0.25      # MES


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


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def precompute_tpo_columns(df: pd.DataFrame, value_area_pct: float = 0.70) -> pd.DataFrame:
    """
    Add tpo_poc / tpo_vah / tpo_val / vol_above_avg columns, each computed from
    the trailing TPO_WINDOW_BARS bars ending at (and including) that bar —
    exactly the trailing-24h window production evaluate_structure() receives.

    Expensive (per-bar profile build) — call ONCE on the full frame, then slice
    for WFO windows. Profile at bar t depends only on bars <= t, so slicing
    after precompute introduces no look-ahead.
    """
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    strat = StarkTPOStrategy(value_area_pct=value_area_pct)
    n = len(df)
    poc = np.full(n, np.nan)
    vah = np.full(n, np.nan)
    val = np.full(n, np.nan)

    closes = df["close"].to_numpy(float)
    volumes = df["volume"].to_numpy(float)

    for i in range(TPO_WINDOW_BARS - 1, n):
        window = df.iloc[i - TPO_WINDOW_BARS + 1 : i + 1]
        p, h, l = strat._calculate_tpo_profile(window)
        poc[i], vah[i], val[i] = p, h, l

    # Production BREAKOUT-vs-GAP_IMBALANCE discriminator: last-bar volume vs
    # the trailing-window MEAN volume (evaluate_structure line 131).
    vol_mean = (
        pd.Series(volumes, index=df.index)
        .rolling(TPO_WINDOW_BARS, min_periods=TPO_WINDOW_BARS)
        .mean()
        .to_numpy()
    )
    df["tpo_poc"] = poc
    df["tpo_vah"] = vah
    df["tpo_val"] = val
    df["vol_above_avg"] = volumes > vol_mean
    _ = closes  # closes retained for clarity; signal math uses df columns
    return df


# Production signal taxonomy (strategies/stark_tpo_strategy.py::_get_actionable_signal).
# Each entry: (structure, side). Structure conditions per evaluate_structure():
#   INSIDE_VALUE   : val <= close <= vah
#   GAP_IMBALANCE  : outside value area, last-bar volume <= trailing-window mean
#   BREAKOUT       : outside value area, last-bar volume >  trailing-window mean
STARK_SIGNALS = (
    "SHORT_GAP_FILL",    # GAP_IMBALANCE, close > VAH -> short, target POC
    "LONG_GAP_FILL",     # GAP_IMBALANCE, close < VAL -> long,  target POC
    "SHORT_VAH_REJECT",  # INSIDE_VALUE, close >= VAH - 4 ticks -> short, target POC
    "LONG_VAL_BOUNCE",   # INSIDE_VALUE, close <= VAL + 4 ticks -> long,  target POC
    "LONG_MOMENTUM",     # BREAKOUT, close > VAH -> long,  target +1 VA-range
    "SHORT_MOMENTUM",    # BREAKOUT, close < VAL -> short, target -1 VA-range
)

_REJECT_BAND_TICKS = 4  # production: `vah - (tick_size * 4)` / `val + (tick_size * 4)`


def generate_stark_signals(
    df: pd.DataFrame,
    signal_type: str = "SHORT_GAP_FILL",
    stop_atr_mult: float = 2.0,
    min_gap_ticks: int = 0,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """
    Map the precomputed TPO state to Backtester-contract signals for ANY of the
    six production Stark TPO actionable signals.

    Parameters
    ----------
    df : OHLCV frame ALREADY passed through precompute_tpo_columns().
    signal_type : one of STARK_SIGNALS.
    stop_atr_mult : stop distance from entry close, in ATR(14) multiples.
    min_gap_ticks : gap-fill signals only — require close beyond VAH/VAL by at
        least this many ticks (filters marginal pokes outside value). Ignored
        for the other signal families (their band is production-fixed).

    Targets follow the production mandate where one exists (mean-reversion and
    gap-fill signals target POC). The momentum signals have NO production
    target — the backtest uses entry +/- 1x value-area range (pre-registered,
    noted in runner lineage).

    Returns RTH-only rows with the Backtester contract columns.
    """
    if signal_type not in STARK_SIGNALS:
        raise ValueError(f"signal_type must be one of {STARK_SIGNALS}, got {signal_type!r}")
    if "tpo_vah" not in df.columns:
        raise ValueError("call precompute_tpo_columns() first")

    df = df.copy()
    df["atr"] = _atr(df, period=14)

    close = df["close"].to_numpy(float)
    vah = df["tpo_vah"].to_numpy(float)
    val = df["tpo_val"].to_numpy(float)
    poc = df["tpo_poc"].to_numpy(float)
    vol_above = df["vol_above_avg"].to_numpy(bool)

    ready = ~np.isnan(vah) & ~np.isnan(val) & ~np.isnan(poc)
    inside_value = ready & (close >= val) & (close <= vah)
    band = _REJECT_BAND_TICKS * TICK_SIZE
    va_range = vah - val

    is_long = signal_type in ("LONG_GAP_FILL", "LONG_VAL_BOUNCE", "LONG_MOMENTUM")

    if signal_type == "SHORT_GAP_FILL":
        in_state = ready & ~vol_above & (close > vah + min_gap_ticks * TICK_SIZE)
        target = poc
    elif signal_type == "LONG_GAP_FILL":
        in_state = ready & ~vol_above & (close < val - min_gap_ticks * TICK_SIZE)
        target = poc
    elif signal_type == "SHORT_VAH_REJECT":
        in_state = inside_value & (close >= vah - band)
        target = poc
    elif signal_type == "LONG_VAL_BOUNCE":
        in_state = inside_value & (close <= val + band)
        target = poc
    elif signal_type == "LONG_MOMENTUM":
        in_state = ready & vol_above & (close > vah)
        target = close + va_range
    else:  # SHORT_MOMENTUM
        in_state = ready & vol_above & (close < val)
        target = close - va_range

    # Fresh transition only — first bar entering the state.
    prev_state = np.roll(in_state, 1)
    prev_state[0] = False
    fresh = in_state & ~prev_state

    # RTH-only entries.
    rth = _rth_mask(df.index, tz=tz)
    fresh = fresh & rth

    atr = df["atr"].to_numpy(float)
    stop = np.full(len(df), np.nan)
    t1 = np.full(len(df), np.nan)

    if is_long:
        stop[fresh] = close[fresh] - stop_atr_mult * atr[fresh]
    else:
        stop[fresh] = close[fresh] + stop_atr_mult * atr[fresh]
    t1[fresh] = np.asarray(target, dtype=float)[fresh] if np.ndim(target) else target

    df["entry_signal"] = np.where(fresh, "ENTRY_NOW", "NO_TRADE")
    df["bias"] = np.where(fresh, "BULLISH" if is_long else "BEARISH", "NEUTRAL")
    df["stop_level"] = stop
    df["target_1"] = t1
    df["target_2"] = t1
    df["target_3"] = t1
    df["regime"] = ""
    df["exit_signal"] = "NO_EXIT"

    # Backtest on RTH rows only (entries are RTH-gated already; restricting the
    # frame keeps EOD-exit semantics identical to the gap/IB family runners).
    return df[rth]


def generate_stark_gapfill_signals(
    df: pd.DataFrame,
    stop_atr_mult: float = 2.0,
    min_gap_ticks: int = 0,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """Backward-compatible alias: the original SHORT_GAP_FILL-only entry point."""
    return generate_stark_signals(
        df, signal_type="SHORT_GAP_FILL",
        stop_atr_mult=stop_atr_mult, min_gap_ticks=min_gap_ticks, tz=tz,
    )
