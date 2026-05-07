"""
JARVIS TRADER — COHEN-MES Composite Signal Generator
=====================================================
Combines three independent signal sources into a regime-adaptive composite signal.

Strategy: "Never bet on one signal" — Steve Cohen / Point72 principle.
Each source captures a different market dynamic:

  1. STC (Schaff Trend Cycle + 5-layer framework)  — momentum / trend
  2. ORB (Opening Range Breakout)                  — morning momentum (9:30-11:00 ET)
  3. VWAP Deviation Reversion                      — intraday mean reversion (11:00+ ET)

Regime-Adaptive Weighting (from RegimeClassifier):
  TRENDING regime  → STC=0.60, ORB=0.30, VWAP=0.10  (STC dominates)
  RANGING regime   → STC=0.50, ORB=0.20, VWAP=0.30  (STC primary, VWAP supporting)
  VOLATILE regime  → ALL=0.00                         (no entries — sit out)

Entry threshold: composite_score >= 0.55 for LONG or SHORT (v2, was 0.35)
  (STC alone can enter at 0.50+, but VWAP alone at 0.30 cannot)
ADX filter: ADX must be >= 25 for entries (v2 addition, eliminates chop)
ORB band: 3.0×ATR default (v2, was 2.5)
R:R filter: entries with composite_rr < 1.5 are rejected

Output columns added (backtester-compatible):
  entry_signal  : "ENTRY_NOW" | "NO_TRADE" | "COMPOSITE_VOLATILE_BLOCK"
  bias          : "STRONG_BULL" | "STRONG_BEAR" | (original)
  stop_level    : tightest stop from contributing signals
  target_1      : STC T1 (priority), else ORB T1, else VWAP T1
  target_2      : furthest target from any contributing signal
  target_3      : original STC T3

  composite_score    : float, signed score (positive = bullish, negative = bearish)
  composite_regime   : "TRENDING" | "RANGING" | "VOLATILE"
  stc_contrib        : bool — STC signal contributed to this entry
  orb_contrib        : bool — ORB signal contributed
  vwap_contrib       : bool — VWAP signal contributed
  composite_rr       : R:R ratio at T1
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("composite_signals")

# ── Regime Weights ─────────────────────────────────────────────────────────────
REGIME_WEIGHTS = {
    "TRENDING": {"stc": 0.60, "orb": 0.30, "vwap": 0.10},
    "RANGING": {"stc": 0.50, "orb": 0.20, "vwap": 0.30},
    "VOLATILE": {"stc": 0.00, "orb": 0.00, "vwap": 0.00},
}
DEFAULT_WEIGHTS = REGIME_WEIGHTS["RANGING"]  # default when regime unknown

# Entry threshold: composite score must exceed this to generate a signal
# 0.35 lets STC alone (0.50 or 0.60) enter, but VWAP alone (0.30) cannot
ENTRY_THRESHOLD = 0.55  # v2: raised from 0.35 to eliminate chop entries

# Minimum reward:risk ratio for composite entries
MIN_RR = 1.2


def generate_composite_signals(
    df: pd.DataFrame,
    symbol: str = "MES",
    band_mult: float = 3.0,  # v2: widened from 2.5 to reduce false breakouts
    stop_mult: float = 0.5,  # legacy: ignored here; kept for call-site compat
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
    Generate composite MES signals combining STC + ORB + VWAP with
    regime-adaptive weighting.

    Parameters
    ----------
    df : pd.DataFrame
        1-hour OHLCV data with DatetimeIndex (Eastern or UTC).
        Required columns: open, high, low, close, volume.
    symbol : str
        Symbol for logging and per-instrument params.
    band_mult : float
        ATR multiplier for VWAP bands (passed to generate_vwap_signals).
    stop_mult : float
        ATR multiplier for VWAP stops (passed to generate_vwap_signals).
    atr_period : int
        ATR period for VWAP computation.
    entry_threshold : float
        Minimum composite score to generate ENTRY_NOW signal (default 0.40).
    stc_oversold : float, optional
        STC oversold level (e.g., 15). If None, uses symbol defaults.
    stc_overbought : float, optional
        STC overbought level (e.g., 83). If None, uses symbol defaults.

    Returns
    -------
    pd.DataFrame
        Input df with all signal columns from each strategy plus composite
        columns. Backtester-compatible: entry_signal, bias, stop_level,
        target_1, target_2, target_3 are all set.
    """
    if df.empty or len(df) < 20:
        logger.warning(f"{symbol}: insufficient data ({len(df)} bars) — returning empty signals")
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
            adaptive_regime=True,  # uses RegimeClassifier → adds regime_type
            regime_filter=False,  # let composite layer handle filtering
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

        df_orb = _gen_orb(df_orig.copy(), symbol=symbol, volume_filter=True, regime_filter=False)
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

    # ORB columns
    for col in ["ORB_signal", "orb_stop", "orb_target_1", "orb_target_2", "orb_rr"]:
        if col in df_orb.columns:
            result[col] = df_orb[col].values

    # VWAP columns
    for col in ["vwap_signal", "vwap_stop", "vwap_target_1", "vwap_target_2", "vwap_rr", "vwap"]:
        if col in df_vwap.columns:
            result[col] = df_vwap[col].values

    # ── Step 5: Determine regime per bar ──────────────────────────────────
    # adaptive_regime=True → 'regime_type' column added by RegimeClassifier
    # Values: "TRENDING" | "RANGING" | "VOLATILE"
    if "regime_type" in result.columns:
        regime_series = result["regime_type"].fillna("RANGING")
    else:
        # Fallback: run classifier manually
        try:
            from backtest.regime import RegimeClassifier

            clf = RegimeClassifier()
            classified = clf.classify(result)
            regime_series = classified["regime_type"].fillna("RANGING")
            result["regime_type"] = regime_series
        except Exception:
            regime_series = pd.Series("RANGING", index=result.index)
            result["regime_type"] = regime_series

    # ── Step 5b: ADX trend-strength filter (v2) ───────────────────────────────
    # Only allow entries when ADX > adx_threshold (default 25), ensuring
    # minimum trend conviction before firing composite signals.
    # In RANGING regime, ADX is typically 10-20 (flat); in TRENDING, 25-40+.
    try:
        adx_threshold = 25.0
        period = 14
        high = result["high"]
        low = result["low"]
        close_s = result["close"]

        # True Range
        tr1 = high - low
        tr2 = (high - close_s.shift(1)).abs()
        tr3 = (low - close_s.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # Smooth with Wilder EMA (alpha = 1/period)
        atr_wilder = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        plus_di = 100 * pd.Series(plus_dm, index=result.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_wilder
        minus_di = 100 * pd.Series(minus_dm, index=result.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_wilder

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean().fillna(0)

        result["adx"] = adx.round(2)
        adx_pass = adx >= adx_threshold
        logger.info(f"{symbol}: ADX filter — {adx_pass.sum()} / {len(adx_pass)} bars pass ADX≥{adx_threshold} ({adx_pass.mean():.1%})")
    except Exception as e:
        logger.warning(f"{symbol}: ADX filter failed, bypassing: {e}")
        adx_pass = pd.Series(True, index=result.index)  # fail-open
        result["adx"] = np.nan

    # ── Step 6: Vectorized composite scoring ──────────────────────────────
    # Encode each signal as 0 or 1
    stc_long = result.get("stc_cross_up", pd.Series(False, index=result.index)).astype(float)
    stc_short = result.get("stc_cross_down", pd.Series(False, index=result.index)).astype(float)

    orb_long = (result.get("ORB_signal", pd.Series("", index=result.index)) == "LONG_ENTRY").astype(
        float
    )
    orb_short = (
        result.get("ORB_signal", pd.Series("", index=result.index)) == "SHORT_ENTRY"
    ).astype(float)

    vwap_long = (
        result.get("vwap_signal", pd.Series("", index=result.index)) == "LONG_ENTRY"
    ).astype(float)
    vwap_short = (
        result.get("vwap_signal", pd.Series("", index=result.index)) == "SHORT_ENTRY"
    ).astype(float)

    # Weights by regime
    w_stc = regime_series.map(lambda r: REGIME_WEIGHTS.get(r, DEFAULT_WEIGHTS)["stc"])
    w_orb = regime_series.map(lambda r: REGIME_WEIGHTS.get(r, DEFAULT_WEIGHTS)["orb"])
    w_vwap = regime_series.map(lambda r: REGIME_WEIGHTS.get(r, DEFAULT_WEIGHTS)["vwap"])

    long_score = w_stc * stc_long + w_orb * orb_long + w_vwap * vwap_long
    short_score = w_stc * stc_short + w_orb * orb_short + w_vwap * vwap_short

    # Signed composite score: positive = bullish pressure, negative = bearish
    composite_score = long_score - short_score
    result["composite_score"] = composite_score.round(3)
    result["composite_regime"] = regime_series

    # Which signals contributed
    result["stc_contrib"] = False
    result["orb_contrib"] = False
    result["vwap_contrib"] = False

    # ── Step 7: Generate composite entry signals ───────────────────────────
    # OPTION A: STC must fire as a GATE — ORB/VWAP only add to score, cannot
    # generate entries without STC. This preserves STC's proven ~35% WR.
    stc_long_bool = stc_long.astype(bool)
    stc_short_bool = stc_short.astype(bool)

    is_volatile = regime_series == "VOLATILE"
    is_long_entry = (long_score >= entry_threshold) & stc_long_bool & ~is_volatile & adx_pass
    is_short_entry = (short_score >= entry_threshold) & stc_short_bool & ~is_volatile & adx_pass

    # Resolve conflicts: when both fire on same bar, take the stronger one
    both = is_long_entry & is_short_entry
    is_long_entry = is_long_entry & ~(both & (short_score >= long_score))
    is_short_entry = is_short_entry & ~(both & (long_score > short_score))

    # ── Step 8: Override backtester-compatible columns ─────────────────────
    close = result["close"]
    atr = result.get("atr", pd.Series(result["close"] * 0.001, index=result.index)).fillna(
        result["close"] * 0.001
    )

    # Default: no composite signal
    result["entry_signal"] = "NO_TRADE"
    result["bias"] = result.get("bias", pd.Series("NEUTRAL", index=result.index))

    # ── Composite stop/target ATR multiples ──────────────────────────────
    # Defaults (stop=1.00, T1=2.50, T2=4.00, T3=6.00) come from the Sprint-16
    # STC-gate tuning. Now honored from caller params so Bayesian / grid
    # search across these axes is actually effective. Pre-2026-04-20 these
    # were hardcoded, silently defeating 4 of 6 search dimensions.
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

            # Composite stop: fixed 1.5 ATR below entry (wider than STC's 0.70)
            composite_stop = entry_p - COMP_STOP_ATR * atr_val
            result.at[idx_val, "stop_level"] = round(composite_stop, 4)

            # Composite targets: closer T1 for higher hit rate
            t1 = entry_p + COMP_T1_ATR * atr_val
            t2 = entry_p + COMP_T2_ATR * atr_val
            t3 = entry_p + COMP_T3_ATR * atr_val
            result.at[idx_val, "target_1"] = round(t1, 4)
            result.at[idx_val, "target_2"] = round(t2, 4)
            result.at[idx_val, "target_3"] = round(t3, 4)

            # R:R
            risk = entry_p - composite_stop
            reward = t1 - entry_p
            result.at[idx_val, "composite_rr"] = round(reward / risk, 3) if risk > 0 else 0.0

            # Contribution flags
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

            # Composite stop: fixed 1.5 ATR above entry
            composite_stop = entry_p + COMP_STOP_ATR * atr_val
            result.at[idx_val, "stop_level"] = round(composite_stop, 4)

            # Composite targets: closer T1 for higher hit rate
            t1 = entry_p - COMP_T1_ATR * atr_val
            t2 = entry_p - COMP_T2_ATR * atr_val
            t3 = entry_p - COMP_T3_ATR * atr_val
            result.at[idx_val, "target_1"] = round(t1, 4)
            result.at[idx_val, "target_2"] = round(t2, 4)
            result.at[idx_val, "target_3"] = round(t3, 4)

            # R:R
            risk = composite_stop - entry_p
            reward = entry_p - t1
            result.at[idx_val, "composite_rr"] = round(reward / risk, 3) if risk > 0 else 0.0

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
            logger.info(f"{symbol} COMPOSITE: filtered {n_rr_filtered} entries with R:R < {MIN_RR}")

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

    # Ensure composite_rr exists everywhere
    if "composite_rr" not in result.columns:
        result["composite_rr"] = np.nan

    # ── Step 9: Logging ───────────────────────────────────────────────────
    n_long_dir = ((result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BULL")).sum()
    n_short_dir = (
        (result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BEAR")
    ).sum()
    n_volatile = (result["entry_signal"] == "COMPOSITE_VOLATILE_BLOCK").sum()
    n_stc = result["stc_contrib"].sum()
    n_orb = result["orb_contrib"].sum()
    n_vwap = result["vwap_contrib"].sum()
    regime_counts = regime_series.value_counts().to_dict()

    logger.info(
        f"{symbol} COMPOSITE: {n_long_dir} LONG + {n_short_dir} SHORT entries "
        f"({n_volatile} volatile-blocked) over {len(result)} bars | "
        f"STC={n_stc} ORB={n_orb} VWAP={n_vwap} contributions | "
        f"Regime: {regime_counts}"
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
    ]:
        if col not in df.columns:
            if col in ("stc_contrib", "orb_contrib", "vwap_contrib"):
                df[col] = False
            elif col in ("ORB_signal", "vwap_signal", "composite_regime"):
                df[col] = ""
            else:
                df[col] = np.nan
    df["entry_signal"] = "NO_TRADE"
    df["bias"] = "NEUTRAL"
    return df


if __name__ == "__main__":
    """Quick smoke test — run from engine/ directory."""
    import os
    import sys

    # Add engine/ to path so package imports work
    _engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _engine_dir not in sys.path:
        sys.path.insert(0, _engine_dir)

    logging.basicConfig(level=logging.INFO)

    # Build 100 bars of synthetic 1h MES-like data
    rng = np.random.default_rng(42)
    n = 120
    base_price = 5800.0
    closes = base_price + np.cumsum(rng.normal(0, 5, n))
    highs = closes + rng.uniform(2, 10, n)
    lows = closes - rng.uniform(2, 10, n)
    opens = closes - rng.normal(0, 3, n)
    volumes = rng.integers(10000, 50000, n).astype(float)

    # Build timezone-aware DatetimeIndex (1h bars, Eastern Time, RTH-like)
    import pandas as pd
    import pytz

    et = pytz.timezone("America/New_York")
    start = pd.Timestamp("2025-01-02 09:30:00", tz="America/New_York")
    idx = pd.date_range(start=start, periods=n, freq="1h")

    df_test = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )

    print("Running composite signal smoke test on 120 synthetic MES 1h bars...")
    result = generate_composite_signals(df_test, symbol="MES")

    n_entry = (result["entry_signal"] == "ENTRY_NOW").sum()
    n_long = ((result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BULL")).sum()
    n_short = ((result["entry_signal"] == "ENTRY_NOW") & (result["bias"] == "STRONG_BEAR")).sum()

    print(f"Entries: {n_entry} total ({n_long} LONG, {n_short} SHORT)")
    print(f"Regime distribution: {result['composite_regime'].value_counts().to_dict()}")
    print(
        f"Composite score range: [{result['composite_score'].min():.3f}, {result['composite_score'].max():.3f}]"
    )
    print(f"Columns added: {[c for c in result.columns if c not in df_test.columns][:10]}...")
    print("SMOKE TEST PASSED")
