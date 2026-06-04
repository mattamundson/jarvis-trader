"""
JARVIS TRADER -- Multi-Timeframe (MTF) Confirmation Filter

Requires 4h STC signal alignment before allowing 1h entries.
Conservative gate: only blocks entries that are clearly counter-trend
on the higher timeframe.

Usage:
    from backtest.mtf_filter import MTFFilter
    mtf = MTFFilter()
    aligned = mtf.check_alignment(df_1h, df_4h)
    # aligned is a boolean Series indexed like df_1h
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


class MTFFilter:
    """
    Multi-Timeframe confirmation filter.

    For each 1h bar, looks up the corresponding 4h bar's STC state
    and determines whether the higher-timeframe trend aligns with
    the 1h entry direction.

    Alignment rules:
      LONG entries (bias STRONG_BULL / LEAN_BULL):
        ALLOW if 4h STC is overbought, rising, or crossed up within last 3 bars
        BLOCK if 4h STC is oversold, falling, or crossed down within last 3 bars

      SHORT entries (bias STRONG_BEAR / LEAN_BEAR):
        ALLOW if 4h STC is oversold, falling, or crossed down within last 3 bars
        BLOCK if 4h STC is overbought, rising, or crossed up within last 3 bars

      Non-entry bars or NEUTRAL bias: always True (no filtering needed)
    """

    LONG_BIASES = frozenset({"STRONG_BULL", "LEAN_BULL"})
    SHORT_BIASES = frozenset({"STRONG_BEAR", "LEAN_BEAR"})

    # STC states that support long entries
    LONG_ALLOW_STATES = frozenset({"overbought", "rising"})
    # STC states that support short entries
    SHORT_ALLOW_STATES = frozenset({"oversold", "falling"})

    def __init__(self, cross_lookback: int = 3):
        """
        Parameters
        ----------
        cross_lookback : int
            Number of 4h bars to look back for a recent STC cross.
            Default 3 (= 12 hours of 4h data).
        """
        self.cross_lookback = cross_lookback

    def _align_htf_to_ltf(self, df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> pd.DataFrame:
        """
        Forward-fill 4h indicator values onto the 1h index.

        Returns a DataFrame indexed like df_1h with columns:
          htf_stc_signal, htf_stc_cross_up, htf_stc_cross_down,
          htf_recent_cross_up, htf_recent_cross_down
        """
        # Extract the columns we need from 4h
        htf = df_4h[["stc_signal", "stc_cross_up", "stc_cross_down"]].copy()
        htf.columns = ["htf_stc_signal", "htf_stc_cross_up", "htf_stc_cross_down"]

        # Rolling lookback: did a cross happen within the last N 4h bars?
        htf["htf_recent_cross_up"] = (
            htf["htf_stc_cross_up"].rolling(self.cross_lookback, min_periods=1).max().astype(bool)
        )
        htf["htf_recent_cross_down"] = (
            htf["htf_stc_cross_down"].rolling(self.cross_lookback, min_periods=1).max().astype(bool)
        )

        # Reindex onto 1h timestamps using forward-fill
        htf_aligned = htf.reindex(df_1h.index, method="ffill")
        return htf_aligned

    def check_alignment(
        self,
        df_1h: pd.DataFrame,
        df_4h: pd.DataFrame,
        df_1d: Optional[pd.DataFrame] = None,
    ) -> pd.Series:
        """
        Determine MTF alignment for each 1h bar.
        Includes 4h trend and optional daily regime checks.
        """
        htf = self._align_htf_to_ltf(df_1h, df_4h)
        aligned = pd.Series(True, index=df_1h.index)

        # 1. Daily Regime Check (Phase 6.6)
        if df_1d is not None:
            # Reindex daily onto 1h
            from backtest.regime_classifier import RegimeClassifierV2
            classifier = RegimeClassifierV2()
            daily_regime = classifier.classify(df_1d)["regime_v2"]
            daily_aligned = daily_regime.reindex(df_1h.index, method="ffill")

            # Block ALL entries in CRISIS or highly VOLATILE daily regimes
            # unless specifically allowed by strategy
            daily_blocked = daily_aligned.isin(["CRISIS", "VOLATILE"])
            aligned[daily_blocked] = False

        # Only evaluate 4h alignment for remaining bars with actual entry signals
        is_entry = (df_1h["entry_signal"] == "ENTRY_NOW") & aligned
        if not is_entry.any():
            return aligned

        bias = df_1h["bias"]
        htf_signal = htf["htf_stc_signal"]
        htf_cross_up = htf["htf_recent_cross_up"]
        htf_cross_down = htf["htf_recent_cross_down"]

        # ---- LONG entries ----
        is_long_entry = is_entry & bias.isin(self.LONG_BIASES)
        if is_long_entry.any():
            long_allow = htf_signal.isin(self.LONG_ALLOW_STATES) | htf_cross_up
            # Block long entries where 4h does NOT support longs
            aligned[is_long_entry & ~long_allow] = False

        # ---- SHORT entries ----
        is_short_entry = is_entry & bias.isin(self.SHORT_BIASES)
        if is_short_entry.any():
            short_allow = htf_signal.isin(self.SHORT_ALLOW_STATES) | htf_cross_down
            # Block short entries where 4h does NOT support shorts
            aligned[is_short_entry & ~short_allow] = False

        return aligned

