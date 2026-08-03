"""
mes_regime_filter.py

VIX-based regime filter for MES monitor.
Blocks or scales suggestions based on volatility and trade permissions.

This does not override safety_layer or risk configs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegimeConfig:
    vix_hard_stop: float = 18.0
    vix_ideal_max: float = 15.0
    news_blackout_minutes: int = 60
    max_risk_per_trade: float = 125.0
    daily_loss_limit: float = 375.0


@dataclass(frozen=True)
class RegimeInputs:
    vix: Optional[float] = None
    minutes_to_news: Optional[float] = None
    current_daily_loss: Optional[float] = None


@dataclass(frozen=True)
class RegimeResult:
    allow_trade: bool
    reason: str
    suggested_risk_scale: float = 1.0


class MesRegimeFilter:
    def __init__(self, config: Optional[RegimeConfig] = None) -> None:
        self.config = config or RegimeConfig()

    def check(self, inputs: RegimeInputs) -> RegimeResult:
        if inputs.current_daily_loss is not None and abs(inputs.current_daily_loss) >= self.config.daily_loss_limit:
            return RegimeResult(allow_trade=False, reason="daily_loss_limit_reached")

        if inputs.vix is not None and inputs.vix >= self.config.vix_hard_stop:
            return RegimeResult(allow_trade=False, reason="vix_hard_stop")

        if inputs.minutes_to_news is not None and 0 <= inputs.minutes_to_news <= self.config.news_blackout_minutes:
            return RegimeResult(allow_trade=False, reason="news_blackout")

        scale = 1.0
        if inputs.vix is not None and inputs.vix > self.config.vix_ideal_max:
            scale = 0.5

        return RegimeResult(allow_trade=True, reason="regime_clear", suggested_risk_scale=scale)
