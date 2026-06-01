"""
JARVIS TRADER — Base Strategy ABC
Every strategy (hand-coded or LLM-generated) must implement this interface.
Bridges autotrade's strategy-as-code pattern with JARVIS's existing Backtester.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple

import pandas as pd


class BaseStrategy(ABC):
    """Abstract base class for all JARVIS trading strategies."""

    name: str = ""
    description: str = ""
    version: str = "1.0"
    keep: bool = False
    symbol: str = ""
    timeframe: str = "1h"

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add signal columns to the DataFrame.
        Must add at minimum: 'signal' column (1=long, -1=short, 0=flat).
        May also add: 'stop_price', 'target_1', 'target_2', 'regime', 'bias'.
        """
        ...

    @abstractmethod
    def get_stop_atr_mult(self) -> float:
        """ATR multiplier for stop loss."""
        ...

    @abstractmethod
    def get_target_atr_mults(self) -> Tuple[float, float, float]:
        """ATR multipliers for (target_1, target_2, target_3)."""
        ...

    def get_params(self) -> dict:
        """Return strategy parameters as a dict for logging."""
        return {}

    def metadata(self) -> dict:
        """Strategy metadata for registry and logging."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "keep": self.keep,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": self.get_params(),
        }

    def __repr__(self) -> str:
        status = "KEEP" if self.keep else "EVAL"
        return f"<{self.__class__.__name__} [{status}] {self.name} v{self.version}>"
