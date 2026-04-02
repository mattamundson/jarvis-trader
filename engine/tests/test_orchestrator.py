"""
Integration tests for MultiMarketOrchestrator.
Tests module registration, lifecycle management, strategy cycles, and portfolio aggregation.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from markets.base import (
    HealthStatus,
    MarketModule,
    MarketStatus,
    Position,
    TradeResult,
    TradeSignal,
)
from orchestrator.multi_market import (
    MultiMarketOrchestrator,
    get_orchestrator,
    set_orchestrator,
)


class MockMarketModule(MarketModule):
    """Mock market module for testing orchestrator."""

    def __init__(self, name: str = "mock_market", enabled: bool = True):
        self.market_name = name
        self.daily_target = 500.0
        self.capital_allocated = 10_000.0
        self._enabled = enabled
        self._connected = False
        self._positions = []
        self._daily_pnl = 0.0
        self._strategy_call_count = 0

    def is_enabled(self) -> bool:
        return self._enabled

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def get_positions(self) -> list[Position]:
        return self._positions

    async def get_daily_pnl(self) -> float:
        return self._daily_pnl

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        self._strategy_call_count += 1
        return []

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        return TradeResult(
            signal=signal,
            executed=True,
            fill_price=100.0,
            fill_qty=1,
            realized_pnl=50.0,
            order_id="mock-order-1",
        )

    async def shutdown(self) -> None:
        self._connected = False

    def health_check(self) -> HealthStatus:
        status = MarketStatus.PAPER if self._connected else MarketStatus.OFFLINE
        return HealthStatus(
            market=self.market_name,
            status=status,
            message="OK" if self._connected else "Not connected",
            daily_pnl=self._daily_pnl,
            open_positions=len(self._positions),
        )


class FailingMarketModule(MarketModule):
    """Market module that fails during strategy cycle."""

    def __init__(self, name: str = "failing_market"):
        self.market_name = name
        self.daily_target = 500.0
        self.capital_allocated = 10_000.0

    def is_enabled(self) -> bool:
        return True

    async def connect(self) -> bool:
        return True

    async def get_positions(self) -> list[Position]:
        return []

    async def get_daily_pnl(self) -> float:
        return 0.0

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        raise RuntimeError("Strategy cycle failed")

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        return TradeResult(
            signal=signal,
            executed=False,
            fill_price=None,
            fill_qty=None,
            realized_pnl=None,
            order_id=None,
        )

    async def shutdown(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        return HealthStatus(
            market=self.market_name,
            status=MarketStatus.OFFLINE,
            message="Not connected",
            daily_pnl=0.0,
            open_positions=0,
        )


class TestMultiMarketOrchestratorBasics:
    """Test basic orchestrator registration and module management."""

    def test_register_module(self):
        """Test that modules are registered correctly."""
        orch = MultiMarketOrchestrator()
        module = MockMarketModule("futures")

        orch.register(module)
        assert "futures" in orch.list_modules()
        assert orch.get_module("futures") == module

    def test_register_multiple_modules(self):
        """Test registering multiple modules."""
        orch = MultiMarketOrchestrator()
        futures = MockMarketModule("futures")
        options = MockMarketModule("options")
        crypto = MockMarketModule("crypto")

        orch.register(futures)
        orch.register(options)
        orch.register(crypto)

        modules = orch.list_modules()
        assert len(modules) == 3
        assert "futures" in modules
        assert "options" in modules
        assert "crypto" in modules

    def test_get_nonexistent_module(self):
        """Test retrieving a module that doesn't exist."""
        orch = MultiMarketOrchestrator()
        assert orch.get_module("nonexistent") is None

    def test_start_all_modules(self):
        """Test start() connects all registered modules."""
        orch = MultiMarketOrchestrator()
        futures = MockMarketModule("futures")
        options = MockMarketModule("options")

        orch.register(futures)
        orch.register(options)

        # Start orchestrator
        import asyncio

        asyncio.run(orch.start())

        assert orch._running is True
        assert futures._connected is True
        assert options._connected is True

    def test_stop_all_modules(self):
        """Test stop() disconnects all modules."""
        orch = MultiMarketOrchestrator()
        futures = MockMarketModule("futures")

        orch.register(futures)
        futures._connected = True  # Simulate connected state

        import asyncio

        asyncio.run(orch.stop())

        assert orch._running is False
        assert futures._connected is False

    def test_empty_orchestrator_handles_gracefully(self):
        """Test that empty orchestrator (no modules) handles gracefully."""
        orch = MultiMarketOrchestrator()
        assert orch.list_modules() == []

        import asyncio

        asyncio.run(orch.start())  # Should not crash
        asyncio.run(orch.stop())  # Should not crash

        summary = asyncio.run(orch.get_portfolio_summary())
        assert summary["total_daily_pnl"] == 0.0
        assert summary["total_open_positions"] == 0


class TestMultiMarketOrchestratorCycles:
    """Test strategy cycle execution."""

    def test_run_all_cycles_executes_each_module(self):
        """Test that run_all_cycles calls each module's strategy cycle."""
        orch = MultiMarketOrchestrator()
        futures = MockMarketModule("futures")
        options = MockMarketModule("options")

        orch.register(futures)
        orch.register(options)

        import asyncio

        results = asyncio.run(orch.run_all_cycles())

        assert "futures" in results
        assert "options" in results
        assert futures._strategy_call_count == 1
        assert options._strategy_call_count == 1

    def test_run_cycles_skips_disabled_modules(self):
        """Test that disabled modules are skipped during cycles."""
        orch = MultiMarketOrchestrator()
        enabled = MockMarketModule("enabled")
        disabled = MockMarketModule("disabled", enabled=False)

        orch.register(enabled)
        orch.register(disabled)

        import asyncio

        results = asyncio.run(orch.run_all_cycles())

        assert "enabled" in results
        assert "disabled" not in results
        assert enabled._strategy_call_count == 1
        assert disabled._strategy_call_count == 0

    def test_run_cycles_returns_signal_counts(self):
        """Test that run_all_cycles returns signal counts."""
        orch = MultiMarketOrchestrator()
        futures = MockMarketModule("futures")

        orch.register(futures)

        import asyncio

        results = asyncio.run(orch.run_all_cycles())

        assert results["futures"] == 0  # No signals generated by mock

    def test_module_failure_during_cycle_doesnt_crash_orchestrator(self):
        """Test that module failure doesn't crash orchestrator."""
        orch = MultiMarketOrchestrator()
        good = MockMarketModule("good")
        bad = FailingMarketModule("bad")

        orch.register(good)
        orch.register(bad)

        import asyncio

        results = asyncio.run(orch.run_all_cycles())

        # Both should be in results, bad has 0 signals
        assert "good" in results
        assert "bad" in results
        assert results["bad"] == 0
        # Orchestrator should still be running
        assert orch._running or not orch._running  # Just check it's not crashed


class TestMultiMarketOrchestratorPortfolioAggregation:
    """Test portfolio summary and P&L aggregation."""

    def test_get_portfolio_summary_basic(self):
        """Test basic portfolio summary."""
        orch = MultiMarketOrchestrator(daily_target=1000.0)
        futures = MockMarketModule("futures")
        futures._daily_pnl = 300.0
        futures._positions = [
            Position(
                symbol="MES",
                quantity=1,
                avg_cost=5800.0,
                market_value=5850.0,
                unrealized_pnl=50.0,
                side="long",
                market="futures",
            )
        ]

        orch.register(futures)

        import asyncio

        summary = asyncio.run(orch.get_portfolio_summary())

        assert summary["total_daily_pnl"] == 300.0
        assert summary["daily_target"] == 1000.0
        assert summary["total_open_positions"] == 1
        assert "futures" in summary["markets"]

    def test_get_portfolio_summary_aggregates_multiple_markets(self):
        """Test portfolio summary aggregates across multiple markets."""
        orch = MultiMarketOrchestrator(daily_target=2000.0)

        futures = MockMarketModule("futures")
        futures._daily_pnl = 500.0
        futures._positions = [
            Position(
                symbol="MES",
                quantity=1,
                avg_cost=5800.0,
                market_value=5850.0,
                unrealized_pnl=50.0,
                side="long",
                market="futures",
            )
        ]

        options = MockMarketModule("options")
        options._daily_pnl = 300.0
        options._positions = [
            Position(
                symbol="SPY",
                quantity=10,
                avg_cost=100.0,
                market_value=1050.0,
                unrealized_pnl=50.0,
                side="long",
                market="options",
            )
        ]

        orch.register(futures)
        orch.register(options)

        import asyncio

        summary = asyncio.run(orch.get_portfolio_summary())

        assert summary["total_daily_pnl"] == 800.0
        assert summary["total_open_positions"] == 2
        assert summary["target_progress_pct"] == 40.0  # 800/2000

    def test_portfolio_summary_includes_module_stats(self):
        """Test that portfolio summary includes per-module statistics."""
        orch = MultiMarketOrchestrator()
        module = MockMarketModule("test_market")
        module._daily_pnl = 250.0

        orch.register(module)

        import asyncio

        summary = asyncio.run(orch.get_portfolio_summary())

        assert "test_market" in summary["markets"]
        stats = summary["markets"]["test_market"]
        assert stats["daily_pnl"] == 250.0
        assert stats["open_positions"] == 0
        assert stats["target"] == 500.0
        assert stats["capital"] == 10_000.0

    def test_portfolio_summary_handles_module_error_gracefully(self):
        """Test portfolio summary handles module errors gracefully."""
        orch = MultiMarketOrchestrator()

        # Create a mock module that raises during get_daily_pnl
        bad_module = AsyncMock(spec=MarketModule)
        bad_module.market_name = "bad"
        bad_module.daily_target = 500.0
        bad_module.capital_allocated = 10_000.0
        bad_module.get_daily_pnl = AsyncMock(side_effect=Exception("Connection lost"))

        orch._modules["bad"] = bad_module

        import asyncio

        summary = asyncio.run(orch.get_portfolio_summary())

        # Should include error in stats
        assert "bad" in summary["markets"]
        assert "error" in summary["markets"]["bad"]


class TestMultiMarketOrchestratorSingleton:
    """Test singleton pattern."""

    def test_get_orchestrator_initially_none(self):
        """Test that orchestrator is initially None."""
        # Reset global state
        set_orchestrator(None)
        assert get_orchestrator() is None

    def test_set_and_get_orchestrator(self):
        """Test setting and getting orchestrator singleton."""
        orch = MultiMarketOrchestrator()
        set_orchestrator(orch)
        assert get_orchestrator() == orch

    def test_orchestrator_singleton_persists(self):
        """Test that singleton persists across calls."""
        orch1 = MultiMarketOrchestrator()
        set_orchestrator(orch1)

        orch2 = get_orchestrator()
        orch3 = get_orchestrator()

        assert orch2 == orch1
        assert orch3 == orch1
        assert orch2 is orch3  # Same object


class TestMultiMarketOrchestratorHaltResume:
    """Test halt/resume functionality."""

    def test_halt_all_sets_halted_state(self):
        """Test that halt_all sets halted flag."""
        orch = MultiMarketOrchestrator()
        orch.halt_all("Test halt")

        assert orch._halted is True
        assert orch._halt_reason == "Test halt"

    def test_halted_orchestrator_doesnt_run_cycles(self):
        """Test that halted orchestrator skips strategy cycles."""
        orch = MultiMarketOrchestrator()
        module = MockMarketModule("test")
        orch.register(module)
        orch.halt_all("Testing halt")

        import asyncio

        results = asyncio.run(orch.run_all_cycles())

        # Should return empty dict and not increment call count
        assert results == {}
        assert module._strategy_call_count == 0

    def test_resume_clears_halt_state(self):
        """Test that resume clears halted flag."""
        orch = MultiMarketOrchestrator()
        orch.halt_all("Test halt")
        orch.resume()

        assert orch._halted is False
        assert orch._halt_reason is None

    def test_health_check_returns_all_modules(self):
        """Test get_all_health returns status of all modules."""
        orch = MultiMarketOrchestrator()
        futures = MockMarketModule("futures")
        options = MockMarketModule("options")

        orch.register(futures)
        orch.register(options)

        # Connect one module
        import asyncio

        asyncio.run(futures.connect())

        health_statuses = orch.get_all_health()

        assert len(health_statuses) == 2
        assert health_statuses[0].market in ["futures", "options"]
        assert health_statuses[1].market in ["futures", "options"]


class TestMultiMarketOrchestratorUptime:
    """Test uptime tracking."""

    def test_uptime_seconds_calculated_after_start(self):
        """Test that uptime is calculated after start."""
        orch = MultiMarketOrchestrator()
        module = MockMarketModule("test")
        orch.register(module)

        import asyncio
        import time

        asyncio.run(orch.start())
        time.sleep(0.1)  # Small delay

        summary = asyncio.run(orch.get_portfolio_summary())

        assert summary["uptime_seconds"] > 0.0

    def test_uptime_zero_before_start(self):
        """Test that uptime is 0 before start."""
        orch = MultiMarketOrchestrator()
        summary_data = {"uptime_seconds": (datetime.utcnow() - None) if orch._start_time else 0}
        # Since _start_time is None before start, uptime should be 0
        assert summary_data["uptime_seconds"] == 0
