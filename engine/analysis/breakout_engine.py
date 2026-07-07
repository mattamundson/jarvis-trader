"""
JARVIS ANALYSIS — Volume Profile & Breakout Engine
==================================================
Calculates Volume Profile levels (POC, VAH, VAL) and identifies breakouts.
Essential for institutional-grade entries.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


class VolumeProfileEngine:
    """
    Calculates Volume Profile metrics from OHLCV bars.
    """

    def __init__(self, value_area_pct: float = 0.70):
        self.value_area_pct = value_area_pct

    def calculate_profile(self, df: pd.DataFrame, bins: int = 50) -> Dict[str, Any]:
        """
        Computes Volume Profile, POC, VAH, and VAL.
        """
        if df.empty or "close" not in df.columns or "volume" not in df.columns:
            return {}

        df = df.copy()

        low = df["low"].min()
        high = df["high"].max()

        # Create price bins
        price_bins = np.linspace(low, high, bins + 1)
        bin_volume = np.zeros(bins)

        # Assign volume to bins (approximate using close for simplicity, ideally distribute over high/low)
        # For a more accurate profile, we'd split bar volume across multiple bins between low and high.
        for _, row in df.iterrows():
            # Find bins covering the bar range
            idx_low = np.digitize(row["low"], price_bins) - 1
            idx_high = np.digitize(row["high"], price_bins) - 1

            idx_low = max(0, min(bins - 1, idx_low))
            idx_high = max(0, min(bins - 1, idx_high))

            num_bins = (idx_high - idx_low) + 1
            vol_per_bin = row["volume"] / num_bins

            for i in range(idx_low, idx_high + 1):
                bin_volume[i] += vol_per_bin

        # Point of Control (POC)
        poc_idx = np.argmax(bin_volume)
        poc_price = (price_bins[poc_idx] + price_bins[poc_idx + 1]) / 2

        # Value Area (VA)
        total_volume = np.sum(bin_volume)
        target_va_volume = total_volume * self.value_area_pct

        va_indices = {poc_idx}
        current_va_volume = bin_volume[poc_idx]

        lower_idx = poc_idx - 1
        upper_idx = poc_idx + 1

        while current_va_volume < target_va_volume:
            vol_lower = bin_volume[lower_idx] if lower_idx >= 0 else 0
            vol_upper = bin_volume[upper_idx] if upper_idx < bins else 0

            if vol_lower == 0 and vol_upper == 0:
                break

            if vol_lower >= vol_upper:
                current_va_volume += vol_lower
                va_indices.add(lower_idx)
                lower_idx -= 1
            else:
                current_va_volume += vol_upper
                va_indices.add(upper_idx)
                upper_idx += 1

        vah_idx = max(va_indices)
        val_idx = min(va_indices)

        vah = price_bins[vah_idx + 1]
        val = price_bins[val_idx]

        return {
            "poc": poc_price,
            "vah": vah,
            "val": val,
            "bins": bins,
            "total_volume": total_volume,
            "va_volume_pct": current_va_volume / total_volume if total_volume > 0 else 0
        }

    def detect_breakout(self, df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Checks if current price is breaking out of the Value Area.
        """
        if not profile:
            return {"status": "none", "side": "none"}

        current_price = df["close"].iloc[-1]
        prev_price = df["close"].iloc[-2] if len(df) > 1 else current_price

        vah = profile["vah"]
        val = profile["val"]

        # Bullish Breakout: Close above VAH
        if current_price > vah and prev_price <= vah:
            return {"status": "breakout", "side": "bullish", "level": vah, "name": "VAH"}

        # Bearish Breakout: Close below VAL
        if current_price < val and prev_price >= val:
            return {"status": "breakout", "side": "bearish", "level": val, "name": "VAL"}

        # Inside VA
        if val <= current_price <= vah:
            return {"status": "inside_va", "side": "neutral"}

        # Extension (already out)
        if current_price > vah:
            return {"status": "extended", "side": "bullish"}
        if current_price < val:
            return {"status": "extended", "side": "bearish"}

        return {"status": "none", "side": "neutral"}
