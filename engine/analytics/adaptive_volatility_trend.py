"""
JARVIS TRADER — Adaptive Volatility Trend (AVT)
===============================================
Port of the "Adaptive Volatility Trend [WillyAlgoTrader]" TradingView indicator
(tradingview.com/script/CFgnJqe7), a trend filter built on Kaufman's Efficiency
Ratio rather than a fixed-period moving average: it speeds up in clean trends and
slows down in chop, with an ATR channel that narrows when efficiency is high and
widens when it drops, plus a 0-100 signal score.

This is a faithful port of the *documented* behaviour (the Pine source is
closed). It reuses the engine's existing primitives rather than reimplementing
them:

  * adaptive MA  -> ``backtest.indicators.kama`` (Kaufman Adaptive MA: the
    Efficiency Ratio blends a fast 2-EMA and slow 30-EMA smoothing constant).
  * ATR          -> ``backtest.indicators.wilder_atr``.
  * RSI          -> ``backtest.indicators.rsi``.

Components
----------
  * ``efficiency_ratio`` — net directional change over ``period`` bars divided by
    the total path travelled (sum of |Δclose|). 1.0 = a clean line, 0.0 = pure
    noise. Matches the ER convention inside ``kama``.
  * ``adaptive_atr_bands`` — channel around the adaptive MA whose half-width is
    ``ATR × multiplier × (1 - band_er_scale × ER)``: high ER contracts the band
    (tight signals in trends), low ER widens it (filters chop). ``band_er_scale``
    defaults to 0.5 so a perfectly efficient trend still leaves half the band.
  * ``signal_score`` — 0-100, summing trend strength (0-40, from ER), momentum
    (0-30, RSI distance from 50 in the signal direction) and volume confirmation
    (0-30, volume vs its 20-bar average).
  * gates — RSI gate blocks longs when RSI > 70 / shorts when RSI < 30; volume
    gate requires volume > SMA(20) × 1.2.
  * presets — Conservative / Default / Aggressive / Scalping length+ATR+multiplier
    sets.

No look-ahead (point-in-time discipline)
----------------------------------------
Every series uses only backward windows and ``shift(1)`` cross detection; a
signal at bar ``t`` is confirmed on that bar's close and reads only bars ``<= t``
(non-repainting), matching ``.claude/rules/testing.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from backtest.indicators import kama, rsi, wilder_atr

logger = logging.getLogger(__name__)

# Score component caps (sum to 100).
_TREND_MAX = 40.0
_MOMENTUM_MAX = 30.0
_VOLUME_MAX = 30.0

# Default gate thresholds (from the indicator's documented defaults).
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
VOLUME_GATE_MULT = 1.2
VOLUME_SMA_PERIOD = 20

# Volume that doubles its 20-bar average earns full volume points.
_VOLUME_FULL_RATIO = 2.0
# A perfectly efficient trend still leaves half the ATR band in place.
_DEFAULT_BAND_ER_SCALE = 0.5


@dataclass(frozen=True)
class AVTPreset:
    """A length/ATR/multiplier triple for one trading style."""

    trend_length: int
    atr_length: int
    multiplier: float


# Documented presets (trend length, ATR length, ATR multiplier).
PRESETS: dict[str, AVTPreset] = {
    "conservative": AVTPreset(trend_length=30, atr_length=20, multiplier=2.5),
    "default": AVTPreset(trend_length=20, atr_length=14, multiplier=2.0),
    "aggressive": AVTPreset(trend_length=12, atr_length=10, multiplier=1.5),
    "scalping": AVTPreset(trend_length=8, atr_length=7, multiplier=1.2),
}


def get_preset(name: str) -> AVTPreset:
    """Look up a preset by case-insensitive name; raises on unknown name."""
    key = name.strip().lower()
    if key not in PRESETS:
        raise ValueError(f"Unknown preset '{name}'. Valid: {sorted(PRESETS)}")
    return PRESETS[key]


# ---------------------------------------------------------------------------
# Core indicator series
# ---------------------------------------------------------------------------


def efficiency_ratio(close: pd.Series, period: int = 20) -> pd.Series:
    """Kaufman Efficiency Ratio over ``period`` bars, in ``[0, 1]``.

    ``|close - close[t-period]| / Σ|Δclose|`` over the trailing ``period`` bars.
    A flat or noisy path -> 0; a clean directional move -> 1. Bars without enough
    history are NaN. Matches the ER used inside :func:`backtest.indicators.kama`.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    change = close.diff(period).abs()
    volatility = close.diff().abs().rolling(period).sum()
    er = change / volatility.replace(0, np.nan)
    # Zero path travelled (perfectly flat) means no inefficiency -> ER 0, not NaN.
    er = er.where(volatility != 0, 0.0)
    return er.clip(0.0, 1.0)


def adaptive_trend(close: pd.Series, period: int = 20) -> pd.Series:
    """Adaptive moving average (Kaufman). Thin alias over ``indicators.kama``."""
    return kama(close, period=period, fast_period=2, slow_period=30)


def adaptive_atr_bands(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    basis: pd.Series,
    er: pd.Series,
    *,
    atr_period: int = 14,
    multiplier: float = 2.0,
    band_er_scale: float = _DEFAULT_BAND_ER_SCALE,
) -> tuple[pd.Series, pd.Series]:
    """Efficiency-scaled ATR channel around ``basis``.

    Half-width = ``ATR × multiplier × (1 - band_er_scale × ER)``: a high ER
    contracts the band, a low ER widens it. Returns ``(upper, lower)``.
    """
    atr = wilder_atr(high, low, close, period=atr_period)
    effective_mult = multiplier * (1.0 - band_er_scale * er.clip(0.0, 1.0))
    half_width = atr * effective_mult
    return basis + half_width, basis - half_width


# ---------------------------------------------------------------------------
# Signal score
# ---------------------------------------------------------------------------


def _trend_points(er_value: float) -> float:
    if not np.isfinite(er_value):
        return 0.0
    return float(np.clip(er_value, 0.0, 1.0)) * _TREND_MAX


def _momentum_points(rsi_value: float, direction: int) -> float:
    """RSI distance from the neutral 50 in the signal direction, scaled to 0-30."""
    if not np.isfinite(rsi_value) or direction == 0:
        return 0.0
    if direction > 0:
        edge = max(0.0, rsi_value - 50.0)
    else:
        edge = max(0.0, 50.0 - rsi_value)
    return min(1.0, edge / 50.0) * _MOMENTUM_MAX


def _volume_points(volume_ratio: float) -> float:
    """Volume vs its 20-bar average, scaled to 0-30 (2x average == full marks)."""
    if not np.isfinite(volume_ratio) or volume_ratio <= 0:
        return 0.0
    return min(1.0, volume_ratio / _VOLUME_FULL_RATIO) * _VOLUME_MAX


def signal_score(er_value: float, rsi_value: float, volume_ratio: float, direction: int) -> float:
    """Composite 0-100 score: trend (0-40) + momentum (0-30) + volume (0-30).

    ``direction`` is +1 for a long signal, -1 for a short, 0 for none (score 0).
    """
    if direction == 0:
        return 0.0
    return (
        _trend_points(er_value)
        + _momentum_points(rsi_value, direction)
        + _volume_points(volume_ratio)
    )


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


@dataclass
class AVTParams:
    """Resolved AVT configuration."""

    trend_length: int = 20
    atr_length: int = 14
    multiplier: float = 2.0
    band_er_scale: float = _DEFAULT_BAND_ER_SCALE
    min_score: float = 0.0
    use_rsi_gate: bool = True
    use_volume_gate: bool = True
    rsi_period: int = 14

    @classmethod
    def from_preset(cls, name: str, **overrides) -> "AVTParams":
        p = get_preset(name)
        base = {"trend_length": p.trend_length, "atr_length": p.atr_length,
                "multiplier": p.multiplier}
        base.update(overrides)
        return cls(**base)


_REQUIRED_COLUMNS = ("high", "low", "close", "volume")


def generate_avt_signals(df: pd.DataFrame, params: Optional[AVTParams] = None) -> pd.DataFrame:
    """Compute the Adaptive Volatility Trend series and gated signals.

    The trend direction is an adaptive-MA cross (close crossing above the
    adaptive MA -> long, below -> short), confirmed on bar close — the same
    non-repainting convention as ``backtest.studies.kama_signals``. Each raw
    cross is then scored and filtered by the RSI gate, the volume gate, and the
    minimum-score threshold.

    Returns a copy of ``df`` with added columns: ``avt_trend`` (adaptive MA),
    ``avt_er``, ``avt_upper``, ``avt_lower``, ``avt_rsi``, ``avt_vol_ratio``,
    ``avt_raw_signal`` (-1/0/1 cross before gating), ``avt_score`` and
    ``avt_signal`` (-1/0/1 after gating). Only bars ``<= t`` inform bar ``t``.
    """
    params = params or AVTParams()
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"generate_avt_signals: frame missing columns {missing}")

    work = df.copy()
    close, high, low, volume = work["close"], work["high"], work["low"], work["volume"]

    basis = adaptive_trend(close, period=params.trend_length)
    er = efficiency_ratio(close, period=params.trend_length)
    upper, lower = adaptive_atr_bands(
        high, low, close, basis, er,
        atr_period=params.atr_length,
        multiplier=params.multiplier,
        band_er_scale=params.band_er_scale,
    )
    rsi_series = rsi(close, period=params.rsi_period)
    vol_sma = volume.rolling(VOLUME_SMA_PERIOD).mean()
    vol_ratio = (volume / vol_sma.replace(0, np.nan))

    above = close > basis
    raw = pd.Series(0, index=work.index, dtype=int)
    raw[above & ~above.shift(1).fillna(above).astype(bool)] = 1
    raw[~above & above.shift(1).fillna(~above).astype(bool)] = -1

    scores = np.zeros(len(work), dtype=float)
    signals = np.zeros(len(work), dtype=int)
    er_v, rsi_v, vr_v = er.to_numpy(), rsi_series.to_numpy(), vol_ratio.to_numpy()
    raw_v = raw.to_numpy()
    for i in range(len(work)):
        direction = int(raw_v[i])
        if direction == 0:
            continue
        if params.use_rsi_gate and np.isfinite(rsi_v[i]):
            if direction > 0 and rsi_v[i] > RSI_OVERBOUGHT:
                continue
            if direction < 0 and rsi_v[i] < RSI_OVERSOLD:
                continue
        if params.use_volume_gate:
            ratio = vr_v[i]
            if not np.isfinite(ratio) or ratio < VOLUME_GATE_MULT:
                continue
        score = signal_score(er_v[i], rsi_v[i], vr_v[i], direction)
        scores[i] = score
        if score >= params.min_score:
            signals[i] = direction

    work["avt_trend"] = basis
    work["avt_er"] = er
    work["avt_upper"] = upper
    work["avt_lower"] = lower
    work["avt_rsi"] = rsi_series
    work["avt_vol_ratio"] = vol_ratio
    work["avt_raw_signal"] = raw
    work["avt_score"] = scores
    work["avt_signal"] = signals
    return work
