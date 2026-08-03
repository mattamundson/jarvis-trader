"""
mes_level_monitor.py

Watches MES/ES for actionable intraday structure:
- Pullback long zone
- Breakout long level
- Chop/no-trade detection

This is a suggestion/monitoring module only.
It does not place trades and does not bypass safety layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LevelMonitorConfig:
    symbol: str = "MES"
    pullback_low: float = 7615.0
    pullback_high: float = 7625.0
    breakout_level: float = 7635.0
    chop_threshold: float = 3.5
    min_candles: int = 1


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_: float
    high: float
    low: float
    close_: float
    volume: float


@dataclass(frozen=True)
class LevelSignal:
    direction: str
    confidence: float
    price: float
    reason: str


class MesLevelMonitor:
    def __init__(self, config: Optional[LevelMonitorConfig] = None) -> None:
        self.config = config or LevelMonitorConfig()

    def evaluate(self, candles: Iterable[Candle]) -> Optional[LevelSignal]:
        recent = list(candles)
        if len(recent) < self.config.min_candles:
            logger.debug("Not enough candles: %s", len(recent))
            return None

        last = recent[-1]
        price = last.close_
        recent_high = max(c.high for c in recent)
        recent_low = min(c.low for c in recent)
        recent_range = recent_high - recent_low

        if recent_range <= self.config.chop_threshold:
            logger.info("MES in chop; recent range=%s", recent_range)
            return None

        if self.config.pullback_low <= price <= self.config.pullback_high:
            confidence = 0.65 if last.close_ >= last.open_ else 0.55
            return LevelSignal(
                direction="long",
                confidence=confidence,
                price=float(price),
                reason="pullback_long_zone",
            )

        if price > self.config.breakout_level:
            confidence = 0.7 if last.volume > 0 else 0.6
            return LevelSignal(
                direction="long",
                confidence=confidence,
                price=float(price),
                reason="breakout_above_level",
            )

        logger.debug("No level signal at %s", price)
        return None
