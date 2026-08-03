"""
mes_monitor_orchestrator.py

Main entrypoint for the MES 24x7 monitor.
Wires level monitor + regime filter + alert dispatch + trade logging.

This module only produces suggestions. It does not place orders.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from engine.monitors.mes_level_monitor import MesLevelMonitor, LevelMonitorConfig, Candle, LevelSignal
from engine.monitors.mes_regime_filter import MesRegimeFilter, RegimeConfig, RegimeInputs, RegimeResult
from engine.monitors.mes_alert_dispatcher import MesAlertDispatcher
from engine.monitors.mes_trade_logger import MesTradeLogger, MonitorSuggestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MesMonitorVerdict:
    should_alert: bool
    direction: Optional[str]
    confidence: float
    price: float
    reason: str
    regime_reason: str
    risk_scale: float


class MesMonitorOrchestrator:
    def __init__(
        self,
        level_config: Optional[LevelMonitorConfig] = None,
        regime_config: Optional[RegimeConfig] = None,
        alert_dir: Path = Path("docs/morning_briefs"),
        suggestion_csv: Path = Path("data/mes_monitor_suggestions.csv"),
    ) -> None:
        self.level_monitor = MesLevelMonitor(level_config)
        self.regime_filter = MesRegimeFilter(regime_config)
        self.dispatcher = MesAlertDispatcher(alert_dir)
        self.logger = MesTradeLogger(suggestion_csv)

    def run(self, candles: Iterable[Candle], regime_inputs: RegimeInputs) -> MesMonitorVerdict:
        signal: Optional[LevelSignal] = self.level_monitor.evaluate(candles)
        if signal is None:
            return MesMonitorVerdict(
                should_alert=False,
                direction=None,
                confidence=0.0,
                price=0.0,
                reason="no_signal",
                regime_reason="not_evaluated",
                risk_scale=1.0,
            )

        regime: RegimeResult = self.regime_filter.check(regime_inputs)
        if not regime.allow_trade:
            return MesMonitorVerdict(
                should_alert=False,
                direction=signal.direction,
                confidence=signal.confidence,
                price=signal.price,
                reason=signal.reason,
                regime_reason=regime.reason,
                risk_scale=regime.suggested_risk_scale,
            )

        alert = {
            "symbol": "MES",
            "direction": signal.direction,
            "confidence": signal.confidence * regime.suggested_risk_scale,
            "price": signal.price,
            "reason": signal.reason,
            "regime": regime.reason,
        }
        self.dispatcher.dispatch(alert)
        self.logger.log(
            MonitorSuggestion(
                timestamp=datetime.now(timezone.utc).isoformat(),
                symbol="MES",
                direction=signal.direction,
                confidence=float(signal.confidence),
                price=float(signal.price),
                reason=signal.reason,
                regime_reason=regime.reason,
                risk_scale=float(regime.suggested_risk_scale),
            )
        )

        return MesMonitorVerdict(
            should_alert=True,
            direction=signal.direction,
            confidence=float(signal.confidence),
            price=float(signal.price),
            reason=signal.reason,
            regime_reason=regime.reason,
            risk_scale=float(regime.suggested_risk_scale),
        )
