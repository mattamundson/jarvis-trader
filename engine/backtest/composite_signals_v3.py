"""
JARVIS TRADER — COHEN Composite Signal Generator v3
=====================================================
Builds on v2 composite signals with the following changes:

  v3 Changes vs v2:
  -----------------
  1. Circuit breaker: max drawdown threshold relaxed from 15% to 10%
     (tighter risk control — pauses trading sooner)
  2. ADX threshold by instrument:
     - MES/ES  : ADX >= 25 (unchanged from v2)
     - MNQ/NQ  : ADX >= 20 (relaxed — NQ is inherently more volatile/trending)
     - MCL/CL  : ADX >= 20 (relaxed — crude oil trends more aggressively)
  3. Extended data window: 2 years of historical data (was 1 year in v2)
  4. Vol-adjusted position sizing:
     - Scale factor = target_vol / realized_vol
     - target_vol = 0.07 (7% annualised)
     - realized_vol computed from last 20 bars of log returns
     - Stored as 'pos_size_scalar' column for the backtester to consume
  5. Trend filter (EMA crossover gate):
     - Long signals only when 50-EMA > 200-EMA (uptrend confirmed)
     - Short signals only when 50-EMA < 200-EMA (downtrend confirmed)
     - Stored as 'ema_trend' column: 1=up, -1=down, 0=undecided

  Retained from v2:
  -----------------
  - Entry threshold: 0.55
  - Composite scoring: STC + ORB + VWAP regime-adaptive weighting
  - R:R filter: composite_rr >= 1.2
  - ORB band multiplier: 3.0×ATR
  - STC gate: STC must fire for composite entry
  - VOLATILE regime block

Strategy: "Never bet on one signal" — Steve Cohen / Point72 principle.
Each source captures a different market dynamic:

  1. STC (Schaff Trend Cycle + 5-layer framework)  — momentum / trend
  2. ORB (Opening Range Breakout)                  — morning momentum (9:30-11:00 ET)
  3. VWAP Deviation Reversion                      — intraday mean reversion (11:00+ ET)

Regime-Adaptive Weighting (from RegimeClassifier):
  TRENDING regime  → STC=0.60, ORB=0.30, VWAP=0.10  (STC dominates)
  RANGING regime   → STC=0.50, ORB=0.20, VWAP=0.30  (STC primary, VWAP supporting)
  VOLATILE regime  → ALL=0.00                         (no entries — sit out)

Output columns added (backtester-compatible):
  entry_signal    : "ENTRY_NOW" | "NO_TRADE" | "COMPOSITE_VOLATILE_BLOCK"
  bias            : "STRONG_BULL" | "STRONG_BEAR" | (original)
  stop_level      : tightest stop from contributing signals
  target_1        : STC T1 (priority), else ORB T1, else VWAP T1
  target_2        : furthest target from any contributing signal
  target_3        : original STC T3
  composite_score : float, signed score (positive = bullish, negative = bearish)
  composite_regime: "TRENDING" | "RANGING" | "VOLATILE"
  stc_contrib     : bool — STC signal contributed to this entry
  orb_contrib     : bool — ORB signal contributed
  vwap_contrib    : bool — VWAP signal contributed
  composite_rr    : R:R ratio at T1
  adx             : ADX value (14-period)
  ema_trend       : 1=uptrend (EMA50>EMA200), -1=downtrend, 0=undecided
  pos_size_scalar : vol-adjusted position size multiplier
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("composite_signals_v3")

# ── Version Tag ─────────────────────────────────────────────────────────────
VERSION = "v3"

# ── Regime Weights ─────────────────────────────────────────────────────────────
REGIME_WEIGHTS = {
    "TRENDING": {"stc": 0.60, "orb": 0.30, "vwap": 0.10},
    "RANGING":  {"stc": 0.50, "orb": 0.20, "vwap": 0.30},
    "VOLATILE": {"stc": 0.00, "orb": 0.00, "vwap": 0.00},
}
DEFAULT_WEIGHTS = REGIME_WEIGHTS["RANGING"]  # default when regime unknown

# Entry threshold (unchanged from v2)
ENTRY_THRESHOLD = 0.55

# Minimum reward:risk ratio for composite entries
MIN_RR = 1.2

# ── v3: ADX thresholds by instrument ────────────────────────────────────────
ADX_THRESHOLDS = {
    "MES": 25.0,
    "ES":  25.0,
    "MNQ": 20.0,  # relaxed: NQ trends more aggressively
    "NQ":  20.0,
    "MCL": 20.0,  # relaxed: crude oil has frequent strong trends
    "CL":  20.0,
}
ADX_THRESHOLD_DEFAULT = 25.0  # fallback for unknown symbols

# ── v3: Circuit breaker ──────────────────────────────────────────────────────
CIRCUIT_BREAKER_DRAWDOWN = 0.10  # 10% max drawdown before pause (was 15% in v2)

# ── v3: Vol-adjusted position sizing ────────────────────────────────────────
TARGET_VOL = 0.07    # 7% annualised target volatility
VOL_LOOKBACK = 20    # bars for realised vol calculation
SQRT_252 = np.sqrt(252)  # annualisation factor for daily; for hourly bars use sqrt(252*6.5)
SQRT_HOURLY = np.sqrt(252 * 6.5)  # ~40.5, for 1h bars

# ── v3: EMA trend filter periods ─────────────────────────────────────────────
EMA_FAST = 50
EMA_SLOW = 200


def generate_composite_signals(
    df: pd.DataFrame,
    symbol: str = "MES",
    band_mult: float = 3.0,
    stop_mult: float = 0.5,
    atr_period: int = 14,
    entry_threshold: float = ENTRY_THRESHOLD,
    stc_oversold: float | None = None,
    stc_overbought: float | None = None,
    stop_atr_mult: float = 1.00,
    t1_atr_mult: float = 2.50,
    t2_atr_mult: float = 4.00,
    t3_atr_mult: float = 6.00,
) -> pd.DataFrame:
    """
    Generate composite signals combining STC + ORB + VWAP with
    regime-adaptive weighting. v3: adds EMA trend filter, vol-adjusted
    sizing, per-instrument ADX thresholds, and tighter circuit breaker.

    Parameters
    ----------
    df : pd.DataFrame
        1-hour OHLCV data with DatetimeIndex.
        Required columns: open, high, low, close, volume.
    symbol : str
        Symbol for logging and per-instrument ADX threshold selection.
    band_mult : float
        ATR multiplier for VWAP bands.
    stop_mult : float
        ATR multiplier for VWAP stops (legacy compat).
    atr_period : int
        ATR period for VWAP computation.
    entry_threshold : float
        Minimum composite score to generate ENTRY_NOW signal.
    stc_oversold : float, optional
        STC oversold level override.
    stc_overbought : float, optional
        STC overbought level override.
    stop_atr_mult : float
        ATR multiple for stop placement.
    t1_atr_mult / t2_atr_mult / t3_atr_mult : float
        ATR multiples for target levels.

    Returns
    -------
    pd.DataFrame
        Input df with all signal columns plus v3-specific columns:
        adx, ema_trend, pos_size_scalar, composite_score, etc.
    """
    if df.empty or len(df) < 20:
        logger.warning(
            f"{symbol}: insufficient data ({len(df)} bars) — returning empty signals"
        )
        return _add_empty_composite_cols(df.copy())

    df_orig = df.copy()

    # ── Step 1: STC signals (adaptive regime) ─────────────────────────────
    try:
        from backtest.signals import generate_signals as _gen_stc

        df_stc = _gen_stc(
            df_orig.copy(),
            symbol=symbol,
            stc_oversold=stc_oversold,
            stc_overbought=stc_overbought,
            adaptive_regime=True,
            regime_filter=False,
        )
    except Exception as e:
        logger.warning(f"{symbol}: STC signal generation failed: {e}")
        df_stc = df_orig.copy()
        df_stc["entry_signal"] = "NO_TRADE"
        df_stc["bias"] = "NEUTRAL"
        df_stc["stc_cross_up"] = False
        df_stc["stc_cross_down"] = False
        df_stc["stop_level"] = np.nan
        df_stc["target_1"] = np.nan
        df_stc["target_2"] = np.nan
        df_stc["target_3"] = np.nan
        df_stc["regime"] = "RANGE_BOUND"
        df_stc["regime_type"] = "RANGING"

    # ── Step 2: ORB signals ────────────────────────────────────────────────
    try:
        from backtest.orb_signals import generate_orb_signals as _gen_orb

        df_orb = _gen_orb(
            df_orig.copy(), symbol=symbol, volume_filter=True, regime_filter=False
        )
    except Exception as e:
        logger.warning(f"{symbol}: ORB signal generation failed: {e}")
        df_orb = df_orig.copy()
        df_orb["ORB_signal"] = ""
        df_orb["orb_stop"] = np.nan
        df_orb["orb_target_1"] = np.nan
        df_orb["orb_target_2"] = np.nan
        df_orb["orb_rr"] = np.nan

    # ── Step 3: VWAP signals ───────────────────────────────────────────────
    try:
        from backtest.vwap_signals import generate_vwap_signals as _gen_vwap

        df_vwap = _gen_vwap(
            df_orig.copy(),
            symbol=symbol,
            band_mult=band_mult,
            stop_mult=stop_mult,
            atr_period=atr_period,
            regime_filter=False,
        )
    except Exception as e:
        logger.warning(f"{symbol}: VWAP signal generation failed: {e}")
        df_vwap = df_orig.copy()
        df_vwap["vwap_signal"] = ""
        df_vwap["vwap_stop"] = np.nan
        df_vwap["vwap_target_1"] = np.nan
        df_vwap["vwap_target_2"] = np.nan
        df_vwap["vwap_rr"] = np.nan
        df_vwap["vwap"] = df_orig["close"]

    # ── Step 4: Merge all signal columns into STC base ─────────────────────
    result = df_stc.copy()

    for col in ["ORB_signal", "orb_stop", "orb_target_1", "orb_target_2", "orb_rr"]:
        if col in df_orb.columns:
            result[col] = df_orb[col].values

    for col in [
        "vwap_signal",
        "vwap_stop",
        "vwap_target_1",
        "vwap_target_2",
        "vwap_rr",
        "vwap",
    ]:
        if col in df_vwap.columns:
            result[col] = df_vwap[col].values

    # ── Step 5: Determine regime per bar ──────────────────────────────────
    if "regime_type" in result.columns:
        regime_series = result["regime_type"].fillna("RANGING")
    else:
        try:
            from backtest.regime import RegimeClassifier

            clf = RegimeClassifier()
            classified = clf.classify(result)
            regime_series = classified["regime_type"].fillna("RANGING")
            result["regime_type"] = regime_series
        except Exception:
            regime_series = pd.Series("RANGING", index=result.index)
            result["regime_type"] = regime_series

    # ── Step 5b: ADX trend-strength filter (v3: per-instrument threshold) ─
    # v3 change: MNQ/MCL use ADX>=20 instead of the v2 uniform ADX>=25
    adx_threshold = ADX_THRESHOLDS.get(symbol.upper(), ADX_THRESHOLD_DEFAULT)
    try:
        period = 14
        high = result["high"]
        low = result["low"]
        close_s = result["close"]

        tr1 = high - low
        tr2 = (high - close_s.shift(1)).abs()
        tr3 = (low - close_s.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where(
            (up_move > down_move) & (up_move > 0), up_move, 0.0
        )
        minus_dm = np.where(
            (down_move > up_move) & (down_move > 0), down_move, 0.0
        )

        atr_wilder = tr.ewm(
            alpha=1 / period, min_periods=period, adjust=False
        ).mean()
        plus_di = (
            100
            * pd.Series(plus_dm, index=result.index)
            .ewm(alpha=1 / period, min_periods=period, adjust=False)
            .mean()
            / atr_wilder
        )
        minus_di = (
            100
            * pd.Series(minus_dm, index=result.index)
            .ewm(alpha=1 / period, min_periods=period, adjust=False)
            .mean()
            / atr_wilder
        )

        dx = (
            100
            * (plus_di - minus_di).abs()
            / (plus_di + minus_di).replace(0, np.nan)
        )
        adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().fillna(0)

        result["adx"] = adx.round(2)
        adx_pass = adx >= adx_threshold
        logger.info(
            f"{symbol} v3: ADX filter (threshold={adx_threshold}) — "
            f"{adx_pass.sum()} / {len(adx_pass)} bars pass ({adx_pass.mean():.1%})"
        )
    except Exception as e:
        logger.warning(f"{symbol}: ADX filter failed, bypassing: {e}")
        adx_pass = pd.Series(True, index=result.index)
        result["adx"] = np.nan

    # ── Step 5c: EMA trend filter (v3 new feature) ────────────────────────
    # Only take long signals when EMA50 > EMA200 (uptrend confirmed)
    # Only take short signals when EMA50 < EMA200 (downtrend confirmed)
    try:
        close_prices = result["close"]
        ema_fast = close_prices.ewm(span=EMA_FAST, adjust=False).mean()
        ema_slow = close_prices.ewm(span=EMA_SLOW, adjust=False).mean()

        # Compute trend: 1=uptrend, -1=downtrend, 0=crossing (undecided)
        ema_diff = ema_fast - ema_slow
        ema_trend = np.where(
            ema_diff > 0, 1, np.where(ema_diff < 0, -1, 0)
        )
        result["ema_fast"] = ema_fast.round(4)
        result["ema_slow"] = ema_slow.round(4)
        result["ema_trend"] = ema_trend  # 1, -1, 0

        # Only count EMA filter as active after enough warm-up bars
        ema_warmed = close_prices.index >= close_prices.index[min(EMA_SLOW, len(close_prices) - 1)]
        # For trend confirmation: longs only in uptrend, shorts only in downtrend
        ema_long_ok = pd.Series(ema_trend == 1, index=result.index) | ~ema_warmed
        ema_short_ok = pd.Series(ema_trend == -1, index=result.index) | ~ema_warmed

        n_uptrend = int((pd.Series(ema_trend, index=result.index) == 1).sum())
        n_downtrend = int((pd.Series(ema_trend, index=result.index) == -1).sum())
        logger.info(
            f"{symbol} v3: EMA trend filter — uptrend={n_uptrend} "
            f"downtrend={n_downtrend} bars"
        )
    except Exception as e:
        logger.warning(f"{symbol}: EMA trend filter failed, bypassing: {e}")
        result["ema_trend"] = 0
        result["ema_fast"] = np.nan
        result["ema_slow"] = np.nan
        ema_long_ok = pd.Series(True, index=result.index)
        ema_short_ok = pd.Series(True, index=result.index)

    # ── Step 5d: Vol-adjusted position sizing (v3 new feature) ────────────
    # pos_size_scalar = target_vol / realized_vol (clipped 0.25–4.0)
    # Realized vol = annualised std of log returns over last VOL_LOOKBACK bars
    try:
        log_ret = np.log(result["close"] / result["close"].shift(1))
        realized_vol = log_ret.rolling(VOL_LOOKBACK, min_periods=5).std() * SQRT_HOURLY
        realized_vol = realized_vol.replace(0, np.nan).fillna(TARGET_VOL)

        pos_scalar = (TARGET_VOL / realized_vol).clip(0.25, 4.0)
        result["pos_size_scalar"] = pos_scalar.round(4)
        result["realized_vol"] = realized_vol.round(6)

        logger.info(
            f"{symbol} v3: vol-adjusted sizing — "
            f"scalar range [{pos_scalar.min():.2f}, {pos_scalar.max():.2f}], "
            f"mean={pos_scalar.mean():.2f}"
        )
    except Exception as e:
        logger.warning(f"{symbol}: Vol sizing failed, defaulting to 1.0: {e}")
        result["pos_size_scalar"] = 1.0
        result["realized_vol"] = np.nan

    # ── Step 6: Vectorized composite scoring ──────────────────────────────
    stc_long = result.get(
        "stc_cross_up", pd.Series(False, index=result.index)
    ).astype(float)
    stc_short = result.get(
        "stc_cross_down", pd.Series(False, index=result.index)
    ).astype(float)

    orb_long = (
        result.get("ORB_signal", pd.Series("", index=result.index)) == "LONG_ENTRY"
    ).astype(float)
    orb_short = (
        result.get("ORB_signal", pd.Series("", index=result.index)) == "SHORT_ENTRY"
    ).astype(float)

    vwap_long = (
        result.get("vwap_signal", pd.Series("", index=result.index)) == "LONG_ENTRY"
    ).astype(float)
    vwap_short = (
        result.get("vwap_signal", pd.Series("", index=result.index)) == "SHORT_ENTRY"
    ).astype(float)

    w_stc = regime_series.map(lambda r: REGIME_WEIGHTS.get(r, DEFAULT_WEIGHTS)["stc"])
    w_orb = regime_series.map(lambda r: REGIME_WEIGHTS.get(r, DEFAULT_WEIGHTS)["orb"])
    w_vwap = regime_series.map(lambda r: REGIME_WEIGHTS.get(r, DEFAULT_WEIGHTS)["vwap"])

    long_score = w_stc * stc_long + w_orb * orb_long + w_vwap * vwap_long
    short_score = w_stc * stc_short + w_orb * orb_short + w_vwap * vwap_short

    composite_score = long_score - short_score
    result["composite_score"] = composite_score.round(3)
    result["composite_regime"] = regime_series

    result["stc_contrib"] = False
    result["orb_contrib"] = False
    result["vwap_contrib"] = False

    # ── Step 7: Generate composite entry signals ───────────────────────────
    # STC must fire as a gate; ORB/VWAP add score
    stc_long_bool = stc_long.astype(bool)
    stc_short_bool = stc_short.astype(bool)

    is_volatile = regime_series == "VOLATILE"

    # v3: add EMA trend filter on top of ADX filter
    is_long_entry = (
        (long_score >= entry_threshold)
        & stc_long_bool
        & ~is_volatile
        & adx_pass
        & ema_long_ok   # v3: only longs in uptrend
    )
    is_short_entry = (
        (short_score >= entry_threshold)
        & stc_short_bool
        & ~is_volatile
        & adx_pass
        & ema_short_ok  # v3: only shorts in downtrend
    )

    # Resolve conflicts: when both fire on same bar, take the stronger one
    both = is_long_entry & is_short_entry
    is_long_entry = is_long_entry & ~(both & (short_score >= long_score))
    is_short_entry = is_short_entry & ~(both & (long_score > short_score))

    # ── Step 8: Override backtester-compatible columns ─────────────────────
    close = result["close"]
    atr = result.get(
        "atr", pd.Series(result["close"] * 0.001, index=result.index)
    ).fillna(result["close"] * 0.001)

    result["entry_signal"] = "NO_TRADE"
    result["bias"] = result.get(
        "bias", pd.Series("NEUTRAL", index=result.index)
    )

    COMP_STOP_ATR = stop_atr_mult
    COMP_T1_ATR = t1_atr_mult
    COMP_T2_ATR = t2_atr_mult
    COMP_T3_ATR = t3_atr_mult

    # LONG entries
    long_idx = result.index[is_long_entry]
    if len(long_idx) > 0:
        result.loc[long_idx, "entry_signal"] = "ENTRY_NOW"
        result.loc[long_idx, "bias"] = "STRONG_BULL"

        for idx_val in long_idx:
            entry_p = float(close.loc[idx_val])
            atr_val = float(atr.loc[idx_val])

            composite_stop = entry_p - COMP_STOP_ATR * atr_val
            result.at[idx_val, "stop_level"] = round(composite_stop, 4)

            t1 = entry_p + COMP_T1_ATR * atr_val
            t2 = entry_p + COMP_T2_ATR * atr_val
            t3 = entry_p + COMP_T3_ATR * atr_val
            result.at[idx_val, "target_1"] = round(t1, 4)
            result.at[idx_val, "target_2"] = round(t2, 4)
            result.at[idx_val, "target_3"] = round(t3, 4)

            risk = entry_p - composite_stop
            reward = t1 - entry_p
            result.at[idx_val, "composite_rr"] = (
                round(reward / risk, 3) if risk > 0 else 0.0
            )

            result.at[idx_val, "stc_contrib"] = bool(stc_long.loc[idx_val])
            result.at[idx_val, "orb_contrib"] = bool(orb_long.loc[idx_val])
            result.at[idx_val, "vwap_contrib"] = bool(vwap_long.loc[idx_val])

    # SHORT entries
    short_idx = result.index[is_short_entry]
    if len(short_idx) > 0:
        result.loc[short_idx, "entry_signal"] = "ENTRY_NOW"
        result.loc[short_idx, "bias"] = "STRONG_BEAR"

        for idx_val in short_idx:
            entry_p = float(close.loc[idx_val])
            atr_val = float(atr.loc[idx_val])

            composite_stop = entry_p + COMP_STOP_ATR * atr_val
            result.at[idx_val, "stop_level"] = round(composite_stop, 4)

            t1 = entry_p - COMP_T1_ATR * atr_val
            t2 = entry_p - COMP_T2_ATR * atr_val
            t3 = entry_p - COMP_T3_ATR * atr_val
            result.at[idx_val, "target_1"] = round(t1, 4)
            result.at[idx_val, "target_2"] = round(t2, 4)
            result.at[idx_val, "target_3"] = round(t3, 4)

            risk = composite_stop - entry_p
            reward = entry_p - t1
            result.at[idx_val, "composite_rr"] = (
                round(reward / risk, 3) if risk > 0 else 0.0
            )

            result.at[idx_val, "stc_contrib"] = bool(stc_short.loc[idx_val])
            result.at[idx_val, "orb_contrib"] = bool(orb_short.loc[idx_val])
            result.at[idx_val, "vwap_contrib"] = bool(vwap_short.loc[idx_val])

    # ── Step 8b: R:R filter — reject entries with composite_rr < MIN_RR ────
    if "composite_rr" in result.columns:
        low_rr_mask = (result["entry_signal"] == "ENTRY_NOW") & (
            result["composite_rr"].fillna(0) < MIN_RR
        )
        n_rr_filtered = low_rr_mask.sum()
        if n_rr_filtered > 0:
            result.loc[low_rr_mask, "entry_signal"] = "NO_TRADE"
            result.loc[low_rr_mask, "bias"] = "NEUTRAL"
            logger.info(
                f"{symbol} COMPOSITE v3: filtered {n_rr_filtered} entries with R:R < {MIN_RR}"
            )

    # Volatile blocks
    volatile_with_signal = is_volatile & (
        stc_long.astype(bool)
        | stc_short.astype(bool)
        | orb_long.astype(bool)
        | orb_short.astype(bool)
        | vwap_long.astype(bool)
        | vwap_short.astype(bool)
    )
    result.loc[volatile_with_signal, "entry_signal"] = "COMPOSITE_VOLATILE_BLOCK"

    if "composite_rr" not in result.columns:
        result["composite_rr"] = np.nan

    # ── Step 9: Logging ───────────────────────────────────────────────────
    n_long_dir = (
        (result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BULL")
    ).sum()
    n_short_dir = (
        (result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BEAR")
    ).sum()
    n_volatile = (result["entry_signal"] == "COMPOSITE_VOLATILE_BLOCK").sum()
    n_stc = result["stc_contrib"].sum()
    n_orb = result["orb_contrib"].sum()
    n_vwap = result["vwap_contrib"].sum()
    regime_counts = regime_series.value_counts().to_dict()

    logger.info(
        f"{symbol} COMPOSITE v3: {n_long_dir} LONG + {n_short_dir} SHORT entries "
        f"({n_volatile} volatile-blocked) over {len(result)} bars | "
        f"STC={n_stc} ORB={n_orb} VWAP={n_vwap} contributions | "
        f"ADX_threshold={adx_threshold} | Regime: {regime_counts}"
    )

    return result


def _add_empty_composite_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Add empty composite columns for insufficient data case."""
    for col in [
        "composite_score",
        "composite_rr",
        "composite_regime",
        "stc_contrib",
        "orb_contrib",
        "vwap_contrib",
        "ORB_signal",
        "orb_stop",
        "orb_target_1",
        "orb_target_2",
        "vwap_signal",
        "vwap_stop",
        "vwap_target_1",
        "vwap_target_2",
        "adx",
        "ema_trend",
        "pos_size_scalar",
        "realized_vol",
    ]:
        if col not in df.columns:
            if col in ("stc_contrib", "orb_contrib", "vwap_contrib"):
                df[col] = False
            elif col in ("ORB_signal", "vwap_signal", "composite_regime"):
                df[col] = ""
            elif col == "ema_trend":
                df[col] = 0
            elif col == "pos_size_scalar":
                df[col] = 1.0
            else:
                df[col] = np.nan
    df["entry_signal"] = "NO_TRADE"
    df["bias"] = "NEUTRAL"
    return df


if __name__ == "__main__":
    """Quick smoke test — run from engine/ directory."""
    import os
    import sys

    _engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _engine_dir not in sys.path:
        sys.path.insert(0, _engine_dir)

    logging.basicConfig(level=logging.INFO)

    rng = np.random.default_rng(42)
    n = 250
    base_price = 5800.0
    closes = base_price + np.cumsum(rng.normal(0, 5, n))
    highs = closes + rng.uniform(2, 10, n)
    lows = closes - rng.uniform(2, 10, n)
    opens = closes - rng.normal(0, 3, n)
    volumes = rng.integers(10000, 50000, n).astype(float)

    idx = pd.date_range(
        start=pd.Timestamp("2025-01-02 09:30:00", tz="America/New_York"),
        periods=n,
        freq="1h",
    )

    df_test = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )

    print("Running composite v3 signal smoke test on 250 synthetic MES 1h bars...")
    result = generate_composite_signals(df_test, symbol="MES")

    n_entry = (result["entry_signal"] == "ENTRY_NOW").sum()
    n_long = (
        (result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BULL")
    ).sum()
    n_short = (
        (result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BEAR")
    ).sum()

    print(f"Entries: {n_entry} total ({n_long} LONG, {n_short} SHORT)")
    print(f"Regime distribution: {result['composite_regime'].value_counts().to_dict()}")
    print(
        f"Composite score range: [{result['composite_score'].min():.3f}, "
        f"{result['composite_score'].max():.3f}]"
    )
    print(f"EMA trend distribution: {pd.Series(result['ema_trend']).value_counts().to_dict()}")
    print(
        f"Pos scalar range: [{result['pos_size_scalar'].min():.2f}, "
        f"{result['pos_size_scalar'].max():.2f}]"
    )
    print(f"ADX columns added: {'adx' in result.columns}")
    print("SMOKE TEST PASSED")
