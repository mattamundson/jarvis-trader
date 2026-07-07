"""
JARVIS TRADER — Harmonic Vision Agent
======================================
Detects Fibonacci XABCD patterns (Gartley, Bat, Butterfly, etc.)
Identifies high-probability reversal zones.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List

from analysis.harmonics_engine import HarmonicEngine

logger = logging.getLogger("jarvis_trader.agents.harmonic_agent")

@dataclass
class HarmonicReport:
    symbol: str
    timestamp: datetime
    patterns: List[dict]
    signal: float # -1.0 to 1.0
    confidence: float
    summary: str
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "patterns": self.patterns,
            "signal": self.signal,
            "confidence": self.confidence,
            "summary": self.summary,
            "reasoning": self.reasoning,
        }

class HarmonicAgent:
    """
    Agent that utilizes Fibonacci geometry to detect harmonic patterns.
    """

    def __init__(self, data_manager):
        self._data = data_manager
        self._engine = HarmonicEngine()

    async def analyze(
        self,
        symbol: str,
        timeframe: str = "15m",
        is_futures: bool = False,
        **kwargs
    ) -> HarmonicReport:
        """
        Scan for harmonic patterns on the given symbol.
        """
        # Fetch data (need more bars for swing detection)
        df = await self._data.get_bars(
            symbol, lookback_days=10, timeframe=timeframe, is_futures=is_futures
        )

        if df.empty or len(df) < 100:
            return self._empty_report(symbol)

        # Detect patterns
        patterns = await asyncio.to_thread(self._engine.detect_patterns, df)

        if not patterns:
            return self._empty_report(symbol)

        # Focus on the most recent pattern
        # Determine if it's "active" (latest swing is D)
        last_swing_idx = df.index[-1]
        active_patterns = [p for p in patterns if (last_swing_idx - p.points[-1][0]) < 10]

        if not active_patterns:
            return self._empty_report(symbol, "Patterns detected but none active near current price.")

        best_pattern = active_patterns[-1]

        # Bullish patterns (Gartley/Bat/Butterfly/Crab) signal a buy at D
        signal = 0.7 if best_pattern.type == "bullish" else -0.7
        confidence = best_pattern.confidence

        pattern_list = []
        for p in active_patterns:
            pattern_list.append({
                "name": p.name,
                "type": p.type,
                "age_bars": int(last_swing_idx - p.points[-1][0])
            })

        summary = f"Detected active {best_pattern.type} {best_pattern.name} pattern."
        reasoning = (
            f"Pattern points completion at D: ${best_pattern.points[-1][1]:.2f}. "
            f"Fibonacci XD/XA ratio: {best_pattern.ratios.get('XD/XA', 0):.3f}."
        )

        return HarmonicReport(
            symbol=symbol,
            timestamp=datetime.now(),
            patterns=pattern_list,
            signal=signal,
            confidence=confidence,
            summary=summary,
            reasoning=reasoning
        )

    def _empty_report(self, symbol: str, reason: str = "No active harmonic patterns detected.") -> HarmonicReport:
        return HarmonicReport(
            symbol=symbol,
            timestamp=datetime.now(),
            patterns=[],
            signal=0,
            confidence=0,
            summary=reason,
            reasoning="ZigZag swing analysis completed, no XABCD matches found."
        )
