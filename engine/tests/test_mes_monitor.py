"""
Tests for engine/monitors/mes_* modules.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from engine.monitors.mes_level_monitor import Candle, LevelMonitorConfig, LevelSignal, MesLevelMonitor
from engine.monitors.mes_regime_filter import MesRegimeFilter, RegimeConfig, RegimeInputs, RegimeResult
from engine.monitors.mes_monitor_orchestrator import MesMonitorOrchestrator, MesMonitorVerdict
from engine.monitors.mes_trade_logger import MesTradeLogger, MonitorSuggestion


def make_candle(close_: float, open_: float = 7618.0, high: float = 7628.0, low: float = 7612.0, volume: float = 1000.0) -> Candle:
    return Candle(symbol="MES", timeframe="5min", open_=open_, high=high, low=low, close_=close_, volume=volume)


class TestMesLevelMonitor:
    def test_pullback_long_zone(self):
        monitor = MesLevelMonitor()
        signal = monitor.evaluate([make_candle(close_=7620.0)])
        assert signal is not None
        assert signal.direction == "long"
        assert signal.reason == "pullback_long_zone"
        assert 7615.0 <= signal.price <= 7625.0

    def test_breakout_long(self):
        monitor = MesLevelMonitor()
        signal = monitor.evaluate([make_candle(close_=7640.0)])
        assert signal is not None
        assert signal.direction == "long"
        assert signal.reason == "breakout_above_level"
        assert signal.price == 7640.0

    def test_chop_zone_returns_none(self):
        monitor = MesLevelMonitor()
        signal = monitor.evaluate([make_candle(close_=7634.5)])
        assert signal is None


class TestMesRegimeFilter:
    def test_blocks_daily_loss(self):
        filt = MesRegimeFilter()
        result = filt.check(RegimeInputs(current_daily_loss=-375.0))
        assert result.allow_trade is False
        assert result.reason == "daily_loss_limit_reached"

    def test_blocks_vix_hard_stop(self):
        filt = MesRegimeFilter()
        result = filt.check(RegimeInputs(vix=19.0))
        assert result.allow_trade is False
        assert result.reason == "vix_hard_stop"

    def test_blocks_news_blackout(self):
        filt = MesRegimeFilter()
        result = filt.check(RegimeInputs(minutes_to_news=15.0))
        assert result.allow_trade is False
        assert result.reason == "news_blackout"

    def test_scales_risk_above_ideal_vix(self):
        filt = MesRegimeFilter()
        result = filt.check(RegimeInputs(vix=16.5))
        assert result.allow_trade is True
        assert result.suggested_risk_scale == 0.5


class TestMesMonitorOrchestrator:
    def test_no_signal_when_no_candles(self):
        orch = MesMonitorOrchestrator()
        verdict = orch.run([], RegimeInputs())
        assert verdict.should_alert is False
        assert verdict.reason == "no_signal"

    def test_no_alert_when_regime_blocks(self):
        orch = MesMonitorOrchestrator()
        candles = [make_candle(7620.0)]
        verdict = orch.run(candles, RegimeInputs(vix=19.0))
        assert verdict.should_alert is False
        assert verdict.regime_reason == "vix_hard_stop"

    def test_alert_when_regime_clear(self, tmp_path: Path):
        csv_path = tmp_path / "suggestions.csv"
        orch = MesMonitorOrchestrator(suggestion_csv=csv_path)
        candles = [make_candle(7620.0)]
        verdict = orch.run(candles, RegimeInputs(vix=14.0))
        assert verdict.should_alert is True
        assert csv_path.exists()
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["direction"] == "long"
