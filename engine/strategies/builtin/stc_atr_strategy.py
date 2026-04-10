"""
JARVIS TRADER — STC+ATR Built-in Strategy Wrapper
Wraps the proven signals.py 5-layer framework as a BaseStrategy subclass.
This is the production strategy — keep=True, pre-approved.
"""

from __future__ import annotations

from typing import Tuple

import pandas as pd

from strategies.base_strategy import BaseStrategy


class STCATRStrategy(BaseStrategy):
    """
    Wraps JARVIS's proven STC+ATR 5-layer signal framework.
    Uses per-instrument optimized parameters from signals.py INSTRUMENT_PARAMS.
    """

    name = "stc_atr_v1"
    description = "STC oscillator + ATR stops + 5-layer regime filter (production)"
    version = "1.0"
    keep = True  # Pre-approved, proven WFE >= 0.57

    def __init__(self, symbol: str = "MCL", timeframe: str = "1h") -> None:
        self.symbol = symbol
        self.timeframe = timeframe

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Delegate to the proven signals.py generate_signals function."""
        from backtest.signals import generate_signals

        return generate_signals(df, symbol=self.symbol)

    def get_stop_atr_mult(self) -> float:
        from backtest.signals import INSTRUMENT_PARAMS

        params = INSTRUMENT_PARAMS.get(self.symbol)
        if params:
            return params[2]  # atr_stop_mult
        return 0.70  # default

    def get_target_atr_mults(self) -> Tuple[float, float, float]:
        from backtest.signals import INSTRUMENT_PARAMS

        params = INSTRUMENT_PARAMS.get(self.symbol)
        if params:
            return (params[3], params[4], params[5])  # t1, t2, t3
        return (1.00, 1.80, 2.618)  # defaults

    def get_params(self) -> dict:
        from backtest.signals import INSTRUMENT_PARAMS

        params = INSTRUMENT_PARAMS.get(self.symbol)
        if params:
            return {
                "stc_oversold": params[0],
                "stc_overbought": params[1],
                "atr_stop_mult": params[2],
                "atr_t1_mult": params[3],
                "atr_t2_mult": params[4],
                "atr_t3_mult": params[5],
                "regime_filter": params[6],
            }
        return {}
