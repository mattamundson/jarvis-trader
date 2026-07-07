"""
HiddenPivots Pattern Detection Library
Pure Python — no LLM calls, deterministic OHLCV-based pattern recognition.

Strategy: Rick Ackerman's Hidden Pivots methodology combined with:
  - 4-EMA fan alignment (bullish/bearish/compressed)
  - Custom 2-line oscillator (STC raw + smoothed STC)
  - Pre-calculated HP level ladder (A-B-C-D swing structure)
  - Pattern recognition: rounded base/top, flags, triangles, channel reversals
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class HPScanResult:
    symbol: str
    timeframe: str
    pattern: Optional[
        str
    ]  # "rounded_base" | "rounded_top" | "bull_flag" | "bear_flag" | "triangle" | "channel_reversal" | None
    bias: str  # "LONG" | "SHORT" | "WATCH" | "SOH"
    trigger_price: Optional[float]  # "Above X" level for entry
    tight_stop: Optional[float]
    riskier_stop: Optional[float]
    targets: list[float] = field(default_factory=list)  # [T1, T2, T3]
    hp_ou_level: Optional[float] = None  # The HP o/u dotted line level
    hp_levels: list[float] = field(default_factory=list)  # Full level ladder
    ema_alignment: str = "MIXED"  # "BULLISH_FAN" | "BEARISH_FAN" | "COMPRESSED" | "MIXED"
    rs_rw_score: float = 0.0  # -1.0 (strong r/w) to +1.0 (strong r/s)
    rs_rw_label: str = (
        "neutral"  # "awesome_rs" | "good_rs" | "decent_rs" | "neutral" | "decent_rw" | "dominant_rw"
    )
    soh: bool = False  # Sit On Hands flag
    oscillator_state: str = (
        "FLAT"  # "BULLISH_CROSS" | "BEARISH_CROSS" | "RISING" | "FALLING" | "FLAT"
    )
    bars_since_cross: int = (
        -1
    )  # bars since last STC teal/pink cross (0 = latest bar; -1 = none found)
    last_cross_dir: str = "none"  # "bull" | "bear" | "none" — direction of that most-recent cross
    confidence: float = 0.0  # 0.0–1.0
    notes: str = ""


@dataclass
class SwingPoints:
    """A-B-C-D swing structure for HP level calculation."""

    a_idx: int
    a_price: float
    b_idx: int
    b_price: float
    c_idx: int
    c_price: float
    d_price: float  # Measured move target (projected)
    midpoint: float  # HP o/u level


# ── EMA Alignment ─────────────────────────────────────────────────────────────


def detect_ema_alignment(df: pd.DataFrame, periods: list[int] = None) -> str:
    """
    Classify EMA alignment as BULLISH_FAN, BEARISH_FAN, COMPRESSED, or MIXED.

    BULLISH_FAN: All EMAs rising + stacked (short > medium > long) + price above all
    BEARISH_FAN: All EMAs falling + stacked (short < medium < long) + price below all
    COMPRESSED: All EMAs within 1% of each other (base/consolidation phase)
    MIXED: None of the above
    """
    if periods is None:
        periods = [10, 50, 100, 200]

    close = df["close"]
    if len(close) < max(periods) + 5:
        return "MIXED"

    emas = {p: close.ewm(span=p, adjust=False).mean() for p in periods}
    current_emas = {p: emas[p].iloc[-1] for p in periods}
    prev_emas = {p: emas[p].iloc[-5] for p in periods}  # 5-bar lookback for direction

    sorted_periods = sorted(periods)  # short → long
    ema_values = [current_emas[p] for p in sorted_periods]

    # Check direction: all EMAs rising
    all_rising = all(current_emas[p] > prev_emas[p] for p in periods)
    all_falling = all(current_emas[p] < prev_emas[p] for p in periods)

    # Check stacking order
    bullish_stacked = all(ema_values[i] > ema_values[i + 1] for i in range(len(ema_values) - 1))
    bearish_stacked = all(ema_values[i] < ema_values[i + 1] for i in range(len(ema_values) - 1))

    # Check price position
    current_price = close.iloc[-1]
    price_above_all = current_price > max(ema_values)
    price_below_all = current_price < min(ema_values)

    # Check compression: all EMAs within 1% of median
    median_ema = np.median(ema_values)
    max_deviation = max(abs(v - median_ema) / median_ema for v in ema_values)
    compressed = max_deviation < 0.01

    if compressed:
        return "COMPRESSED"
    if all_rising and bullish_stacked and price_above_all:
        return "BULLISH_FAN"
    if all_falling and bearish_stacked and price_below_all:
        return "BEARISH_FAN"
    return "MIXED"


# ── Oscillator State ──────────────────────────────────────────────────────────


def detect_oscillator_state(df: pd.DataFrame) -> str:
    """
    Detect HiddenPivots 2-line oscillator state using STC as proxy.

    Teal line = STC raw value (fast)
    Pink line = STC.ewm(span=3).mean() (slow smoothing)

    Returns: BULLISH_CROSS | BEARISH_CROSS | RISING | FALLING | FLAT
    """
    try:
        from backtest.indicators import stc as compute_stc
    except ImportError:
        logger.warning("Could not import stc from backtest.indicators")
        return "FLAT"

    close = df["close"]
    if len(close) < 60:
        return "FLAT"

    teal = compute_stc(close, fast=23, slow=50, k_period=10, d_period=3)
    pink = teal.ewm(span=3, adjust=False).mean()

    if len(teal) < 3:
        return "FLAT"

    t_now = teal.iloc[-1]
    t_prev = teal.iloc[-2]
    p_now = pink.iloc[-1]
    p_prev = pink.iloc[-2]

    # Crossover detection
    crossed_up = t_prev <= p_prev and t_now > p_now
    crossed_down = t_prev >= p_prev and t_now < p_now

    if crossed_up:
        return "BULLISH_CROSS"
    if crossed_down:
        return "BEARISH_CROSS"

    # Direction without cross
    if t_now > p_now and t_now > t_prev:
        return "RISING"
    if t_now < p_now and t_now < t_prev:
        return "FALLING"
    return "FLAT"


def bars_since_last_cross(df: pd.DataFrame) -> tuple[int, str]:
    """Bars since the most recent STC teal/pink crossover and its direction.

    A crossover is a single-bar event, so `oscillator_state` only reports
    BULLISH_CROSS/BEARISH_CROSS on the exact bar it prints. This walks backward
    to find how stale the last cross is, so a WATCH setup can still convey "the
    cross fired N bars ago" instead of a binary in/out.

    Returns (bars_since, direction):
      bars_since == 0  -> cross printed on the latest bar
      bars_since  > 0  -> N bars have closed since the cross
      bars_since == -1 -> no cross found in the window (direction "none")
      direction in {"bull", "bear", "none"}
    """
    try:
        from backtest.indicators import stc as compute_stc
    except ImportError:
        logger.warning("Could not import stc from backtest.indicators")
        return -1, "none"

    close = df["close"]
    if len(close) < 60:
        return -1, "none"

    teal = compute_stc(close, fast=23, slow=50, k_period=10, d_period=3)
    pink = teal.ewm(span=3, adjust=False).mean()
    t = teal.values
    p = pink.values
    n = len(t)
    if n < 2:
        return -1, "none"

    # Walk from the latest bar backward; NaN comparisons are False so the
    # warm-up bars never register a spurious cross.
    for k in range(n - 1, 0, -1):
        crossed_up = t[k - 1] <= p[k - 1] and t[k] > p[k]
        crossed_down = t[k - 1] >= p[k - 1] and t[k] < p[k]
        if crossed_up:
            return (n - 1 - k), "bull"
        if crossed_down:
            return (n - 1 - k), "bear"
    return -1, "none"


# ── HP Level Calculation (Rick Ackerman) ─────────────────────────────────────


def _find_swing_points(series: pd.Series, order: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """Find local maxima and minima indices."""
    arr = series.values
    highs = argrelextrema(arr, np.greater_equal, order=order)[0]
    lows = argrelextrema(arr, np.less_equal, order=order)[0]
    return highs, lows


def compute_hp_ou_level(
    df: pd.DataFrame,
) -> tuple[Optional[float], list[float], Optional[SwingPoints]]:
    """
    Compute HP o/u level and full level ladder from the last A-B-C swing structure.

    Rick Ackerman methodology:
      A = last major swing low
      B = swing high after A
      C = retracement low after B (must be > A for valid bullish pattern)
      D (measured move) = C + (B - A)
      HP o/u midpoint = (A + D) / 2

    Level ladder: Fibonacci projections from A-B-C structure at 0.618, 1.0, 1.272, 1.618 of (B-A)

    Returns: (hp_ou_level, level_ladder, swing_points) or (None, [], None)
    """
    close = df["close"]
    if len(close) < 30:
        return None, [], None

    highs_idx, lows_idx = _find_swing_points(close, order=5)

    if len(highs_idx) < 1 or len(lows_idx) < 2:
        return None, [], None

    # Find last A-B-C structure: A=low, B=high after A, C=low after B (> A)
    swing_points = None
    for i in range(len(lows_idx) - 1, 0, -1):
        c_idx = lows_idx[i]
        c_price = close.iloc[c_idx]
        # Find B (high) between A and C
        a_candidates = list(lows_idx[:i])
        if not a_candidates:
            continue
        a_idx = a_candidates[-1]
        a_price = close.iloc[a_idx]
        if c_price <= a_price:
            continue  # C must be above A for valid bullish structure
        b_candidates = [j for j in highs_idx if a_idx < j < c_idx]
        if not b_candidates:
            continue
        b_idx = b_candidates[-1]
        b_price = close.iloc[b_idx]
        if b_price <= a_price:
            continue
        # Valid A-B-C found
        d_price = c_price + (b_price - a_price)
        midpoint = (a_price + d_price) / 2
        swing_points = SwingPoints(
            a_idx=a_idx,
            a_price=a_price,
            b_idx=b_idx,
            b_price=b_price,
            c_idx=c_idx,
            c_price=c_price,
            d_price=d_price,
            midpoint=midpoint,
        )
        break

    if swing_points is None:
        return None, [], None

    ab_range = swing_points.b_price - swing_points.a_price
    base = swing_points.c_price
    d_price = swing_points.d_price

    # Level ladder: dense Fibonacci projections from both C and D anchor points
    # Primary (from C): 0.618, 1.0, 1.272, 1.618 of AB range
    # Extended (from D): additional levels above the measured move
    c_levels = [base + ab_range * f for f in [0.618, 1.0, 1.272, 1.618, 2.0, 2.618]]
    d_levels = [d_price + ab_range * f for f in [0.5, 1.0, 1.618, 2.618]]
    # Support levels below C (for stop placement)
    support_levels = [base - ab_range * f for f in [0.382, 0.618, 1.0]]

    all_raw = c_levels + d_levels + support_levels
    level_ladder = sorted({round(l, 2) for l in all_raw if l > 0})  # noqa: E741  # OHLC convention

    return swing_points.midpoint, level_ladder, swing_points


# ── Pattern Detectors ─────────────────────────────────────────────────────────


def detect_rounded_base(
    df: pd.DataFrame, min_bars: int = 20, max_bars: int = 120
) -> tuple[Optional[float], float, str]:
    """
    Detect rounded base / saucer pattern.

    Criteria:
    1. Price is concave-up at the trough (2nd derivative of smoothed close > 0)
    2. EMA alignment compressed → transitioning to BULLISH_FAN
    3. Volume declining into low, expanding at neckline
    4. Neckline = horizontal resistance above trough

    Returns: (trigger_price, confidence, notes) or (None, 0.0, reason)
    """
    if len(df) < min_bars:
        return None, 0.0, "insufficient_bars"

    window = df.tail(max_bars)
    close = window["close"]
    volume = window.get("volume", pd.Series(dtype=float))

    # Smooth price to reduce noise
    smooth = close.rolling(5, min_periods=1).mean()
    smooth_arr = smooth.values

    # Find the trough (minimum)
    trough_rel = int(np.argmin(smooth_arr))
    if trough_rel < 5 or trough_rel > len(smooth_arr) - 5:
        return None, 0.0, "trough_at_edge"

    # Check concavity (2nd derivative > 0 at trough = concave up)
    second_deriv = np.gradient(np.gradient(smooth_arr))
    concave_up = np.mean(second_deriv[max(0, trough_rel - 3) : trough_rel + 4]) > 0

    # Neckline = max price from trough to now
    post_trough = close.iloc[trough_rel:]
    neckline = post_trough.max()
    current_price = close.iloc[-1]

    # Price should be approaching or testing neckline (within 3%)
    approaching_neckline = current_price >= neckline * 0.97

    # EMA check: compressed or transitioning to bullish
    ema_state = detect_ema_alignment(df)
    ema_ok = ema_state in ("COMPRESSED", "BULLISH_FAN", "MIXED")

    # Volume check (optional)
    vol_ok = True
    if len(volume) > 0 and volume.sum() > 0:
        pre_trough_vol = volume.iloc[:trough_rel].mean() if trough_rel > 0 else 0
        post_trough_vol = volume.iloc[trough_rel:].mean()
        vol_ok = post_trough_vol >= pre_trough_vol * 0.8  # Volume recovering

    # Weighted scoring: concavity most important, volume least
    weights = {"concave": 0.40, "neckline": 0.30, "ema": 0.20, "vol": 0.10}
    confidence = (
        weights["concave"] * float(concave_up)
        + weights["neckline"] * float(approaching_neckline)
        + weights["ema"] * float(ema_ok)
        + weights["vol"] * float(vol_ok)
    )
    # Quality bonus: saucer must have meaningful depth (> 3% drawdown)
    trough_price = close.iloc[trough_rel]
    saucer_depth_pct = (neckline - trough_price) / neckline if neckline > 0 else 0
    if saucer_depth_pct > 0.05:  # > 5% depth adds 0.10 bonus
        confidence = min(1.0, confidence + 0.10)
    elif saucer_depth_pct < 0.01:  # Very shallow — penalize
        confidence = confidence * 0.5

    if confidence < 0.5:
        return None, confidence, f"low_confidence({confidence:.2f})"

    return (
        neckline,
        confidence,
        f"saucer(depth={saucer_depth_pct:.1%},trough_bar={trough_rel},neckline={neckline:.2f})",
    )


def detect_bull_flag(df: pd.DataFrame) -> tuple[Optional[float], float, str]:
    """
    Detect bull flag: strong prior up move + downward-sloping consolidation.

    Returns: (trigger_price, confidence, notes)
    """
    if len(df) < 25:
        return None, 0.0, "insufficient_bars"

    close = df["close"]

    # Check for prior strong up move in last 10-20 bars before consolidation
    lookback = min(30, len(close) - 5)
    prior_move_pct = (close.iloc[-5] - close.iloc[-lookback]) / close.iloc[-lookback]
    if prior_move_pct < 0.03:  # Need at least 3% prior move
        return None, 0.0, f"weak_prior_move({prior_move_pct:.1%})"

    # Consolidation: last 5-15 bars with downward slope
    consol = close.tail(15)
    if len(consol) < 5:
        return None, 0.0, "insufficient_consolidation"

    x = np.arange(len(consol))
    slope, _ = np.polyfit(x, consol.values, 1)

    # Slope should be slightly negative (consolidation, not crash)
    if not (-0.5 < slope / consol.mean() * len(consol) < 0):
        return None, 0.0, f"slope_not_flag({slope:.4f})"

    # Trigger = upper bound of consolidation channel (recent high)
    trigger = consol.max()
    confidence = min(0.9, prior_move_pct * 5 + 0.5)

    return trigger, confidence, f"bull_flag(prior_move={prior_move_pct:.1%},slope={slope:.4f})"


def detect_bear_flag(df: pd.DataFrame) -> tuple[Optional[float], float, str]:
    """
    Detect bear flag: strong prior down move + upward-sloping consolidation.

    Returns: (trigger_price, confidence, notes)
    """
    if len(df) < 25:
        return None, 0.0, "insufficient_bars"

    close = df["close"]

    lookback = min(30, len(close) - 5)
    prior_move_pct = (close.iloc[-lookback] - close.iloc[-5]) / close.iloc[-lookback]
    if prior_move_pct < 0.03:
        return None, 0.0, f"weak_prior_move({prior_move_pct:.1%})"

    consol = close.tail(15)
    if len(consol) < 5:
        return None, 0.0, "insufficient_consolidation"

    x = np.arange(len(consol))
    slope, _ = np.polyfit(x, consol.values, 1)

    # Slope should be slightly positive (bear flag consolidation)
    if not (0 < slope / consol.mean() * len(consol) < 0.5):
        return None, 0.0, f"slope_not_bear_flag({slope:.4f})"

    trigger = consol.min()
    confidence = min(0.9, prior_move_pct * 5 + 0.5)

    return trigger, confidence, f"bear_flag(prior_move={prior_move_pct:.1%},slope={slope:.4f})"


def detect_rounded_top(
    df: pd.DataFrame, min_bars: int = 20, max_bars: int = 120
) -> tuple[Optional[float], float, str]:
    """
    Detect rounded top / inverted saucer — mirror of rounded base.

    Returns: (trigger_price, confidence, notes)
    """
    if len(df) < min_bars:
        return None, 0.0, "insufficient_bars"

    window = df.tail(max_bars)
    close = window["close"]
    volume = window.get("volume", pd.Series(dtype=float))

    smooth = close.rolling(5, min_periods=1).mean()
    smooth_arr = smooth.values

    peak_rel = int(np.argmax(smooth_arr))
    if peak_rel < 5 or peak_rel > len(smooth_arr) - 5:
        return None, 0.0, "peak_at_edge"

    second_deriv = np.gradient(np.gradient(smooth_arr))
    concave_down = np.mean(second_deriv[max(0, peak_rel - 3) : peak_rel + 4]) < 0

    post_peak = close.iloc[peak_rel:]
    neckline = post_peak.min()
    current_price = close.iloc[-1]

    approaching_neckline = current_price <= neckline * 1.03

    ema_state = detect_ema_alignment(df)
    ema_ok = ema_state in ("BEARISH_FAN", "MIXED")

    vol_ok = True
    if len(volume) > 0 and volume.sum() > 0:
        pre_peak_vol = volume.iloc[:peak_rel].mean() if peak_rel > 0 else 0
        post_peak_vol = volume.iloc[peak_rel:].mean()
        vol_ok = post_peak_vol >= pre_peak_vol * 0.8

    weights = {"concave": 0.40, "neckline": 0.30, "ema": 0.20, "vol": 0.10}
    confidence = (
        weights["concave"] * float(concave_down)
        + weights["neckline"] * float(approaching_neckline)
        + weights["ema"] * float(ema_ok)
        + weights["vol"] * float(vol_ok)
    )
    # Quality bonus: top must have meaningful height (> 3% rise then fall)
    peak_price = close.iloc[peak_rel]
    top_height_pct = (peak_price - neckline) / peak_price if peak_price > 0 else 0
    if top_height_pct > 0.05:
        confidence = min(1.0, confidence + 0.10)
    elif top_height_pct < 0.01:
        confidence = confidence * 0.5

    if confidence < 0.5:
        return None, confidence, f"low_confidence({confidence:.2f})"

    return (
        neckline,
        confidence,
        f"rounded_top(height={top_height_pct:.1%},peak_bar={peak_rel},neckline={neckline:.2f})",
    )


def detect_symmetrical_triangle(df: pd.DataFrame) -> tuple[Optional[float], str, float, str]:
    """
    Detect symmetrical triangle: converging upper/lower trendlines.

    Returns: (trigger_price, bias, confidence, notes)
    bias = "LONG" if price likely to break up, "SHORT" if down, "WATCH" if neutral
    """
    if len(df) < 30:
        return None, "WATCH", 0.0, "insufficient_bars"

    close = df["close"]
    high = df.get("high", close)
    low = df.get("low", close)

    window = 40
    h = high.tail(window).values
    l = low.tail(window).values  # noqa: E741  # OHLC convention
    x = np.arange(window)

    # Fit trendlines to highs and lows
    h_slope, h_intercept = np.polyfit(x, h, 1)
    l_slope, l_intercept = np.polyfit(x, l, 1)

    # Symmetrical: upper slope negative, lower slope positive, similar magnitude
    slopes_valid = h_slope < 0 < l_slope
    slope_ratio = abs(h_slope) / (abs(l_slope) + 1e-10)
    slopes_balanced = 0.5 < slope_ratio < 2.0

    if not slopes_valid or not slopes_balanced:
        return None, "WATCH", 0.0, f"slopes_not_triangle(h={h_slope:.4f},l={l_slope:.4f})"

    # Current trendline levels
    upper = h_slope * (window - 1) + h_intercept
    lower = l_slope * (window - 1) + l_intercept
    current_price = close.iloc[-1]

    # Bias: if price closer to upper line → bearish (about to test upper → short on break)
    # if closer to lower → bullish
    mid = (upper + lower) / 2
    bias = "LONG" if current_price > mid else "SHORT"
    trigger = upper if bias == "LONG" else lower

    # Confidence from tightness of triangle
    width_pct = (upper - lower) / mid
    confidence = max(0.3, min(0.85, 1.0 - width_pct * 5))

    return (
        trigger,
        bias,
        confidence,
        f"triangle(upper={upper:.2f},lower={lower:.2f},width={width_pct:.1%})",
    )


def detect_descending_channel_reversal(df: pd.DataFrame) -> tuple[Optional[float], float, str]:
    """
    Detect gap-up reversal from a descending channel.

    A bearish descending channel (parallel lower highs + lower lows) is violated to the upside.

    Returns: (trigger_price, confidence, notes)
    """
    if len(df) < 30:
        return None, 0.0, "insufficient_bars"

    close = df["close"]
    high = df.get("high", close)
    low = df.get("low", close)

    window = 30
    h = high.tail(window).values
    l = low.tail(window).values  # noqa: E741  # OHLC convention
    x = np.arange(window)

    h_slope, h_intercept = np.polyfit(x, h, 1)
    l_slope, l_intercept = np.polyfit(x, l, 1)

    # Descending channel: both slopes negative and roughly parallel
    both_declining = h_slope < 0 and l_slope < 0
    slope_diff = abs(h_slope - l_slope) / (abs(h_slope) + 1e-10)
    roughly_parallel = slope_diff < 0.5

    if not both_declining or not roughly_parallel:
        return None, 0.0, "not_descending_channel"

    # Check if current bar closes above upper channel line
    upper_now = h_slope * (window - 1) + h_intercept
    current_close = close.iloc[-1]
    gap_up_reversal = current_close > upper_now

    if not gap_up_reversal:
        return None, 0.0, "no_gap_up_break"

    confidence = 0.75
    return (
        current_close,
        confidence,
        f"channel_reversal(upper={upper_now:.2f},close={current_close:.2f})",
    )


# ── Relative Strength/Weakness ────────────────────────────────────────────────


def compute_rs_rw(
    df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame] = None
) -> tuple[float, str]:
    """
    Compute relative strength vs benchmark (SPY/QQQ).

    Score: symbol_pct_change - benchmark_pct_change, normalized to [-1, 1]
    Labels: awesome_rs (>0.8) | good_rs (0.5-0.8) | decent_rs (0.2-0.5) |
            neutral (-0.2-0.2) | decent_rw (-0.5--0.2) | dominant_rw (<-0.5)
    """
    if benchmark_df is None or len(benchmark_df) < 10 or len(df) < 10:
        return 0.0, "neutral"

    periods = [5, 10, 20]
    scores = []
    for p in periods:
        if len(df) >= p and len(benchmark_df) >= p:
            sym_ret = (df["close"].iloc[-1] - df["close"].iloc[-p]) / df["close"].iloc[-p]
            bench_ret = (
                benchmark_df["close"].iloc[-1] - benchmark_df["close"].iloc[-p]
            ) / benchmark_df["close"].iloc[-p]
            scores.append(sym_ret - bench_ret)

    if not scores:
        return 0.0, "neutral"

    raw_score = np.mean(scores)
    normalized = max(-1.0, min(1.0, raw_score * 10))  # Scale to [-1, 1]

    if normalized > 0.8:
        label = "awesome_rs"
    elif normalized > 0.5:
        label = "good_rs"
    elif normalized > 0.2:
        label = "decent_rs"
    elif normalized > -0.2:
        label = "neutral"
    elif normalized > -0.5:
        label = "decent_rw"
    else:
        label = "dominant_rw"

    return normalized, label


# ── SOH Detection ─────────────────────────────────────────────────────────────


def detect_soh(df: pd.DataFrame) -> bool:
    """
    Sit On Hands: return True if all 3 conditions met.
    1. Range of last 3 bars < 0.5x ATR(14) → inside-day compression
    2. Volume of last 3 bars < 0.8x 20-day avg volume → light volume
    3. No new HOD/LOD in last 20 bars → no directional thrust
    """
    if len(df) < 25:
        return False

    try:
        from backtest.indicators import wilder_atr

        atr = wilder_atr(df["high"], df["low"], df["close"], period=14)
        atr_val = atr.iloc[-1]
    except Exception:
        atr_val = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]

    # Condition 1: tight range
    last3_range = df["high"].tail(3).max() - df["low"].tail(3).min()
    tight_range = last3_range < 0.5 * atr_val

    # Condition 2: light volume (optional)
    light_vol = True
    if "volume" in df.columns and df["volume"].sum() > 0:
        recent_vol = df["volume"].tail(3).mean()
        avg_vol = df["volume"].tail(20).mean()
        light_vol = recent_vol < 0.8 * avg_vol

    # Condition 3: no new HOD/LOD in last 20 bars
    recent_high = df["high"].tail(20).max()
    recent_low = df["low"].tail(20).min()
    prior_high = df["high"].tail(40).iloc[:20].max() if len(df) >= 40 else recent_high
    prior_low = df["low"].tail(40).iloc[:20].min() if len(df) >= 40 else recent_low
    no_thrust = (recent_high <= prior_high * 1.001) and (recent_low >= prior_low * 0.999)

    return bool(tight_range and light_vol and no_thrust)


# ── Stops and Targets ─────────────────────────────────────────────────────────


def compute_stops_and_targets(
    trigger_price: float, bias: str, hp_levels: list[float], atr_value: float
) -> tuple[float, float, list[float]]:
    """
    Compute two-tier stops and T1/T2/T3 targets.

    Tight stop = trigger ∓ 1.0x ATR
    Riskier stop = trigger ∓ 1.5x ATR
    Targets = next 3 HP levels in direction of trade
    """
    if bias == "LONG":
        tight_stop = trigger_price - 1.0 * atr_value
        riskier_stop = trigger_price - 1.5 * atr_value
        candidate_targets = sorted(lvl for lvl in hp_levels if lvl > trigger_price)
    else:  # SHORT
        tight_stop = trigger_price + 1.0 * atr_value
        riskier_stop = trigger_price + 1.5 * atr_value
        candidate_targets = sorted((lvl for lvl in hp_levels if lvl < trigger_price), reverse=True)

    targets = candidate_targets[:3]  # T1, T2, T3

    # Fallback targets if HP levels don't cover
    if len(targets) < 3:
        for i in range(len(targets), 3):
            if bias == "LONG":
                targets.append(trigger_price + (i + 1) * 1.5 * atr_value)
            else:
                targets.append(trigger_price - (i + 1) * 1.5 * atr_value)

    return tight_stop, riskier_stop, targets


# ── Full Scan ─────────────────────────────────────────────────────────────────


def full_hidden_pivots_scan(
    symbol: str,
    df: pd.DataFrame,
    benchmark_df: Optional[pd.DataFrame] = None,
    timeframe: str = "1d",
) -> HPScanResult:
    """
    Run all HiddenPivots detectors and return the strongest pattern.

    Pattern priority: rounded_base/top > bull/bear_flag > triangle > channel_reversal

    The oscillator crossover acts as gating: if no BULLISH_CROSS/BEARISH_CROSS,
    the bias is WATCH (pattern identified but no entry signal yet).
    """
    if df is None or len(df) < 20:
        return HPScanResult(
            symbol=symbol,
            timeframe=timeframe,
            pattern=None,
            bias="WATCH",
            trigger_price=None,
            tight_stop=None,
            riskier_stop=None,
            notes="insufficient_data",
        )

    # Ensure required columns
    if "close" not in df.columns:
        return HPScanResult(
            symbol=symbol,
            timeframe=timeframe,
            pattern=None,
            bias="WATCH",
            trigger_price=None,
            tight_stop=None,
            riskier_stop=None,
            notes="missing_close_column",
        )
    if "high" not in df.columns:
        df = df.copy()
        df["high"] = df["close"]
        df["low"] = df["close"]

    # --- Run all detectors ---
    ema_alignment = detect_ema_alignment(df)
    osc_state = detect_oscillator_state(df)
    hp_ou, hp_levels, swing_pts = compute_hp_ou_level(df)
    rs_score, rs_label = compute_rs_rw(df, benchmark_df)
    soh = detect_soh(df)

    # ATR for stops
    try:
        from backtest.indicators import wilder_atr

        atr_series = wilder_atr(df["high"], df["low"], df["close"], period=14)
        atr_val = atr_series.iloc[-1]
    except Exception:
        atr_val = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]

    if pd.isna(atr_val) or atr_val <= 0:
        atr_val = df["close"].iloc[-1] * 0.01  # 1% fallback

    # Pattern detection in priority order
    pattern = None
    bias = "WATCH"
    trigger = None
    confidence = 0.0
    notes = ""

    # 1. Rounded base (bullish)
    rb_trigger, rb_conf, rb_notes = detect_rounded_base(df)
    if rb_trigger is not None and rb_conf > 0.5:
        pattern = "rounded_base"
        bias = "LONG"
        trigger = rb_trigger
        confidence = rb_conf
        notes = rb_notes

    # 2. Rounded top (bearish) — only if no bullish pattern found yet
    if pattern is None:
        rt_trigger, rt_conf, rt_notes = detect_rounded_top(df)
        if rt_trigger is not None and rt_conf > 0.5:
            pattern = "rounded_top"
            bias = "SHORT"
            trigger = rt_trigger
            confidence = rt_conf
            notes = rt_notes

    # 3. Bull flag
    if pattern is None:
        bf_trigger, bf_conf, bf_notes = detect_bull_flag(df)
        if bf_trigger is not None and bf_conf > 0.4:
            pattern = "bull_flag"
            bias = "LONG"
            trigger = bf_trigger
            confidence = bf_conf
            notes = bf_notes

    # 4. Bear flag
    if pattern is None:
        brf_trigger, brf_conf, brf_notes = detect_bear_flag(df)
        if brf_trigger is not None and brf_conf > 0.4:
            pattern = "bear_flag"
            bias = "SHORT"
            trigger = brf_trigger
            confidence = brf_conf
            notes = brf_notes

    # 5. Symmetrical triangle
    if pattern is None:
        tri_trigger, tri_bias, tri_conf, tri_notes = detect_symmetrical_triangle(df)
        if tri_trigger is not None and tri_conf > 0.4:
            pattern = "triangle"
            bias = tri_bias
            trigger = tri_trigger
            confidence = tri_conf
            notes = tri_notes

    # 6. Descending channel reversal
    if pattern is None:
        cr_trigger, cr_conf, cr_notes = detect_descending_channel_reversal(df)
        if cr_trigger is not None and cr_conf > 0.5:
            pattern = "channel_reversal"
            bias = "LONG"
            trigger = cr_trigger
            confidence = cr_conf
            notes = cr_notes

    # The pattern's directional bias, captured before SOH/oscillator gating can
    # downgrade the *entry* bias. Stops/targets are computed off this so a gated
    # WATCH setup still ships a usable level ladder (the entry just isn't armed).
    pattern_bias = bias  # "LONG" | "SHORT" | "WATCH" (WATCH == no directional pattern)

    # --- SOH override ---
    if soh:
        bias = "SOH"

    # --- Oscillator gating ---
    # HP rule: NO ENTRY without oscillator crossover circle.
    # "RISING" / "FALLING" = developing setup → WATCH, not entry.
    # Only a confirmed crossover (BULLISH_CROSS / BEARISH_CROSS) triggers entry.
    if pattern is not None and bias in ("LONG", "SHORT"):
        if bias == "LONG" and osc_state != "BULLISH_CROSS":
            bias = "WATCH"
        elif bias == "SHORT" and osc_state != "BEARISH_CROSS":
            bias = "WATCH"

    # Recency of the last oscillator cross — informs how stale a WATCH setup is.
    bars_since_cross, last_cross_dir = bars_since_last_cross(df)

    # --- Compute stops and targets ---
    # Populate the ladder whenever there is a directional pattern, even if the
    # entry bias was gated to WATCH/SOH. The ladder describes the setup; arming
    # the entry is a separate question answered by `bias`.
    tight_stop = None
    riskier_stop = None
    targets = []

    if trigger is not None and pattern_bias in ("LONG", "SHORT"):
        tight_stop, riskier_stop, targets = compute_stops_and_targets(
            trigger_price=trigger,
            bias=pattern_bias,
            hp_levels=hp_levels,
            atr_value=atr_val,
        )

    return HPScanResult(
        symbol=symbol,
        timeframe=timeframe,
        pattern=pattern,
        bias=bias,
        trigger_price=float(round(trigger, 4)) if trigger else None,
        tight_stop=float(round(tight_stop, 4)) if tight_stop else None,
        riskier_stop=float(round(riskier_stop, 4)) if riskier_stop else None,
        targets=[float(round(t, 4)) for t in targets],
        hp_ou_level=float(round(hp_ou, 4)) if hp_ou else None,
        hp_levels=[float(round(l, 4)) for l in hp_levels],  # noqa: E741  # OHLC convention
        ema_alignment=ema_alignment,
        rs_rw_score=float(round(rs_score, 3)),
        rs_rw_label=rs_label,
        soh=bool(soh),
        oscillator_state=osc_state,
        bars_since_cross=int(bars_since_cross),
        last_cross_dir=last_cross_dir,
        confidence=float(round(confidence, 3)),
        notes=notes,
    )
