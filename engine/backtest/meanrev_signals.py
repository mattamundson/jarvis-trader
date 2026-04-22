"""
Bollinger-Band + RSI mean-reversion signal generator for JARVIS TRADER.

Designed for MCL (crude oil 1h) — per-symbol decision memo (commit `c4a1ef1`)
flagged MCL as a mean-reversion candidate rather than trend-following. MCL is
currently blocklisted via `DO_NOT_TRADE_SYMBOLS` pending a validated edge; this
module is the first step in that re-derivation (roadmap P1.1).

Thesis
------
Crude oil tends to mean-revert after short-horizon dislocations:
    * Price closing OUTSIDE a Bollinger band (20-SMA ± 2σ) is an extreme event.
    * RSI(14) at <30 (oversold) or >70 (overbought) confirms momentum exhaustion.
    * Target: reversion to the 20-SMA midband.
    * Stop:   ATR-based buffer below/above the entry bar extreme.

Symmetric (LONG + SHORT) — unlike the trend-following SMA module which is
LONG-only by design.

Entry (LONG)
------------
    * close < lower_band   AND   rsi < rsi_long_threshold  (default 30)

Entry (SHORT)
-------------
    * close > upper_band   AND   rsi > rsi_short_threshold (default 70)

Exit
----
    * Price crosses midband (primary — "reversion complete")   → exit_signal=EXIT_NOW
    * Stop hit                                                 → handled by backtester
    * RSI returns to 50 (optional momentum-reset exit; not enforced here)

Output format
-------------
Matches the column contract consumed by the backtester:
    entry_signal  : "ENTRY_NOW" | "NO_TRADE"
    exit_signal   : "EXIT_NOW"  | "NO_EXIT"
    bias          : "STRONG_BULL" (long setup) | "STRONG_BEAR" (short setup) | "NEUTRAL"
    regime        : "MEAN_REVERTING" | "TRENDING" | "NEUTRAL"
    stop_level    : float — entry ± stop_atr_mult × ATR(14)
    target_1      : float — midband (primary reversion target)
    target_2      : float — midband ± 0.5 × band_width (extended)
    target_3      : float — opposite band (max reversion)
    bb_upper / bb_mid / bb_lower : raw Bollinger levels
    rsi_14 / atr_14              : momentum + volatility context
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Default MCL-targeted params — refined via backtest in P1.1
MEANREV_PARAMS: dict[str, dict] = {
    "MCL": {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_long": 30.0,
        "rsi_short": 70.0,
        "stop_atr_mult": 1.5,
    },
}

_ATR_PERIOD = 14


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI with exponential smoothing (alpha = 1/period)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing via EWMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # "No losses in window" → RSI = 100 (definitional).
    # Warmup bars (avg_loss NaN) must stay NaN so downstream warm-guards skip them.
    no_losses = (avg_loss == 0.0)
    rsi = rsi.mask(no_losses, 100.0)
    return rsi


def generate_bollinger_rsi_signals(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_long: float = 30.0,
    rsi_short: float = 70.0,
    stop_atr_mult: float = 1.5,
) -> pd.DataFrame:
    """Generate Bollinger + RSI mean-reversion signals.

    Args:
        df: OHLCV DataFrame with columns open, high, low, close, volume.
        bb_period: Bollinger lookback window (default 20).
        bb_std: Standard-deviation multiplier for bands (default 2.0).
        rsi_period: Wilder RSI period (default 14).
        rsi_long: Oversold threshold for LONG entries (default 30.0).
        rsi_short: Overbought threshold for SHORT entries (default 70.0).
        stop_atr_mult: Stop distance in ATR(14) multiples (default 1.5).

    Returns:
        Copy of df with added columns documented in the module docstring.
    """
    df = df.copy()

    # ── Core indicators ──────────────────────────────────────────────────
    sma = df["close"].rolling(bb_period).mean()
    sd = df["close"].rolling(bb_period).std(ddof=0)
    bb_upper = sma + bb_std * sd
    bb_lower = sma - bb_std * sd

    rsi = _wilder_rsi(df["close"], period=rsi_period)
    atr = _wilder_atr(df["high"], df["low"], df["close"], period=_ATR_PERIOD)

    # ── Entry logic ──────────────────────────────────────────────────────
    close = df["close"]

    long_cond = (close < bb_lower) & (rsi < rsi_long)
    short_cond = (close > bb_upper) & (rsi > rsi_short)
    # Require indicators to be warmed up (no NaN in any input)
    warm = sma.notna() & rsi.notna() & atr.notna()
    long_cond = long_cond & warm
    short_cond = short_cond & warm

    # Direction precedence: if somehow both fire (edge case, extreme vol), skip.
    conflict = long_cond & short_cond
    long_cond = long_cond & ~conflict
    short_cond = short_cond & ~conflict

    # ── Exit logic: midband cross ─────────────────────────────────────────
    # Midband cross in either direction — simple reversion-complete signal.
    # The backtester handles per-trade direction-aware exit mechanics; this
    # column flags "a reversion back to fair value has occurred this bar."
    prev_close = close.shift(1)
    prev_sma = sma.shift(1)
    crossed_up_through_mid = (prev_close < prev_sma) & (close >= sma)
    crossed_down_through_mid = (prev_close > prev_sma) & (close <= sma)
    exit_cond = (crossed_up_through_mid | crossed_down_through_mid) & warm

    # ── Target ladder ────────────────────────────────────────────────────
    # LONG target_1 = midband (primary reversion); target_2/3 extend toward
    # and through the upper band. SHORT is mirrored.
    band_width = (bb_upper - bb_lower) / 2.0  # half-width = 1σ
    # Avoid invalid targets on warmup bars
    target_mid = sma

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    long_idx = np.flatnonzero(long_cond.values)
    for i in long_idx:
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BULL"
        stop_level[i] = price - stop_atr_mult * atr_i
        target_1[i] = float(target_mid.iloc[i])
        target_2[i] = float(target_mid.iloc[i]) + 0.5 * float(band_width.iloc[i])
        target_3[i] = float(bb_upper.iloc[i])

    short_idx = np.flatnonzero(short_cond.values)
    for i in short_idx:
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BEAR"
        stop_level[i] = price + stop_atr_mult * atr_i
        target_1[i] = float(target_mid.iloc[i])
        target_2[i] = float(target_mid.iloc[i]) - 0.5 * float(band_width.iloc[i])
        target_3[i] = float(bb_lower.iloc[i])

    exit_idx = np.flatnonzero(exit_cond.values)
    for i in exit_idx:
        exit_signal[i] = "EXIT_NOW"

    # ── Regime label ─────────────────────────────────────────────────────
    # A crude regime hint for downstream consumers. The full regime router
    # lives in regime_classifier.py (P1.3) and should replace this once built.
    regime = np.where(warm, "MEAN_REVERTING", "NEUTRAL")

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["bias"] = bias
    df["regime"] = regime
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["bb_upper"] = bb_upper
    df["bb_mid"] = sma
    df["bb_lower"] = bb_lower
    df["rsi_14"] = rsi
    df["atr_14"] = atr

    return df


def get_meanrev_params(symbol: str) -> dict | None:
    """Return validated mean-reversion params for symbol, or None."""
    return MEANREV_PARAMS.get(symbol.upper())
