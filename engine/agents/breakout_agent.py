"""
JARVIS TRADER — Breakout Specialist Agent
=========================================
Specializes in Volume Profile breakouts and high-volume node (HVN) analysis.
Identifies momentum entries after consolidation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from analysis.breakout_engine import VolumeProfileEngine

logger = logging.getLogger("jarvis_trader.agents.breakout_agent")

@dataclass
class BreakoutReport:
    symbol: str
    timestamp: datetime
    status: str  # "breakout", "inside_va", "extended", "none"
    side: str    # "bullish", "bearish", "neutral"
    vah: float
    val: float
    poc: float
    signal: float # -1.0 to 1.0
    confidence: float
    summary: str
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "side": self.side,
            "vah": self.vah,
            "val": self.val,
            "poc": self.poc,
            "signal": self.signal,
            "confidence": self.confidence,
            "summary": self.summary,
            "reasoning": self.reasoning,
        }

class BreakoutAgent:
    """
    Agent that monitors volume profiles for institutional-grade breakouts.
    """

    def __init__(self, data_manager):
        self._data = data_manager
        self._engine = VolumeProfileEngine()

    async def analyze(
        self,
        symbol: str,
        timeframe: str = "15m",
        is_futures: bool = False,
        **kwargs
    ) -> BreakoutReport:
        """
        Perform breakout analysis on the given symbol.
        """
        # Fetch data
        df = await self._data.get_bars(
            symbol, lookback_days=5, timeframe=timeframe, is_futures=is_futures
        )

        if df.empty or len(df) < 50:
            return self._empty_report(symbol)

        # Calculate profile
        profile = await asyncio.to_thread(self._engine.calculate_profile, df)
        if not profile:
            return self._empty_report(symbol)

        # Detect breakout
        decision = self._engine.detect_breakout(df, profile)

        status = decision["status"]
        side = decision["side"]
        current_price = df["close"].iloc[-1]

        signal = 0.0
        confidence = 0.0

        if status == "breakout":
            signal = 0.8 if side == "bullish" else -0.8
            confidence = 0.75
        elif status == "extended":
            signal = 0.4 if side == "bullish" else -0.4
            confidence = 0.5
        elif status == "inside_va":
            # Rejection of VAL for long or VAH for short?
            # For now, stay neutral
            signal = 0.0
            confidence = 0.3

        summary = f"Price at ${current_price:.2f} is {status} ({side}) relative to Value Area."
        reasoning = (
            f"VAH: ${profile['vah']:.2f}, VAL: ${profile['val']:.2f}, POC: ${profile['poc']:.2f}. "
            f"Volume distribution is {int(profile['va_volume_pct']*100)}% concentrated in VA."
        )

        return BreakoutReport(
            symbol=symbol,
            timestamp=datetime.now(),
            status=status,
            side=side,
            vah=profile["vah"],
            val=profile["val"],
            poc=profile["poc"],
            signal=signal,
            confidence=confidence,
            summary=summary,
            reasoning=reasoning
        )

    def _empty_report(self, symbol: str) -> BreakoutReport:
        return BreakoutReport(
            symbol=symbol,
            timestamp=datetime.now(),
            status="none",
            side="neutral",
            vah=0,
            val=0,
            poc=0,
            signal=0,
            confidence=0,
            summary="Insufficient data for breakout analysis.",
            reasoning="Need at least 50 bars of volume data."
        )
