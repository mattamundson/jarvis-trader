"""
JARVIS TRADER -- stark_tpo_strategy.py
======================================
The "Stark-Cohen Composite (Mark III)" Strategy.
Fully deterministic Auction Market Theory (AMT) and Time Price Opportunity (TPO)
evaluation matrix. Removes qualitative LLM guesswork by evaluating exact Fair Value
limit order zones (POC/VAH/VAL).
"""

import logging
from enum import Enum
from typing import Dict, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

class MarketRegime(Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING_VALUE = "RANGING_VALUE"
    VOLATILE_HALT = "VOLATILE_HALT"

class MarketStructure(Enum):
    INSIDE_VALUE = "INSIDE_VALUE"    # Price is accepted currently in the value area
    GAP_IMBALANCE = "GAP_IMBALANCE"  # Price opening outside Value Area
    BREAKOUT = "BREAKOUT"            # Price pushing through VAH/VAL on high volume
    UNKNOWN = "UNKNOWN"

class StarkTPOStrategy:
    """
    Deterministic Auction Market Theory & TPO profile generator.
    Evaluates 15-minute and 1h intervals to output pure binary execution scores.
    """

    def __init__(self, value_area_pct: float = 0.70):
        self.value_area_pct = value_area_pct
        self.tick_size = 0.25 # Default micro-futures tick size

    def _calculate_tpo_profile(self, df: pd.DataFrame) -> Tuple[float, float, float]:
        """
        Determines the Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).
        Bins prices into discrete tick volumes over the given timeframe.
        """
        # Defensive check
        if df.empty or 'close' not in df.columns or 'volume' not in df.columns:
            logger.warning("StarkTPO: Missing close/volume columns for TPO profile.")
            return np.nan, np.nan, np.nan

        # Use Close prices multiplied by volume to map the histogram
        prices = df['close'].values
        volumes = df['volume'].values

        if len(prices) == 0 or np.sum(volumes) == 0:
            return np.nan, np.nan, np.nan

        # Determine strict bin edges based on min/max and tick size
        min_p = np.min(prices)
        max_p = np.max(prices)

        # If flat, POC is just the price
        if min_p == max_p:
            return min_p, min_p, min_p

        bins = np.arange(min_p, max_p + self.tick_size, self.tick_size)

        # Digitize prices into bins
        inds = np.digitize(prices, bins) - 1

        # Sum volume per bin
        volume_profile = np.zeros(len(bins))
        for i in range(len(prices)):
            idx = min(inds[i], len(volume_profile)-1)
            volume_profile[idx] += volumes[i]

        # POC is price bin with max volume
        poc_idx = np.argmax(volume_profile)
        poc = bins[poc_idx]

        # Calculate Value Area (capturing 70% of total volume)
        total_vol = np.sum(volume_profile)
        target_vol = total_vol * self.value_area_pct

        accum_vol = volume_profile[poc_idx]
        upper_idx = poc_idx
        lower_idx = poc_idx

        # Expand up and down from POC until 70% target reached
        while accum_vol < target_vol:
            up_vol = volume_profile[upper_idx + 1] if upper_idx + 1 < len(volume_profile) else 0
            dn_vol = volume_profile[lower_idx - 1] if lower_idx - 1 >= 0 else 0

            if up_vol == 0 and dn_vol == 0:
                break

            if up_vol > dn_vol:
                upper_idx += 1
                accum_vol += up_vol
            elif dn_vol > up_vol:
                lower_idx -= 1
                accum_vol += dn_vol
            else:
                # Tie: expand both if possible
                upper_idx = min(upper_idx + 1, len(volume_profile) - 1)
                lower_idx = max(lower_idx - 1, 0)
                accum_vol += (up_vol + dn_vol)

        vah = bins[upper_idx]
        val = bins[lower_idx]

        return float(poc), float(vah), float(val)

    def evaluate_structure(self, df_15m: pd.DataFrame) -> Dict[str, any]:
        """
        Takes the trailing 24h dataframe to calculate TPO Value constraints
        and returns exactly what 'Structure/Regime' we are in mathematically.
        """
        if len(df_15m) < 10:
            return {"ready": False}

        poc, vah, val = self._calculate_tpo_profile(df_15m)
        last_price = df_15m['close'].iloc[-1]

        # Structural assessment
        if np.isnan(poc):
            struct = MarketStructure.UNKNOWN
        elif val <= last_price <= vah:
            struct = MarketStructure.INSIDE_VALUE
        elif last_price > vah:
            struct = MarketStructure.BREAKOUT if df_15m['volume'].iloc[-1] > df_15m['volume'].mean() else MarketStructure.GAP_IMBALANCE
        else:
            # Below VAL
            struct = MarketStructure.BREAKOUT if df_15m['volume'].iloc[-1] > df_15m['volume'].mean() else MarketStructure.GAP_IMBALANCE

        # Generate stark truth matrix (Quantitative signals)
        return {
            "ready": True,
            "last_price": last_price,
            "tpo_poc": poc,
            "tpo_vah": vah,
            "tpo_val": val,
            "structure": struct.value,
            # Execute limits natively here
            "actionable_signal": self._get_actionable_signal(last_price, poc, vah, val, struct)
        }

    def _get_actionable_signal(self, last_price: float, poc: float, vah: float, val: float, struct: MarketStructure) -> str:
        """
        Decodes the structural matrix into a strict directional mandate.
        The LLM Agent only needs to read this output ("LONG", "SHORT", "HOLD") + News.
        """
        if struct == MarketStructure.INSIDE_VALUE:
            # Mean reversion matrix: sell highs, buy lows, target POC
            if last_price >= vah - (self.tick_size * 4):
                return "SHORT_VAH_REJECT"
            elif last_price <= val + (self.tick_size * 4):
                return "LONG_VAL_BOUNCE"

        elif struct == MarketStructure.BREAKOUT:
            if last_price > vah:
                return "LONG_MOMENTUM"
            elif last_price < val:
                return "SHORT_MOMENTUM"

        elif struct == MarketStructure.GAP_IMBALANCE:
            # Gap pulls towards POC
            if last_price > vah:
                return "SHORT_GAP_FILL"
            elif last_price < val:
                return "LONG_GAP_FILL"

        return "HOLD"
