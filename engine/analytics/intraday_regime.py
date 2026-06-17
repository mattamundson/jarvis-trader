"""Intraday market-regime scoring.

Pure-Python (pandas/numpy) composite regime scorer that powers the dashboard's
Intraday Market Regime view (GET /regime/intraday). No LLM is involved — every
number here is a deterministic function of OHLCV bars, so it is fully unit
testable and safe to compute on every request.

The composite score is a weighted blend of normalized sub-signals (EMA ribbon,
VWAP, RSI, MACD histogram, rate-of-change) expressed on a -100..+100 scale where
negative is bearish and positive is bullish.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from backtest.indicators import (
    compute_adx,
    compute_roc,
    compute_vwap,
    ema_ribbon,
    rsi,
    wilder_atr,
)

# Timeframe blend weights for the headline composite score. Heavier weight on the
# higher timeframe so the headline reflects the dominant trend, not 5m noise.
TIMEFRAME_WEIGHTS: dict[str, float] = {"5m": 0.2, "15m": 0.3, "1h": 0.5}

# Sub-signal weights for a single timeframe's composite score (sum to 1.0).
_SIGNAL_WEIGHTS = {"ema": 0.30, "vwap": 0.20, "rsi": 0.20, "macd": 0.15, "roc": 0.15}

# Headline direction thresholds on the -100..+100 scale.
_BULL_THRESHOLD = 25.0
_BEAR_THRESHOLD = -25.0
# Per-timeframe bias uses a gentler band so a weak-but-clear lean still reads.
_TF_BULL = 10.0
_TF_BEAR = -10.0

_HISTORY_MAX_POINTS = 350


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _last_finite(series: pd.Series, default: float = 0.0) -> float:
    """Last finite value of a series, or `default` if none."""
    s = series.dropna()
    if s.empty:
        return default
    val = float(s.iloc[-1])
    return val if math.isfinite(val) else default


def score_series(df: pd.DataFrame) -> pd.Series:
    """Per-bar composite regime score in [-100, 100] for one timeframe.

    Each sub-signal is normalized to [-1, 1]; the weighted sum is scaled to ±100.
    """
    close = df["close"]
    ema_8, ema_21, ema_34 = ema_ribbon(close)
    vwap = compute_vwap(df)
    rsi_s = rsi(close)
    roc_s = compute_roc(close, period=14)

    # MACD histogram, bounded by rolling price dispersion so magnitude is scaled.
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    disp = close.rolling(20).std().replace(0, np.nan)

    s_ema = (np.sign(close - ema_8) + np.sign(close - ema_21) + np.sign(close - ema_34)) / 3.0
    s_vwap = np.sign(close - vwap)
    s_rsi = ((rsi_s - 50.0) / 50.0).clip(-1, 1)
    s_macd = np.tanh(hist / disp).fillna(0.0)
    s_roc = (roc_s / 1.0).clip(-1, 1)

    blended = (
        _SIGNAL_WEIGHTS["ema"] * s_ema
        + _SIGNAL_WEIGHTS["vwap"] * s_vwap
        + _SIGNAL_WEIGHTS["rsi"] * s_rsi
        + _SIGNAL_WEIGHTS["macd"] * s_macd
        + _SIGNAL_WEIGHTS["roc"] * s_roc
    )
    return (blended * 100.0).clip(-100, 100).fillna(0.0)


def timeframe_score(df: pd.DataFrame) -> float:
    """Latest composite score for a timeframe, rounded to 2 decimals."""
    if df is None or df.empty:
        return 0.0
    return round(_last_finite(score_series(df)), 2)


def bias_from_score(score: float, bull: float = _TF_BULL, bear: float = _TF_BEAR) -> str:
    if score >= bull:
        return "BULL"
    if score <= bear:
        return "BEAR"
    return "NEUTRAL"


def direction_from_score(score: float) -> str:
    if score >= _BULL_THRESHOLD:
        return "BULLISH"
    if score <= _BEAR_THRESHOLD:
        return "BEARISH"
    return "NEUTRAL"


def _tone(value: float, bull_when_positive: bool = True) -> str:
    if abs(value) < 1e-9:
        return "neutral"
    positive = value > 0
    if not bull_when_positive:
        positive = not positive
    return "bull" if positive else "bear"


def build_indicators(df: pd.DataFrame) -> list[dict]:
    """Ten indicator-card readings from a single (1h) timeframe DataFrame."""
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    price = float(close.iloc[-1])

    ema_8, ema_21, ema_34 = ema_ribbon(close)
    vwap = _last_finite(compute_vwap(df), price)
    above_count = int((price > ema_8.iloc[-1]) + (price > ema_21.iloc[-1]) + (price > ema_34.iloc[-1]))

    hh, ll = high.rolling(20).max(), low.rolling(20).min()
    don_pos = _clamp(float((price - ll.iloc[-1]) / max(hh.iloc[-1] - ll.iloc[-1], 1e-9)), 0, 1)

    adx_df = compute_adx(df)
    adx_val = _last_finite(adx_df["adx"])
    plus_di, minus_di = _last_finite(adx_df["plus_di"]), _last_finite(adx_df["minus_di"])
    trending = adx_val >= 25.0

    obv = (np.sign(close.diff()).fillna(0) * volume).cumsum()
    obv_slope = _last_finite(obv - obv.shift(5))

    rsi_val = _last_finite(rsi(close), 50.0)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist_val = _last_finite(macd - macd.ewm(span=9, adjust=False).mean())
    roc_val = _last_finite(compute_roc(close, period=14))

    atr = wilder_atr(high, low, close)
    atr_ratio = _last_finite(atr / atr.rolling(20).mean().replace(0, np.nan), 1.0)

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_pctb = _clamp(
        float((price - (bb_mid.iloc[-1] - 2 * bb_std.iloc[-1]))
              / max(4 * bb_std.iloc[-1], 1e-9)), 0, 1
    )

    return [
        {"label": "VWAP", "value": "Above" if price >= vwap else "Below",
         "detail": f"${vwap:,.2f}", "tone": _tone(price - vwap),
         "arrow": "up" if price >= vwap else "down", "fill": _clamp(0.5 + (price / vwap - 1) * 20, 0, 1)},
        {"label": "DONCHIAN", "value": f"{don_pos * 100:.0f}% of range",
         "detail": "20-bar channel", "tone": "bull" if don_pos >= 0.5 else "bear", "fill": don_pos},
        {"label": "EMA STACK", "value": f"{above_count}/3 above", "detail": "8-21-34",
         "tone": "bull" if above_count >= 2 else "bear", "fill": above_count / 3.0},
        {"label": "STRUCTURE", "value": "Trending" if trending else "Ranging",
         "detail": f"ADX {adx_val:.0f}",
         "tone": ("bull" if plus_di >= minus_di else "bear") if trending else "neutral",
         "fill": _clamp(adx_val / 50.0, 0, 1)},
        {"label": "OBV", "value": "Rising" if obv_slope >= 0 else "Falling", "detail": "5-bar trend",
         "tone": _tone(obv_slope), "arrow": "up" if obv_slope >= 0 else "down",
         "fill": _clamp(0.5 + math.tanh(obv_slope / max(abs(obv_slope) + 1, 1)) / 2, 0, 1)},
        {"label": "RSI", "value": f"RSI {rsi_val:.0f}",
         "detail": "Overbought" if rsi_val > 70 else "Oversold" if rsi_val < 30 else "Neutral zone",
         "tone": "bull" if rsi_val > 55 else "bear" if rsi_val < 45 else "neutral", "fill": rsi_val / 100.0},
        {"label": "MACD HIST", "value": f"{hist_val:.4f}", "detail": "12-26-9",
         "tone": _tone(hist_val), "fill": _clamp(0.5 + math.tanh(hist_val) / 2, 0, 1)},
        {"label": "RATE OF CHG", "value": f"{roc_val:.2f}%", "detail": "14-bar ROC",
         "tone": _tone(roc_val), "fill": _clamp(0.5 + roc_val / 4.0, 0, 1)},
        {"label": "ATR REGIME", "value": "Expanding" if atr_ratio > 1 else "Contracting",
         "detail": f"Ratio {atr_ratio:.2f}", "tone": "neutral", "fill": _clamp(atr_ratio / 2.0, 0, 1)},
        {"label": "BB POSITION", "value": f"{bb_pctb * 100:.0f}% in band", "detail": "20-2.0 band",
         "tone": "bull" if bb_pctb >= 0.5 else "bear", "fill": bb_pctb},
    ]


def build_history(df: pd.DataFrame, max_points: int = _HISTORY_MAX_POINTS) -> list[dict]:
    """Score history with short/long/extra EMA overlays from the finest timeframe."""
    if df is None or df.empty:
        return []
    scores = score_series(df).tail(max_points)
    short = scores.ewm(span=12, adjust=False).mean()
    long = scores.ewm(span=26, adjust=False).mean()
    extra = scores.ewm(span=50, adjust=False).mean()

    history: list[dict] = []
    for ts, score in scores.items():
        label = ts.strftime("%I:%M %p") if isinstance(ts, (pd.Timestamp, datetime)) else str(ts)
        history.append({
            "time": label,
            "score": round(float(score), 2),
            "short_ema": round(float(short.loc[ts]), 2),
            "long_ema": round(float(long.loc[ts]), 2),
            "extra_ema": round(float(extra.loc[ts]), 2),
        })
    return history


def build_regime_snapshot(
    symbol: str,
    bars_by_tf: dict[str, pd.DataFrame],
    options_flow: Optional[dict] = None,
) -> dict:
    """Assemble the full intraday-regime payload from per-timeframe bar frames.

    `bars_by_tf` maps timeframe label ("5m"/"15m"/"1h") to its OHLCV DataFrame
    (DatetimeIndex; columns open/high/low/close/volume). `options_flow` is an
    optional dealer-GEX reading (kept as a param so this function stays pure and
    deterministic — the router fetches it and passes it through).
    """
    tf_scores = []
    for label, key in (("5-MINUTE", "5m"), ("15-MINUTE", "15m"), ("1-HOUR", "1h")):
        df = bars_by_tf.get(key)
        sc = timeframe_score(df) if df is not None and not df.empty else 0.0
        tf_scores.append({"label": label, "score": sc, "bias": bias_from_score(sc)})

    score = round(
        sum(TIMEFRAME_WEIGHTS[k] * timeframe_score(bars_by_tf.get(k))
            for k in TIMEFRAME_WEIGHTS if bars_by_tf.get(k) is not None and not bars_by_tf[k].empty),
        2,
    )
    direction = direction_from_score(score)

    primary = bars_by_tf.get("1h")
    indicators = build_indicators(primary) if primary is not None and not primary.empty else []
    tone_target = {"BULLISH": "bull", "BEARISH": "bear", "NEUTRAL": "neutral"}[direction]
    matching = sum(1 for ind in indicators if ind["tone"] == tone_target)
    direction_pct = round(100.0 * matching / len(indicators), 1) if indicators else 0.0

    finest = None
    for key in ("5m", "15m", "1h"):
        candidate = bars_by_tf.get(key)
        if candidate is not None and not candidate.empty:
            finest = candidate
            break
    history = build_history(finest) if finest is not None else []

    price = float(primary["close"].iloc[-1]) if primary is not None and not primary.empty else 0.0
    guidance = {
        "BULLISH": "Look for LONG entries",
        "BEARISH": "Look for SHORT entries",
        "NEUTRAL": "Wait for confirmation",
    }[direction]
    conviction = "HIGH" if abs(score) >= 50 else "MEDIUM" if abs(score) >= 25 else "LOW"

    return {
        "symbol": symbol.upper(),
        "price": round(price, 2),
        "score": score,
        "direction": direction,
        "direction_pct": direction_pct,
        "guidance": guidance,
        "conviction": conviction,
        "indicator_timeframe": "1-HOUR",
        "timeframe_scores": tf_scores,
        "indicators": indicators,
        "history": history,
        "snapshot_count": len(history),
        # Dealer-GEX reading when an options source is wired; None (not faked)
        # otherwise — the dashboard renders a "Not wired" state for null.
        "options_flow": options_flow,
        "data_quality": "live",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def latest_price(bars_by_tf: dict[str, pd.DataFrame]) -> Optional[float]:
    for key in ("1h", "15m", "5m"):
        df = bars_by_tf.get(key)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    return None
