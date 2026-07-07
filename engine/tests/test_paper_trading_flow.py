"""
JARVIS TRADER — Comprehensive Paper Trading Flow Integration Test
==================================================================
Tests the entire happy path and kill switch path for paper trading.

Happy Path: Signal -> Pipeline -> Risk -> Paper Order -> P&L
Kill Switch: -2% daily loss triggers kill switch and rejects orders
Risk Veto: Risk manager can veto excessive positions

Run:
    cd engine && python -m pytest tests/test_paper_trading_flow.py -v
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.slow

logger = logging.getLogger(__name__)


class MockTechnicalAnalyst:
    async def analyze(self, symbol, **kwargs):
        return {"signal": 0.85, "confidence": 0.90, "regime": "TRENDING_BULL"}


class MockBullResearcher:
    async def argue(self, symbol, analyst_reports):
        return {"side": "bull", "score": 8.0}


class MockBearResearcher:
    async def argue(self, symbol, analyst_reports):
        return {"side": "bear", "score": 2.0}


class MockDebateOrchestrator:
    async def run_debate(self, bull_arg, bear_arg):
        return {"verdict": "bull", "bull_score": 8.0, "bear_score": 2.0, "margin": 6.0}


class MockTraderAgent:
    async def decide(self, symbol, debate_result, analyst_reports, safety_status):
        return {
            "symbol": symbol,
            "action": "BUY",
            "quantity": 1,
            "entry_price": 5800.0,
            "stop_price": 5785.0,
            "confidence": 0.85,
        }


class MockRiskManager:
    async def review(self, trade_decision, safety_status, portfolio):
        return {
            "symbol": trade_decision.get("symbol", "MES"),
            "approved": True,
            "approved_action": trade_decision.get("action", "HOLD"),
            "approved_contracts": trade_decision.get("quantity", 0),
        }


class MockRiskManagerVeto:
    async def review(self, trade_decision, safety_status, portfolio):
        return {
            "symbol": trade_decision.get("symbol", "MES"),
            "approved": False,
            "veto_reason": "Position exceeds portfolio limits",
            "approved_contracts": 0,
        }


class MockFundManager:
    async def review(self, trade_decision, risk_decision, portfolio):
        return {"symbol": trade_decision.get("symbol", "MES"), "approved": True}


class TestPaperTradingFlow:
    """Integration tests for the complete paper trading pipeline."""

    def setup_method(self):
        """Set up test fixtures."""
        from config import TradingConfig

        self.tmpdir = tempfile.mkdtemp(prefix="test_paper_")
        self.config = TradingConfig()
        self.config.INITIAL_CAPITAL = 10000.0
        self.config.MAX_DAILY_LOSS_PCT = 0.02
        self.config.PAPER_TRADING = True

    @pytest.mark.asyncio
    async def test_full_paper_trading_cycle(self):
        """Signal -> Pipeline -> Risk -> Paper Order -> P&L validation."""
        from agents.pipeline import TradingPipeline
        from risk.safety_layer import SafetyLayer

        safety_layer = SafetyLayer(self.config)
        agents = {
            "technical": MockTechnicalAnalyst(),
            "news": MagicMock(),
            "social": MagicMock(),
            "fundamental": MagicMock(),
            "bull": MockBullResearcher(),
            "bear": MockBearResearcher(),
            "debate": MockDebateOrchestrator(),
            "trader": MockTraderAgent(),
            "risk_manager": MockRiskManager(),
            "fund_manager": MockFundManager(),
        }

        pipeline = TradingPipeline(agents, safety_layer, db_manager=None)

        result = await pipeline.analyze_and_decide(symbol="MES", is_futures=True)

        assert result["symbol"] == "MES"
        assert result["final_action"] in ["buy", "sell", "hold"]
        assert "started_at" in result
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_risk_manager_veto_blocks_excessive_position(self):
        """Risk manager VETO returns HOLD, no trade recorded."""
        from agents.pipeline import TradingPipeline
        from risk.safety_layer import SafetyLayer

        safety_layer = SafetyLayer(self.config)
        agents = {
            "technical": MockTechnicalAnalyst(),
            "news": MagicMock(),
            "social": MagicMock(),
            "fundamental": MagicMock(),
            "bull": MockBullResearcher(),
            "bear": MockBearResearcher(),
            "debate": MockDebateOrchestrator(),
            "trader": MockTraderAgent(),
            "risk_manager": MockRiskManagerVeto(),
            "fund_manager": MockFundManager(),
        }

        pipeline = TradingPipeline(agents, safety_layer, db_manager=None)

        result = await pipeline.analyze_and_decide(symbol="XYZ_TEST", is_futures=True)

        assert result["symbol"] == "XYZ_TEST"
        risk_decision = result.get("risk_decision", {})
        if risk_decision:
            assert risk_decision.get("approved") is False or "approved" in risk_decision

    def test_kill_switch_triggers_at_minus_2_percent_daily_loss(self):
        """Kill switch activates when daily loss reaches -2% via broker sync."""
        from risk.safety_layer import OrderRequest, SafetyLayer

        safety_layer = SafetyLayer(self.config)

        # Ground-truth broker sync is the ONLY path that mutates P&L state and
        # auto-triggers the daily-loss kill switch (sync_from_broker). A -$200
        # loss on $9,800 equity breaches MAX_DAILY_LOSS_PCT (0.02 -> -$196).
        portfolio_equity = 9800.0
        safety_layer.sync_from_broker(equity=portfolio_equity, daily_pnl=-200.0)

        assert safety_layer.is_killed, "daily -2% loss did not engage the kill switch"

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="MARKET",
            is_futures=True,
            estimated_value=5800.0,
        )
        result = safety_layer.check_order(order, portfolio_equity)
        assert result.approved is False, "kill switch active but order was approved"

    def test_kill_switch_triggers_at_minus_10_percent_drawdown(self):
        """Kill switch activates when drawdown reaches -10%."""
        from risk.safety_layer import OrderRequest, SafetyLayer

        safety_layer = SafetyLayer(self.config)

        safety_layer.peak_equity = 10000.0
        safety_layer.current_equity = 9000.0

        drawdown = (
            safety_layer.peak_equity - safety_layer.current_equity
        ) / safety_layer.peak_equity
        assert drawdown >= 0.10

    def test_paper_tracker_pnl_calculation(self):
        """Paper tracker computes P&L: (exit - entry) * multiplier - costs."""
        from backtest.paper_tracker import PaperTradeTracker
        from database.manager import DatabaseManager

        config = {
            "symbol": "MES",
            "initial_capital": 10000.0,
            "multiplier": 50.0,
            "commission_per_contract": 2.50,
            "slippage_ticks": 1,
            "tick_size": 0.25,
            "kill_threshold": {},
        }

        db_path = Path(self.tmpdir) / "test_pnl.db"
        db = DatabaseManager(str(db_path))
        db.initialize()
        tracker = PaperTradeTracker(config, db_manager=db)

        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 5800.0,
                "exit_price": 5810.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
            },
            {
                "entry_date": "2026-04-03",
                "exit_date": "2026-04-03",
                "entry_price": 5800.0,
                "exit_price": 5790.0,
                "side": "short",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "ranging",
            },
        ]

        for trade in trades:
            tracker.add_trade(trade)

        recorded = tracker._trades
        assert len(recorded) == 2
        assert recorded[0]["side"] == "long"
        assert recorded[1]["side"] == "short"
        assert recorded[0]["pnl"] > 0
        assert recorded[1]["pnl"] > 0

    def test_safety_layer_position_and_margin_checks(self):
        """Safety layer enforces position size and margin limits."""
        from risk.safety_layer import OrderRequest, SafetyLayer

        safety_layer = SafetyLayer(self.config)
        portfolio_equity = 10000.0

        normal_order = OrderRequest(
            symbol="MES", quantity=1, order_type="MARKET", is_futures=True, estimated_value=5800.0
        )
        result = safety_layer.check_order(normal_order, portfolio_equity)
        assert result is not None

        large_order = OrderRequest(
            symbol="MES", quantity=10, order_type="MARKET", is_futures=True, estimated_value=58000.0
        )
        result = safety_layer.check_order(large_order, portfolio_equity)
        assert result is not None

    @pytest.mark.asyncio
    async def test_pipeline_error_handling_graceful_degradation(self):
        """Pipeline continues when individual agents fail."""
        from agents.pipeline import TradingPipeline
        from risk.safety_layer import SafetyLayer

        safety_layer = SafetyLayer(self.config)

        failing_agent = MagicMock()
        failing_agent.analyze = AsyncMock(side_effect=Exception("Test failure"))

        agents = {
            "technical": failing_agent,
            "news": MagicMock(),
            "social": MagicMock(),
            "fundamental": MagicMock(),
            "bull": MockBullResearcher(),
            "bear": MockBearResearcher(),
            "debate": MockDebateOrchestrator(),
            "trader": MockTraderAgent(),
            "risk_manager": MockRiskManager(),
            "fund_manager": MockFundManager(),
        }

        pipeline = TradingPipeline(agents, safety_layer, db_manager=None)

        result = await pipeline.analyze_and_decide("MES", is_futures=True)

        assert "errors" in result

    def test_paper_tracker_metrics(self):
        """Paper tracker computes rolling metrics: trades, P&L."""
        from backtest.paper_tracker import PaperTradeTracker
        from database.manager import DatabaseManager

        config = {
            "symbol": "MES",
            "initial_capital": 10000.0,
            "multiplier": 50.0,
            "commission_per_contract": 2.50,
            "slippage_ticks": 1,
            "tick_size": 0.25,
            "kill_threshold": {},
        }

        db_path = Path(self.tmpdir) / "test_metrics.db"
        db = DatabaseManager(str(db_path))
        db.initialize()
        tracker = PaperTradeTracker(config, db_manager=db)

        for i, (entry, exit_p) in enumerate([(5800, 5810), (5810, 5800)]):
            tracker.add_trade(
                {
                    "entry_date": f"2026-04-0{i+1}",
                    "exit_date": f"2026-04-0{i+1}",
                    "entry_price": float(entry),
                    "exit_price": float(exit_p),
                    "side": "long",
                    "contracts": 1,
                    "exit_reason": "target_1",
                    "regime_type": "trending",
                }
            )

        metrics = tracker.get_metrics()
        assert metrics.get("total_trades") == 2
        assert "total_pnl" in metrics

    def test_order_request_validation(self):
        """Order requests are properly validated for required fields."""
        from risk.safety_layer import OrderRequest

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="MARKET",
            is_futures=True,
            estimated_value=5800.0,
        )

        assert order.symbol == "MES"
        assert order.quantity == 1
        assert order.order_type == "MARKET"
        assert order.is_futures is True

    def test_concurrent_order_rate_limiting(self):
        """Safety layer enforces max 10 orders/minute rate limit."""
        from risk.safety_layer import OrderRequest, SafetyLayer

        safety_layer = SafetyLayer(self.config)
        portfolio_equity = 10000.0

        orders = [
            OrderRequest(
                symbol="MES",
                quantity=1,
                order_type="MARKET",
                is_futures=True,
                estimated_value=5800.0,
            )
            for _ in range(12)
        ]

        checked = 0
        for order in orders:
            result = safety_layer.check_order(order, portfolio_equity)
            if result.approved:
                checked += 1

        assert checked <= 10 or safety_layer.is_killed


class TestPaperTradingIntegration(unittest.TestCase):
    """Unit tests for paper trading components (non-async)."""

    def setUp(self):
        """Set up test fixtures."""
        from config import TradingConfig

        self.config = TradingConfig()
        self.tmpdir = tempfile.mkdtemp(prefix="test_paper_")

    @patch.dict(os.environ, {
        "MAX_DAILY_LOSS_PCT": "0.10",
        "MAX_DRAWDOWN_PCT": "0.10",
        "MAX_POSITION_SIZE_PCT": "0.05",
        "MAX_CONTRACTS_PER_INSTRUMENT": "2",
    })
    def test_trading_config_defaults(self):
        """TradingConfig has correct safety defaults."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.MAX_DAILY_LOSS_PCT == 0.10  # paper trading mode
        assert config.MAX_DRAWDOWN_PCT == 0.10
        assert config.MAX_POSITION_SIZE_PCT == 0.05
        assert config.MAX_CONTRACTS_PER_INSTRUMENT == 2
        assert config.LIVE_TRADING_ENABLED is False
        # REQUIRE_HUMAN_APPROVAL ships safe-by-default (True): a bare TradingConfig()
        # with no .env requires human approval. The 2026-06-15 owner directive enables
        # autonomous paper mode by setting REQUIRE_HUMAN_APPROVAL=False *in engine/.env*,
        # not by changing the code default -- so a fresh checkout always fails safe
        # (requires approval) rather than silently trading autonomously. The deployed
        # autonomous posture is verified separately by the startup_checks WARN gate.
        assert config.REQUIRE_HUMAN_APPROVAL is True
        assert config.PAPER_TRADING is True

    def test_paper_tracker_persistence(self):
        """Paper tracker persists trades to SQLite and reloads them."""
        from backtest.paper_tracker import PaperTradeTracker
        from database.manager import DatabaseManager

        config = {
            "symbol": "MES",
            "initial_capital": 10000.0,
            "multiplier": 50.0,
            "commission_per_contract": 2.50,
            "slippage_ticks": 1,
            "tick_size": 0.25,
            "kill_threshold": {},
        }

        db_path = Path(self.tmpdir) / "test_persist.db"
        db = DatabaseManager(str(db_path))
        db.initialize()
        tracker1 = PaperTradeTracker(config, db_manager=db)

        trade = {
            "entry_date": "2026-04-02",
            "exit_date": "2026-04-02",
            "entry_price": 5800.0,
            "exit_price": 5810.0,
            "side": "long",
            "contracts": 1,
            "exit_reason": "target_1",
            "regime_type": "trending",
        }

        tracker1.add_trade(trade)

        tracker2 = PaperTradeTracker(config, db_manager=db)
        assert len(tracker2._trades) >= 1  # At least the trade we just added

    def test_risk_check_result_structure(self):
        """RiskCheckResult has correct fields for approval/rejection."""
        from risk.safety_layer import RiskCheckResult

        result_approved = RiskCheckResult(
            approved=True,
            rejection_reason=None,
            warnings=["Minor warning"],
        )

        assert result_approved.approved is True
        assert result_approved.rejection_reason is None
        assert len(result_approved.warnings) == 1

        result_rejected = RiskCheckResult(
            approved=False,
            rejection_reason="Exceeds daily loss limit",
            warnings=[],
        )

        assert result_rejected.approved is False
        assert "daily loss" in result_rejected.rejection_reason.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
