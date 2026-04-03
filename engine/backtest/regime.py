"""
JARVIS TRADER — Regime Classifier
Detects market regime (TRENDING / RANGING / VOLATILE) on each bar
and returns adaptive STC parameter sets.

Walk-forward analysis showed that static STC thresholds fail because
different regimes require different crossover sensitivity:
  - TRENDING:  STC_OS=15, STC_OB=92 — tighter OB keeps you in trend longer
  - RANGING:   STC_OS=19, STC_OB=83 — wider band catches mean-reversion swings
  - VOLATILE:  skip entries — high ATR/Keltner compression → whipsaw territory

Regime detection uses three independent signals, voted by majority:
  1. ADX-proxy  — Directional Movement strength via EMA spread
  2. BBWidth    — Bollinger Band Width (narrow = compression, wide = trending)
  3. ATR/price  — Normalized volatility vs rolling median

Usage:
    from backtest.regime import RegimeClassifier
    clf = RegimeClassifier()
    df = clf.classify(df)   # adds 'regime_type', 'adaptive_stc_os', 'adaptive_stc_ob' columns
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

# ── Regime-specific STC parameter sets ────────────────────────────────────────
# Validated against walk-forward data: TRENDING needs STC_OB=92 (MNQ finding),
# RANGING benefits from STC_OS=19/OB=83 (more frequent crossovers match the regime).

REGIME_PARAMS: Dict[str, Tuple[float, float]] = {
    "TRENDING": (15, 92),  # STC_OS, STC_OB — strict entry, wide hold
    "RANGING": (19, 83),  # looser entry catches mean-reversion swings
    "VOLATILE": (15, 88),  # default — entries suppressed by ATR gate in backtester
}


class RegimeClassifier:
    """
    Classifies each bar into TRENDING / RANGING / VOLATILE using three
    voting signals. Adds adaptive STC parameter columns for use by
    generate_signals().

    Parameters
    ----------
    ema_fast : int
        Fast EMA period for directional movement proxy (default 20)
    ema_slow : int
        Slow EMA period for directional movement proxy (default 50)
    bb_period : int
        Bollinger Band period for width calculation (default 20)
    bb_std : float
        Standard deviations for Bollinger Bands (default 2.0)
    atr_period : int
        ATR period for normalized volatility (default 14)
    atr_lookback : int
        Rolling window to compute median ATR for normalization (default 50)
    trending_adx_threshold : float
        EMA spread (as % of close) above which market is trending (default 0.005)
    volatile_atr_threshold : float
        Normalized ATR above which market is volatile (default 1.5)
    """

    def __init__(
        self,
        ema_fast: int = 20,
        ema_slow: int = 50,
        bb_period: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
        atr_lookback: int = 50,
        trending_adx_threshold: float = 0.005,
        volatile_atr_threshold: float = 1.5,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.atr_lookback = atr_lookback
        self.trending_adx_threshold = trending_adx_threshold
        self.volatile_atr_threshold = volatile_atr_threshold

    # ── Internal signal computations ─────────────────────────────────────────

    def _ema_spread(self, close: pd.Series) -> pd.Series:
        """
        EMA spread = |EMA_fast - EMA_slow| / close.
        High spread → trending; low spread → ranging.
        """
        ema_f = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_s = close.ewm(span=self.ema_slow, adjust=False).mean()
        return ((ema_f - ema_s).abs() / close).fillna(0)

    def _bb_width(self, close: pd.Series) -> pd.Series:
        """
        Bollinger Band Width = (upper - lower) / middle.
        High BBW → wide, trending/volatile; low BBW → compression, ranging.
        Normalized: ratio to its own rolling median (so it's regime-comparable).
        """
        mid = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std(ddof=0)
        bbw = (2 * self.bb_std * std / mid).fillna(0)
        bbw_median = bbw.rolling(self.atr_lookback).median()
        return (bbw / bbw_median.replace(0, np.nan)).fillna(1.0)

    def _normalized_atr(self, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """
        ATR normalized to its rolling median.
        Value > 1.5 = elevated volatility (VOLATILE regime).
        Value < 0.7 = compressed volatility (typically precedes breakout).
        """
        from backtest.indicators import wilder_atr

        atr = wilder_atr(high, low, close, period=self.atr_period)
        atr_median = atr.rolling(self.atr_lookback).median()
        return (atr / atr_median.replace(0, np.nan)).fillna(1.0)

    # ── Main classification ───────────────────────────────────────────────────

    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add regime columns to df. Requires: close, high, low columns.

        Columns added:
        - 'regime_type'     : 'TRENDING' | 'RANGING' | 'VOLATILE'
        - 'ema_spread'      : directional movement proxy
        - 'bb_width_norm'   : normalized Bollinger Band width
        - 'atr_norm'        : normalized ATR
        - 'adaptive_stc_os' : regime-specific STC oversold threshold
        - 'adaptive_stc_ob' : regime-specific STC overbought threshold
        """
        df = df.copy()

        spread = self._ema_spread(df["close"])
        bbw = self._bb_width(df["close"])
        atr_n = self._normalized_atr(df["high"], df["low"], df["close"])

        df["ema_spread"] = spread
        df["bb_width_norm"] = bbw
        df["atr_norm"] = atr_n

        # ── Vote-based classification ─────────────────────────────────────────
        # Signal 1: EMA spread votes TRENDING if spread > threshold
        vote_trending = (spread > self.trending_adx_threshold).astype(int)

        # Signal 2: BBW votes TRENDING if above median (market in motion)
        #           votes RANGING if below median (consolidation)
        vote_bb_trending = (bbw > 1.0).astype(int)

        # Signal 3: ATR votes VOLATILE if normalized ATR is high
        vote_volatile = (atr_n > self.volatile_atr_threshold).astype(int)

        # Final classification:
        # VOLATILE if ATR is elevated (overrides other signals)
        # TRENDING if 2+ trending votes and not volatile
        # RANGING otherwise
        trending_votes = vote_trending + vote_bb_trending
        regime = pd.Series("RANGING", index=df.index)
        regime[trending_votes >= 2] = "TRENDING"
        regime[vote_volatile == 1] = "VOLATILE"

        df["regime_type"] = regime

        # ── Map to adaptive STC parameters ──────────────────────────────────
        df["adaptive_stc_os"] = (
            regime.map({k: v[0] for k, v in REGIME_PARAMS.items()}).fillna(15).astype(float)
        )

        df["adaptive_stc_ob"] = (
            regime.map({k: v[1] for k, v in REGIME_PARAMS.items()}).fillna(88).astype(float)
        )

        return df

    def regime_summary(self, df: pd.DataFrame) -> Dict[str, float]:
        """Return percentage breakdown of regimes in df."""
        if "regime_type" not in df.columns:
            df = self.classify(df)
        counts = df["regime_type"].value_counts()
        total = len(df)
        return {k: round(v / total * 100, 1) for k, v in counts.items()}
