"""
JARVIS TRADER — Backtest Indicators
Pure-Python implementations of all ThinkorSwim-derived indicators.
No TA-Lib dependency. Uses numpy and pandas only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Average True Range (used by Saty ATR Levels script)."""
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)

    atr = pd.Series(index=close.index, dtype=float)
    atr.iloc[:period] = np.nan
    if len(tr) >= period:
        atr.iloc[period - 1] = tr.iloc[:period].mean()
        for i in range(period, len(tr)):
            atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
    return atr


def sma_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """SMA of True Range (used by Keltner channels)."""
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


def kama(
    close: pd.Series, period: int = 10, fast_period: int = 2, slow_period: int = 30
) -> pd.Series:
    """
    Kaufman Adaptive Moving Average (KAMA).
    Used by NextSignalMomentum script. Period=10, slow=30.
    """
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    result = pd.Series(np.nan, index=close.index, dtype=float)

    if len(close) < period:
        return result

    close_values = close.to_numpy(dtype=float)
    result_values = np.full(len(close), np.nan, dtype=float)
    volatility_values = close.diff().abs().rolling(period).sum().to_numpy(dtype=float)
    result_values[period - 1] = close_values[period - 1]

    for i in range(period, len(close)):
        change = abs(close_values[i] - close_values[i - period])
        volatility = volatility_values[i]

        if volatility == 0:
            er = 0.0
        else:
            er = change / volatility

        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        result_values[i] = result_values[i - 1] + sc * (close_values[i] - result_values[i - 1])

    return pd.Series(result_values, index=close.index, dtype=float)


def stc(
    close: pd.Series, fast: int = 23, slow: int = 50, k_period: int = 10, d_period: int = 3
) -> pd.Series:
    """
    Schaff Trend Cycle (STC).
    Used by shared_OB_STYLE_CYCLE script.
    Parameters: fast=23, slow=50, K=10, D=3.
    Oversold=19, Overbought=88.
    Returns Series 0-100.
    """
    # MACD line
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow

    def _stoch(series: pd.Series, period: int) -> pd.Series:
        lowest = series.rolling(period).min()
        highest = series.rolling(period).max()
        denom = highest - lowest
        result = pd.Series(index=series.index, dtype=float)
        mask = denom != 0
        result[mask] = (series[mask] - lowest[mask]) / denom[mask] * 100
        result[~mask] = 50.0
        return result

    # First stochastic of MACD
    k1 = _stoch(macd_line, k_period)
    d1 = k1.ewm(span=d_period, adjust=False).mean()

    # Second stochastic of smoothed
    k2 = _stoch(d1, k_period)
    stc_val = k2.ewm(span=d_period, adjust=False).mean()

    return stc_val.clip(0, 100)


def phase_oscillator(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ema_len: int = 21,
    atr_len: int = 14,
    bb_len: int = 21,
    bb_std: float = 2.0,
) -> Tuple[pd.Series, pd.Series]:
    """
    Saty Phase Oscillator.
    Returns (phase_value, is_compression).
    Phase = (close - EMA) / (3 * ATR) * 100, clamped [-100, 100].
    Compression = Bollinger Bands narrower than ATR bands.
    """
    ema = close.ewm(span=ema_len, adjust=False).mean()
    atr = wilder_atr(high, low, close, atr_len)

    phase = ((close - ema) / (3 * atr * (atr > 0).astype(float) + 1e-10)) * 100
    phase = phase.clip(-100, 100)

    # Bollinger Bands on close
    bb_mid = close.rolling(bb_len).mean()
    bb_std_val = close.rolling(bb_len).std()
    bb_upper = bb_mid + bb_std * bb_std_val
    bb_lower = bb_mid - bb_std * bb_std_val
    bb_width = bb_upper - bb_lower

    # ATR bands width
    atr_band_width = 2 * atr

    # Compression when BB width < ATR band width
    is_compression = (bb_width < atr_band_width).fillna(False)

    return phase, is_compression


def volume_stack(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Saty Volume Stack.
    Returns (buy_vol, sell_vol, buy_pct).
    buy_vol = volume * (close - low) / (high - low)
    sell_vol = volume * (high - close) / (high - low)
    """
    hl_range = (high - low).replace(0, np.nan)
    buy_vol = volume * (close - low) / hl_range
    sell_vol = volume * (high - close) / hl_range
    buy_vol = buy_vol.fillna(volume * 0.5)
    sell_vol = sell_vol.fillna(volume * 0.5)
    total = buy_vol + sell_vol
    buy_pct = (buy_vol / total.replace(0, np.nan) * 100).fillna(50.0)
    return buy_vol, sell_vol, buy_pct


def keltner_channels(
    close: pd.Series, high: pd.Series, low: pd.Series, sma_len: int = 20, atr_factor: float = 1.5
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Keltner Channel (used by OB_OMEGA and KMaster scripts).
    Returns (upper, basis, lower).
    Basis = SMA(20), ATR = SMA of True Range.
    """
    basis = close.rolling(sma_len).mean()
    atr = sma_atr(high, low, close, sma_len)
    upper = basis + atr_factor * atr
    lower = basis - atr_factor * atr
    return upper, basis, lower


def keltner_channels_mtf(
    df: pd.DataFrame,
    rule: str = "4h",
    sma_len: int = 20,
    atr_factor: float = 3.0,
    developing: bool = True,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Multi-timeframe Keltner Channel — port of jp_keltner_multi_timeframe.ts.

    The ThinkScript computes a Keltner (SMA basis +/- factor*SMA(TrueRange)) on a
    user-selected ``iAggregationPeriod`` and plots it on the base chart. This
    reproduces that: it aggregates the base bars to ``rule`` (e.g. "4h" =
    FOUR_HOURS) and maps the higher-timeframe Keltner back onto every base bar.

    developing=True matches TOS: the current higher-TF bar is the *developing*
    aggregate of the base bars seen so far, so the line updates each base bar.
    developing=False uses only completed higher-TF bars (one extra bar of lag).
    Both are point-in-time safe — a base bar at t uses only base bars <= t.
    With ``rule`` equal to the base bar frequency this collapses exactly to
    ``keltner_channels``.

    Returns (upper, basis, lower) Series on df.index.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("keltner_channels_mtf requires a DatetimeIndex")
    idx = df.index
    win = idx.floor(rule)
    grp = df.groupby(win)
    htf_close = grp["close"].last()
    htf_high = grp["high"].max()
    htf_low = grp["low"].min()
    tr_htf = pd.concat(
        [htf_high - htf_low,
         (htf_high - htf_close.shift(1)).abs(),
         (htf_low - htf_close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)

    def _to_base(s: pd.Series) -> pd.Series:
        return pd.Series(s.reindex(win).to_numpy(), index=idx)

    if developing:
        prev_close = _to_base(htf_close.shift(1))  # last completed HTF close
        dev_high = grp["high"].cummax()
        dev_low = grp["low"].cummin()
        tr_dev = pd.concat(
            [dev_high - dev_low, (dev_high - prev_close).abs(), (dev_low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        comp_close = _to_base(htf_close.shift(1).rolling(sma_len - 1).sum())
        comp_tr = _to_base(tr_htf.shift(1).rolling(sma_len - 1).sum())
        basis = (comp_close + df["close"]) / sma_len
        shift = atr_factor * (comp_tr + tr_dev) / sma_len
    else:
        basis = _to_base(htf_close.rolling(sma_len).mean().shift(1))
        shift = _to_base(atr_factor * tr_htf.rolling(sma_len).mean().shift(1))
    return basis + shift, basis, basis - shift


def keltner_cloud_mtf(
    df: pd.DataFrame,
    rule: str = "4h",
    sma_len: int = 20,
    inner_factor: float = 1.5,
    outer_factor: float = 2.0,
    developing: bool = True,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Dual-band multi-timeframe Keltner — port of the OB_OMEGA / JBOYD cloud.

    The OB_OMEGA study plots two Keltner bands (inner 1.5x, outer 2.0x) on a
    higher aggregation and shades the cloud between them. Reuses
    ``keltner_channels_mtf`` (one aggregation, scaled to both factors) so the
    basis and TR are computed once. The cloud shading itself is cosmetic; this
    returns the band levels that matter for signals.

    Returns (upper_outer, upper_inner, basis, lower_inner, lower_outer).
    """
    upper_inner, basis, lower_inner = keltner_channels_mtf(
        df, rule=rule, sma_len=sma_len, atr_factor=inner_factor, developing=developing
    )
    scale = outer_factor / inner_factor
    shift_inner = upper_inner - basis
    upper_outer = basis + scale * shift_inner
    lower_outer = basis - scale * shift_inner
    return upper_outer, upper_inner, basis, lower_inner, lower_outer


def macd_primer_mtf(
    df: pd.DataFrame,
    rule: str = "4h",
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    developing: bool = True,
) -> pd.Series:
    """MACD primer (OB_OMEGA cloud color) on a higher aggregation.

    Returns the MACD histogram (macd - signal) on the ``rule`` timeframe mapped
    to base bars. Uses only completed higher-TF bars (shift(1)) so it is
    point-in-time safe; ``developing`` is accepted for API symmetry but the
    histogram always lags by one completed higher-TF bar.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("macd_primer_mtf requires a DatetimeIndex")
    idx = df.index
    win = idx.floor(rule)
    htf_close = df.groupby(win)["close"].last()
    ema_fast = htf_close.ewm(span=fast, adjust=False).mean()
    ema_slow = htf_close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    hist = (macd - macd.ewm(span=signal, adjust=False).mean()).shift(1)
    return pd.Series(hist.reindex(win).to_numpy(), index=idx)


def ib_levels(
    high: pd.Series,
    low: pd.Series,
    timestamps: pd.DatetimeIndex,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    ib_minutes: int = 60,
) -> pd.DataFrame:
    """
    Initial Balance levels for each trading day.
    Returns DataFrame indexed by date with IB levels.
    """
    if not isinstance(timestamps, pd.DatetimeIndex):
        timestamps = pd.DatetimeIndex(timestamps)

    df = pd.DataFrame({"high": high.values, "low": low.values, "ts": timestamps})
    df["date"] = df["ts"].dt.date
    df["time_min"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute

    open_min = market_open_hour * 60 + market_open_minute
    close_min = open_min + ib_minutes

    ib_data = {}
    for date, group in df.groupby("date"):
        ib_bars = group[(group["time_min"] >= open_min) & (group["time_min"] < close_min)]
        if len(ib_bars) == 0:
            continue
        ib_high = ib_bars["high"].max()
        ib_low = ib_bars["low"].min()
        ib_range = ib_high - ib_low
        ib_data[date] = {
            "ib_high": ib_high,
            "ib_low": ib_low,
            "ib_range": ib_range,
            "quad_25": ib_low + 0.25 * ib_range,
            "quad_50": ib_low + 0.50 * ib_range,
            "quad_75": ib_low + 0.75 * ib_range,
            "ext_50_up": ib_high + 0.50 * ib_range,
            "ext_100_up": ib_high + 1.00 * ib_range,
            "ext_300_up": ib_high + 3.00 * ib_range,
            "ext_50_down": ib_low - 0.50 * ib_range,
            "ext_100_down": ib_low - 1.00 * ib_range,
            "ext_300_down": ib_low - 3.00 * ib_range,
        }

    return pd.DataFrame.from_dict(ib_data, orient="index")


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 50) -> pd.Series:
    """
    Commodity Channel Index (CCI).
    Used by shared_mtftrendbar script with period=50.
    Zero-cross = trend direction change.
    """
    typical = (high + low + close) / 3
    ma = typical.rolling(period).mean()
    mean_dev = typical.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    result = (typical - ma) / (0.015 * mean_dev.replace(0, np.nan))
    return result.fillna(0)


def atr_fib_levels(
    prior_close: float, atr: float, ratios: Optional[List[float]] = None
) -> Dict[str, float]:
    """
    ATR Fibonacci levels from prior close (Saty ATR Levels script).
    Returns flat dict with both up and down levels.
    """
    if ratios is None:
        ratios = [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.236, 1.5, 2.0, 3.0]

    result = {}
    for r in ratios:
        key = str(r)
        result[f"up_{key}"] = prior_close + r * atr
        result[f"down_{key}"] = prior_close - r * atr
    return result


def range_consumed_pct(current_price: float, prior_close: float, atr: float) -> float:
    """
    How much of the daily ATR range has been consumed.
    < 70% = room to run, > 90% = exhausted.
    """
    if atr <= 0:
        return 0.0
    return min(200.0, abs(current_price - prior_close) / atr * 100)


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Volume Ratio: current volume / rolling mean volume.
    Values > 1.0 indicate above-average volume (high conviction).
    Values < 1.0 indicate below-average volume (low conviction).
    """
    vol_ma = volume.rolling(period).mean()
    return (volume / vol_ma.replace(0, np.nan)).fillna(0.0)


def ema_ribbon(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    EMA Ribbon (8/21/34) from Saty ATR Levels script.
    Returns (ema_8, ema_21, ema_34).
    All up = bullish, all down = bearish, mixed = neutral.
    """
    ema_8 = close.ewm(span=8, adjust=False).mean()
    ema_21 = close.ewm(span=21, adjust=False).mean()
    ema_34 = close.ewm(span=34, adjust=False).mean()
    return ema_8, ema_21, ema_34


# Saty's fib-ATR ratios (faithful to the AA Saty ATR Levels ThinkScript).
# 0.236 is the directional trigger; 1.0 is the full-ATR target; >1.0 are extensions.
SATY_ATR_RATIOS: Tuple[float, ...] = (
    0.236,
    0.382,
    0.5,
    0.618,
    0.786,
    1.0,
    1.236,
    1.382,
    1.5,
    1.618,
    1.786,
    2.0,
    2.236,
    2.382,
    2.5,
    2.618,
    2.786,
    3.0,
)
SATY_CLEAN_RATIOS: Tuple[float, ...] = (0.236, 0.618, 1.0, 1.618)
SATY_TRIGGER_RATIO = 0.236
SATY_CHASE_RANGE_PCT_ATR = 90.0
SATY_CHASE_DISPLACEMENT_ATR = 0.786


def _round_to_tick(value: float, tick_size: float | None = None) -> float:
    """Round price-like values to an optional instrument tick size."""
    if tick_size is None or tick_size <= 0:
        return float(value)
    return round(float(value) / tick_size) * tick_size


def saty_atr_levels(
    prior_close: float,
    atr: float,
    *,
    ratios: Tuple[float, ...] = SATY_ATR_RATIOS,
    tick_size: float | None = None,
) -> dict:
    """Saty ATR Levels: fib-ATR price levels anchored to the prior session close.

    Ported from the Saty ATR Levels ThinkScript study. Unlike entry-anchored ATR
    targets, these levels anchor to the prior close, so the same read-only map
    holds for every decision on the day. The return shape preserves the legacy
    ``call_trigger``/``put_trigger`` keys while adding neutral trigger aliases.
    """
    pc = _round_to_tick(float(prior_close), tick_size)
    a = float(atr) if atr and atr > 0 else 0.0
    upper = {r: _round_to_tick(pc + r * a, tick_size) for r in ratios}
    lower = {r: _round_to_tick(pc - r * a, tick_size) for r in ratios}
    upper_trigger = upper[SATY_TRIGGER_RATIO]
    lower_trigger = lower[SATY_TRIGGER_RATIO]
    return {
        "prior_close": pc,
        "atr": a,
        # Legacy aliases retained for existing callers/tests.
        "call_trigger": upper_trigger,
        "put_trigger": lower_trigger,
        # Preferred neutral labels for dashboard/decision-support use.
        "upper_trigger": upper_trigger,
        "lower_trigger": lower_trigger,
        "upper": upper,
        "lower": lower,
    }


def saty_trigger_state(price: float, levels: dict) -> str:
    """Neutral trigger state; avoids implying calls/puts are standalone entries."""
    if not levels or levels.get("atr", 0) <= 0:
        return "neutral"
    if price > levels["upper_trigger"]:
        return "upside_trigger"
    if price < levels["lower_trigger"]:
        return "downside_trigger"
    return "inside_trigger_band"


def saty_bias(price: float, levels: dict) -> str:
    """Legacy directional bias wrapper: long/short/neutral.

    Kept for compatibility. New dashboard/port code should prefer
    :func:`saty_trigger_state`, which is deliberately non-prescriptive.
    """
    state = saty_trigger_state(price, levels)
    if state == "upside_trigger":
        return "long"
    if state == "downside_trigger":
        return "short"
    return "neutral"


def saty_nearest_target(price: float, side: str, levels: dict) -> Optional[float]:
    """Nearest Saty ATR level beyond ``price`` in the selected direction."""
    if not levels or levels.get("atr", 0) <= 0:
        return None
    if side in ("long", "buy", "up", "upside"):
        above = sorted(p for p in levels["upper"].values() if p > price)
        return above[0] if above else None
    if side in ("short", "sell", "down", "downside"):
        below = sorted((p for p in levels["lower"].values() if p < price), reverse=True)
        return below[0] if below else None
    return None


def _trend_ribbon_state(
    price: float,
    fast_ema: float | None = None,
    pivot_ema: float | None = None,
    slow_ema: float | None = None,
) -> str:
    """8/21/34 pivot-ribbon state, timeframe supplied by caller."""
    if fast_ema is None or pivot_ema is None or slow_ema is None:
        return "unknown"
    if price >= fast_ema >= pivot_ema >= slow_ema:
        return "bullish"
    if price <= fast_ema <= pivot_ema <= slow_ema:
        return "bearish"
    return "mixed"


def _range_state(displacement_atr: float, range_pct_atr: float | None) -> str:
    """Classify price location in the Saty ATR map."""
    abs_disp = abs(displacement_atr)
    direction = "up" if displacement_atr > 0 else "down" if displacement_atr < 0 else "neutral"
    if range_pct_atr is not None and range_pct_atr >= SATY_CHASE_RANGE_PCT_ATR and abs_disp >= 1.0:
        return f"full_atr_extension_{direction}"
    if abs_disp >= 1.618:
        return f"extension_{direction}"
    if abs_disp >= 1.0:
        return f"full_atr_{direction}"
    if abs_disp >= 0.618:
        return f"range_expansion_{direction}"
    if abs_disp >= SATY_TRIGGER_RATIO:
        return f"initiative_{direction}"
    return "inside_trigger_band"


def saty_atr_context(
    *,
    price: float,
    prior_close: float,
    atr: float,
    period_high: float | None = None,
    period_low: float | None = None,
    day_range: float | None = None,
    session_open: float | None = None,
    vwap: float | None = None,
    fast_ema: float | None = None,
    pivot_ema: float | None = None,
    slow_ema: float | None = None,
    opening_range_high: float | None = None,
    opening_range_low: float | None = None,
    atr_percentile: float | None = None,
    tick_size: float | None = None,
) -> dict[str, Any]:
    """Causal read-only Saty ATR Pro context object.

    This deliberately does not emit an execution signal. It normalizes price by
    prior-close anchored ATR, tags trigger/extension/chase states, and exposes a
    small confluence score for dashboard context and later parity tests.
    """
    levels = saty_atr_levels(prior_close, atr, tick_size=tick_size)
    a = float(levels["atr"])
    px = _round_to_tick(float(price), tick_size)

    if a <= 0:
        return {
            "price": px,
            "levels": levels,
            "state": {
                "trigger_state": "neutral",
                "range_state": "invalid_atr",
                "chase_risk": False,
                "trend_ribbon": "unknown",
                "vwap_state": "unknown",
                "opening_range_state": "unknown",
            },
            "metrics": {
                "atr_displacement": 0.0,
                "range_pct_atr": None,
                "gap_atr": None,
                "atr_percentile": atr_percentile,
            },
            "next_levels": {"up": None, "down": None},
            "context_score": {"up": 0, "down": 0},
        }

    range_pct_atr = None
    if day_range is not None:
        range_pct_atr = round((float(day_range) / a) * 100.0, 1)
    elif period_high is not None and period_low is not None:
        range_pct_atr = round(((float(period_high) - float(period_low)) / a) * 100.0, 1)

    atr_displacement = round((px - levels["prior_close"]) / a, 3)
    gap_atr = None if session_open is None else round((float(session_open) - levels["prior_close"]) / a, 3)
    trigger_state = saty_trigger_state(px, levels)
    range_state = _range_state(atr_displacement, range_pct_atr)
    chase_risk = bool(
        range_pct_atr is not None
        and range_pct_atr >= SATY_CHASE_RANGE_PCT_ATR
        and abs(atr_displacement) >= SATY_CHASE_DISPLACEMENT_ATR
    )

    vwap_state = "unknown"
    if vwap is not None:
        vwap_state = "above" if px > float(vwap) else "below" if px < float(vwap) else "at"

    opening_range_state = "unknown"
    if opening_range_high is not None and px > float(opening_range_high):
        opening_range_state = "above_orh"
    elif opening_range_low is not None and px < float(opening_range_low):
        opening_range_state = "below_orl"
    elif opening_range_high is not None and opening_range_low is not None:
        opening_range_state = "inside_or"

    trend_state = _trend_ribbon_state(px, fast_ema, pivot_ema, slow_ema)

    up_score = int(trigger_state == "upside_trigger")
    up_score += int(vwap_state == "above")
    up_score += int(trend_state == "bullish")
    up_score += int(opening_range_state == "above_orh")
    up_score -= int(chase_risk)

    down_score = int(trigger_state == "downside_trigger")
    down_score += int(vwap_state == "below")
    down_score += int(trend_state == "bearish")
    down_score += int(opening_range_state == "below_orl")
    down_score -= int(chase_risk)

    return {
        "price": px,
        "levels": levels,
        "state": {
            "trigger_state": trigger_state,
            "range_state": range_state,
            "chase_risk": chase_risk,
            "trend_ribbon": trend_state,
            "vwap_state": vwap_state,
            "opening_range_state": opening_range_state,
        },
        "metrics": {
            "atr_displacement": atr_displacement,
            "range_pct_atr": range_pct_atr,
            "gap_atr": gap_atr,
            "atr_percentile": atr_percentile,
        },
        "next_levels": {
            "up": saty_nearest_target(px, "upside", levels),
            "down": saty_nearest_target(px, "downside", levels),
        },
        "context_score": {"up": up_score, "down": down_score},
    }


# ─── AutoTrade-derived indicators (Phase 1) ───────────────────────────


def donchian_channels(
    high: pd.Series, low: pd.Series, entry_period: int = 20, exit_period: int = 6
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Donchian breakout + exit channels.
    Shifted 1 bar to prevent look-ahead bias.
    Returns (entry_high, entry_low, exit_high, exit_low).
    """
    entry_high = high.shift(1).rolling(entry_period).max()
    entry_low = low.shift(1).rolling(entry_period).min()
    exit_high = high.shift(1).rolling(exit_period).max()
    exit_low = low.shift(1).rolling(exit_period).min()
    return entry_high, entry_low, exit_high, exit_low


def ema_slope(close: pd.Series, period: int = 21, lookback: int = 3) -> pd.Series:
    """
    Slope of EMA over lookback bars.
    Positive = rising trend confirmation, negative = declining.
    Filters flat crossovers where EMA is directionless.
    """
    ema = close.ewm(span=period, adjust=False).mean()
    return ema - ema.shift(lookback)


def atr_regime(
    high: pd.Series, low: pd.Series, close: pd.Series,
    atr_period: int = 14, sma_period: int = 20
) -> pd.Series:
    """
    ATR regime filter: True when volatility is expanding (ATR > SMA of ATR).
    Only enter trades when volatility is expanding — filters choppy markets.
    """
    atr = wilder_atr(high, low, close, atr_period)
    atr_sma = atr.rolling(sma_period).mean()
    return atr > atr_sma


def volume_regime(volume: pd.Series, lookback: int = 20) -> pd.Series:
    """
    Volume regime classification: HIGH (>1.5x avg), NORMAL, LOW (<0.67x avg).
    HIGH volume confirms institutional participation in moves.
    """
    avg = volume.rolling(lookback).mean()
    ratio = volume / avg.replace(0, np.nan)
    result = pd.Series("NORMAL", index=volume.index)
    result[ratio > 1.5] = "HIGH"
    result[ratio < 0.67] = "LOW"
    return result


def _wilders_average(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing, seeded with the SMA of the first `period` values.

    Matches ThinkScript's AverageType.WILDERS (the recursive
    prev*(n-1)/n + value/n form), identical to the seeding used by
    ``wilder_atr`` above so the two stay consistent.
    """
    out = pd.Series(index=series.index, dtype=float)
    if len(series) < period:
        return out
    out.iloc[: period - 1] = np.nan
    out.iloc[period - 1] = series.iloc[:period].mean()
    for i in range(period, len(series)):
        out.iloc[i] = (out.iloc[i - 1] * (period - 1) + series.iloc[i]) / period
    return out


def atr_trailing_stop(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 5,
    factor: float = 3.5,
    first_trade_long: bool = True,
    trail_type: str = "modified",
) -> Tuple[pd.Series, pd.Series]:
    """ATR Trailing Stop — faithful reproduction of the ThinkorSwim built-in.

    This is the dotted support/resistance line on Matt's /ES chart, legend
    ``ATRTrailingStop (modified, 5, 3.5, long, WILDERS)``. It is a Sylvain
    Vervoort style stop-and-reverse line: it trails below price while long and
    above price while short, flipping state on a close through the line.

    Args:
        period           : ATR length (TOS default for this study = 5).
        factor           : ATR multiplier (TOS default = 3.5).
        first_trade_long : seed the very first bar's state long (TOS default).
        trail_type       : "modified" uses the HiLo/HRef/LRef true-range
                           variant (TOS default); "unmodified" uses classic
                           true range.

    Returns:
        (trail, state) where ``trail`` is the stop line and ``state`` is +1.0
        when long (line is support, below price) / -1.0 when short (line is
        resistance, above price). Point-in-time safe: ``trail.iloc[i]`` uses
        only bars <= i.
    """
    orig_index = close.index
    high = high.astype(float).reset_index(drop=True)
    low = low.astype(float).reset_index(drop=True)
    close = close.astype(float).reset_index(drop=True)
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    if trail_type == "modified":
        hl_avg = (high - low).rolling(period).mean()
        hilo = pd.concat([high - low, 1.5 * hl_avg], axis=1).min(axis=1)
        href = np.where(
            low <= prev_high,
            high - prev_close,
            (high - prev_close) - 0.5 * (low - prev_high),
        )
        lref = np.where(
            high >= prev_low,
            prev_close - low,
            (prev_close - low) - 0.5 * (prev_low - high),
        )
        true_range = pd.concat(
            [hilo, pd.Series(href, index=hilo.index), pd.Series(lref, index=hilo.index)],
            axis=1,
        ).max(axis=1)
    else:
        true_range = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)

    loss = factor * _wilders_average(true_range, period)

    n = len(close)
    trail = np.full(n, np.nan)
    state = np.full(n, np.nan)
    started = False
    for i in range(n):
        if pd.isna(loss.iloc[i]):
            continue
        c = close.iloc[i]
        if not started:
            state[i] = 1.0 if first_trade_long else -1.0
            trail[i] = c - loss.iloc[i] if first_trade_long else c + loss.iloc[i]
            started = True
            continue
        prev_trail = trail[i - 1]
        prev_state = state[i - 1]
        if prev_state == 1.0:
            if c > prev_trail:
                state[i] = 1.0
                trail[i] = max(prev_trail, c - loss.iloc[i])
            else:
                state[i] = -1.0
                trail[i] = c + loss.iloc[i]
        else:
            if c < prev_trail:
                state[i] = -1.0
                trail[i] = min(prev_trail, c + loss.iloc[i])
            else:
                state[i] = 1.0
                trail[i] = c - loss.iloc[i]

    return (
        pd.Series(trail, index=orig_index),
        pd.Series(state, index=orig_index),
    )


def compute_vwap(df: "pd.DataFrame", session_reset: bool = True) -> "pd.Series":
    """
    Volume-Weighted Average Price.

    Resets at the start of each trading day when session_reset=True.
    Standard formula: cumsum(typical_price * volume) / cumsum(volume)

    Args:
        df: DataFrame with columns: high, low, close, volume. Index must be datetime.
        session_reset: Reset accumulation at each new trading day (True for intraday use).

    Returns:
        pd.Series named 'vwap', same index as df.
    """
    import pandas as pd

    typical_price = (df['high'] + df['low'] + df['close']) / 3.0
    dollar_volume = typical_price * df['volume']

    if session_reset:
        try:
            if hasattr(df.index, 'date'):
                dates = df.index.date
            else:
                dates = pd.to_datetime(df.index).dt.date

            cumulative_dv = dollar_volume.groupby(dates).cumsum()
            cumulative_v = df['volume'].groupby(dates).cumsum()
        except Exception:
            # Fall back to rolling VWAP if date grouping fails
            cumulative_dv = dollar_volume.cumsum()
            cumulative_v = df['volume'].cumsum()
    else:
        cumulative_dv = dollar_volume.cumsum()
        cumulative_v = df['volume'].cumsum()

    vwap = cumulative_dv / cumulative_v.replace(0, float('nan'))
    return vwap.rename('vwap')


def compute_adx(df: "pd.DataFrame", period: int = 14) -> "pd.DataFrame":
    """
    Average Directional Index (ADX) with +DI and -DI.

    ADX measures trend strength (0-100):
    - ADX >= 25: strong trend
    - ADX 20-25: developing trend
    - ADX < 20: weak/ranging market

    Returns DataFrame with columns: adx, adx_norm (0-1), plus_di, minus_di
    """
    import numpy as np
    import pandas as pd

    high = df['high']
    low = df['low']
    close = df['close']

    # True Range components
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    # Wilder's smoothed averages (standard RMA: seed = sum of first period bars)
    def wilder_smooth(series, period):
        """Wilder RMA seeded with sum of first period values."""
        result = series.copy().astype(float)
        result.iloc[:period] = float('nan')
        result.iloc[period - 1] = series.iloc[:period].sum()
        for i in range(period, len(series)):
            result.iloc[i] = result.iloc[i-1] - (result.iloc[i-1] / period) + series.iloc[i]
        return result

    tr_smooth = wilder_smooth(tr, period)
    plus_dm_smooth = wilder_smooth(plus_dm, period)
    minus_dm_smooth = wilder_smooth(minus_dm, period)

    plus_di = 100 * plus_dm_smooth / tr_smooth.replace(0, float('nan'))
    minus_di = 100 * minus_dm_smooth / tr_smooth.replace(0, float('nan'))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('nan'))

    # ADX: Wilder smooth of DX, seeded with mean of first `period` valid DX values.
    # DX is NaN for first (period-1) bars, so we seed from index (2*period-2).
    adx = pd.Series(float('nan'), index=df.index)
    seed_end = 2 * period - 2  # inclusive index where the first valid DX batch ends
    if len(dx) > seed_end:
        valid_dx = dx.iloc[period - 1: seed_end + 1].dropna()
        if len(valid_dx) > 0:
            adx.iloc[seed_end] = valid_dx.mean()
            for i in range(seed_end + 1, len(dx)):
                if pd.isna(dx.iloc[i]):
                    adx.iloc[i] = adx.iloc[i - 1]
                else:
                    adx.iloc[i] = (adx.iloc[i - 1] * (period - 1) + dx.iloc[i]) / period

    return pd.DataFrame({
        'adx': adx,
        'adx_norm': adx / 100.0,
        'plus_di': plus_di,
        'minus_di': minus_di,
    }, index=df.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (0-100).
    Entry filter: >54 for longs, <46 for shorts.
    Exit trigger: crosses 50 midpoint.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's smoothing (same as EMA with alpha=1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def fib_ema_stack(close: pd.Series) -> Dict[str, pd.Series]:
    """
    Fibonacci-period EMA stack: 8, 13, 21, 34, 55, 89, 144.
    Extended trend analysis — all aligned = strong trend.
    """
    periods = [8, 13, 21, 34, 55, 89, 144]
    return {f"ema_{p}": close.ewm(span=p, adjust=False).mean() for p in periods}


# ─── Futures-adapted strategy indicators (Phase 2) ───────────────────────────


def compute_roc(
    close: pd.Series,
    period: int = 10,
) -> pd.Series:
    """
    Rate of Change (momentum oscillator).
    RoC = (close / close[N periods ago] - 1) * 100

    Positive RoC = upward momentum (price higher than N bars ago)
    Negative RoC = downward momentum
    Threshold: |RoC| > 0.3% = meaningful momentum signal

    For MES/MCL/MNQ 1h bars, period=10 = ~10 hours of momentum lookback.
    """
    return ((close / close.shift(period)) - 1) * 100.0


def compute_trin(advancing_issues: int, declining_issues: int,
                 advancing_volume: float, declining_volume: float) -> Optional[float]:
    """
    Compute TRIN (Arms Index / Short-Term Trading Index).

    TRIN = (Advancing Issues / Declining Issues) / (Advancing Volume / Declining Volume)

    Interpretation:
    - TRIN < 0.60: Blow-off top / extreme buying — caution for LONG entries
    - TRIN 0.60-1.00: Bullish breadth
    - TRIN 1.00-1.40: Bearish breadth
    - TRIN > 2.00: Capitulation / extreme selling — potential reversal

    Returns None if any input is zero (division guard).
    """
    if declining_issues == 0 or declining_volume == 0:
        return None

    advance_decline_ratio = advancing_issues / declining_issues
    advance_decline_vol_ratio = advancing_volume / declining_volume

    if advance_decline_vol_ratio == 0:
        return None

    return advance_decline_ratio / advance_decline_vol_ratio


def classify_trin(trin_value: Optional[float]) -> str:
    """Classify TRIN value into a regime signal."""
    if trin_value is None:
        return "UNAVAILABLE"
    if trin_value < 0.60:
        return "BLOWOFF_TOP"       # Extreme buying — caution for longs
    elif trin_value < 1.00:
        return "BULLISH"
    elif trin_value < 1.40:
        return "BEARISH"
    elif trin_value < 2.00:
        return "OVERSOLD"
    else:
        return "CAPITULATION"      # Extreme selling — potential reversal


def compute_vwap_zscore(
    close: pd.Series,
    vwap: pd.Series,
    atr: pd.Series,
) -> pd.Series:
    """
    VWAP deviation z-score: how many ATR units is price from VWAP.

    z = (close - vwap) / atr

    z > +1.2 → price extended above VWAP (mean-reversion short opportunity)
    z < -1.2 → price extended below VWAP (mean-reversion long opportunity)
    |z| < 0.5 → price near VWAP (neutral)

    Uses ATR as normalizer — scale-invariant across instruments (MES vs MCL).
    Used as convergence/mean-reversion signal when opposite to trend bias.
    """
    deviation = close - vwap
    zscore = deviation / atr.replace(0, float('nan'))
    return zscore.rename('vwap_zscore')
