"""
JARVIS TRADER — Options Spread Signal Generator (Phase 5.2)
==========================================================
Identifies defined-risk vertical spread setups (Credit/Debit)
based on underlying trend and Greeks (Delta/IV).
"""

import logging
from typing import Dict, List

from data.options_chain_live import OptionStrike

logger = logging.getLogger("jarvis_trader.analysis.options_signals")

class OptionsSpreadSignals:
    def __init__(self, min_credit: float = 0.50, target_delta: float = 0.30):
        self.min_credit = min_credit
        self.target_delta = target_delta

    def find_bull_put_spreads(self, chain: List[OptionStrike], spread_width: float = 5.0) -> List[Dict]:
        """
        Find Bull Put Credit Spreads (Bullish / Mean-Rev setup).
        """
        puts = [s for s in chain if s.right == 'P']
        if not puts:
            return []

        spreads = []
        for short_put in puts:
            # Look for target delta (e.g. 30 delta)
            if 0.20 <= abs(short_put.delta) <= 0.40:
                # Find the long put (spread_width points below)
                long_strike = short_put.strike - spread_width
                long_put = next((p for p in puts if p.strike == long_strike), None)

                if long_put:
                    net_credit = short_put.mid - long_put.mid
                    if net_credit >= self.min_credit:
                        spreads.append({
                            "type": "BULL_PUT_SPREAD",
                            "short_strike": short_put.strike,
                            "long_strike": long_put.strike,
                            "net_credit": net_credit,
                            "max_risk": spread_width - net_credit,
                            "delta": short_put.delta + long_put.delta,
                            "expiry": short_put.expiry
                        })

        return sorted(spreads, key=lambda x: x["net_credit"], reverse=True)

    def find_bear_call_spreads(self, chain: List[OptionStrike], spread_width: float = 5.0) -> List[Dict]:
        """
        Find Bear Call Credit Spreads (Bearish setup).
        """
        calls = [s for s in chain if s.right == 'C']
        if not calls:
            return []

        spreads = []
        for short_call in calls:
            if 0.20 <= abs(short_call.delta) <= 0.40:
                long_strike = short_call.strike + spread_width
                long_call = next((c for c in calls if c.strike == long_strike), None)

                if long_call:
                    net_credit = short_call.mid - long_call.mid
                    if net_credit >= self.min_credit:
                        spreads.append({
                            "type": "BEAR_CALL_SPREAD",
                            "short_strike": short_call.strike,
                            "long_strike": long_call.strike,
                            "net_credit": net_credit,
                            "max_risk": spread_width - net_credit,
                            "delta": short_call.delta + long_call.delta,
                            "expiry": short_call.expiry
                        })

        return sorted(spreads, key=lambda x: x["net_credit"], reverse=True)
