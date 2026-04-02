"""
Integration tests for foundation layer components.
Tests: HookRegistry, CapitalAllocator, CorrelationMonitor, CrossMarketRiskManager.
"""
from datetime import date, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from hooks.registry import (
    DAILY_PNL_UPDATE,
    POST_ORDER,
    SIGNAL_GENERATED,
    TRADE_CLOSED,
    HookRegistry,
)
from orchestrator.capital_allocator import CapitalAllocator
from orchestrator.correlation_monitor import CorrelationMonitor
from risk.cross_market_risk import CrossMarketRiskManager


def create_mock_handler(name: str = "handler"):
    """Create a mock handler with a __name__ attribute."""
    handler = Mock()
    handler.__name__ = name
    return handler


class TestHookRegistry:
    """Test HookRegistry event handling."""

    def test_register_listener(self):
        """Test registering a listener."""
        registry = HookRegistry()
        handler = create_mock_handler("test_handler")

        registry.on(SIGNAL_GENERATED, handler)

        assert len(registry._handlers[SIGNAL_GENERATED]) == 1
        assert registry._handlers[SIGNAL_GENERATED][0] == handler

    def test_emit_calls_all_listeners(self):
        """Test that emit calls all registered listeners."""
        registry = HookRegistry()
        handler1 = create_mock_handler("handler1")
        handler1.return_value = "result1"
        handler2 = create_mock_handler("handler2")
        handler2.return_value = "result2"

        registry.on(SIGNAL_GENERATED, handler1)
        registry.on(SIGNAL_GENERATED, handler2)

        import asyncio
        results = asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES", price=5800.0))

        assert handler1.called
        assert handler2.called
        assert len(results) == 2

    def test_emit_passes_payload_to_handlers(self):
        """Test that emit passes payload kwargs to handlers."""
        registry = HookRegistry()
        handler = create_mock_handler("payload_handler")

        registry.on(SIGNAL_GENERATED, handler)

        import asyncio
        asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES", price=5800.0, confidence=0.85))

        handler.assert_called_once_with(symbol="MES", price=5800.0, confidence=0.85)

    def test_multiple_listeners_for_different_events(self):
        """Test multiple listeners for different events."""
        registry = HookRegistry()
        handler1 = create_mock_handler("handler1")
        handler2 = create_mock_handler("handler2")
        handler3 = create_mock_handler("handler3")

        registry.on(SIGNAL_GENERATED, handler1)
        registry.on(SIGNAL_GENERATED, handler2)
        registry.on(POST_ORDER, handler3)

        import asyncio
        asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES"))

        assert handler1.called
        assert handler2.called
        assert not handler3.called

    def test_emit_handles_async_handlers(self):
        """Test that emit properly awaits async handlers."""
        registry = HookRegistry()
        async_handler = AsyncMock(return_value="async_result")
        async_handler.__name__ = "async_handler"
        sync_handler = create_mock_handler("sync_handler")
        sync_handler.return_value = "sync_result"

        registry.on(SIGNAL_GENERATED, async_handler)
        registry.on(SIGNAL_GENERATED, sync_handler)

        import asyncio
        results = asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES"))

        assert async_handler.called
        assert sync_handler.called
        assert "async_result" in results
        assert "sync_result" in results

    def test_emit_sync_only_calls_sync_handlers(self):
        """Test that emit_sync only calls synchronous handlers."""
        registry = HookRegistry()
        sync_handler = create_mock_handler("sync_handler")
        sync_handler.return_value = "sync_result"
        async_handler = AsyncMock(return_value="async_result")
        async_handler.__name__ = "async_handler"

        registry.on(SIGNAL_GENERATED, sync_handler)
        registry.on(SIGNAL_GENERATED, async_handler)

        results = registry.emit_sync(SIGNAL_GENERATED, symbol="MES")

        assert sync_handler.called
        # Async handler should be skipped
        assert len(results) == 1
        assert "sync_result" in results

    def test_emit_sync_from_sync_context(self):
        """Test emit_sync can be called from synchronous context."""
        registry = HookRegistry()
        handler = create_mock_handler("handler")
        handler.return_value = "result"

        registry.on(POST_ORDER, handler)
        results = registry.emit_sync(POST_ORDER, order_id="test-123")

        assert handler.called
        handler.assert_called_once_with(order_id="test-123")

    def test_unknown_event_handled_gracefully(self):
        """Test that emitting unknown event is handled gracefully."""
        registry = HookRegistry()

        import asyncio
        results = asyncio.run(registry.emit("unknown_event", data="test"))

        assert results == []

    def test_handler_exception_doesnt_crash_emit(self):
        """Test that handler exceptions don't crash emit."""
        registry = HookRegistry()
        bad_handler = create_mock_handler("bad_handler")
        bad_handler.side_effect = RuntimeError("Handler failed")
        good_handler = create_mock_handler("good_handler")
        good_handler.return_value = "ok"

        registry.on(SIGNAL_GENERATED, bad_handler)
        registry.on(SIGNAL_GENERATED, good_handler)

        import asyncio
        results = asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES"))

        # Both should be called despite bad_handler raising
        assert bad_handler.called
        assert good_handler.called
        assert len(results) == 2

    def test_unregister_listener(self):
        """Test unregistering a listener."""
        registry = HookRegistry()
        handler = create_mock_handler("handler")

        registry.on(SIGNAL_GENERATED, handler)
        registry.off(SIGNAL_GENERATED, handler)

        import asyncio
        asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES"))

        assert not handler.called

    def test_emit_increments_counter(self):
        """Test that emit increments event counter."""
        registry = HookRegistry()
        handler = create_mock_handler("handler")
        registry.on(SIGNAL_GENERATED, handler)

        import asyncio
        asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MES"))
        asyncio.run(registry.emit(SIGNAL_GENERATED, symbol="MNQ"))

        stats = registry.get_stats()
        assert stats["emit_counts"][SIGNAL_GENERATED] == 2

    def test_get_stats_returns_handler_counts(self):
        """Test get_stats returns registered handler counts."""
        registry = HookRegistry()
        registry.on(SIGNAL_GENERATED, create_mock_handler("h1"))
        registry.on(SIGNAL_GENERATED, create_mock_handler("h2"))
        registry.on(POST_ORDER, create_mock_handler("h3"))

        stats = registry.get_stats()

        assert stats["registered_handlers"][SIGNAL_GENERATED] == 2
        assert stats["registered_handlers"][POST_ORDER] == 1


class TestCapitalAllocator:
    """Test CapitalAllocator capital rebalancing."""

    def test_initial_allocation_splits_correctly(self):
        """Test initial capital allocation is split correctly."""
        allocations = {"futures": 10_000.0, "options": 5_000.0}
        allocator = CapitalAllocator(allocations)

        # New markets start at 25% ramp
        futures_alloc = allocator.get_allocation("futures")
        options_alloc = allocator.get_allocation("options")

        assert futures_alloc == 2_500.0  # 10_000 * 0.25
        assert options_alloc == 1_250.0  # 5_000 * 0.25

    def test_ramp_up_increases_allocation(self):
        """Test ramp-up logic increases capital allocation."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        initial = allocator.get_allocation("futures")
        allocator.ramp_up("futures")
        after_ramp = allocator.get_allocation("futures")

        assert initial == 2_500.0
        assert after_ramp == 5_000.0  # 2500 + (10000 * 0.25)

    def test_ramp_up_multiple_steps(self):
        """Test multiple ramp-up steps approach 100%."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        allocator.ramp_up("futures")  # 0.25 -> 0.50
        allocator.ramp_up("futures")  # 0.50 -> 0.75
        allocator.ramp_up("futures")  # 0.75 -> 1.00

        final = allocator.get_allocation("futures")
        assert final == 10_000.0  # Full capital

    def test_ramp_up_caps_at_100_percent(self):
        """Test ramp-up doesn't exceed 100% allocation."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        # Ramp up to 100%
        for _ in range(10):  # More steps than needed
            allocator.ramp_up("futures")

        final = allocator.get_allocation("futures")
        assert final == 10_000.0

    def test_record_daily_pnl(self):
        """Test recording daily P&L for performance history."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        allocator.record_daily_pnl("futures", 150.0)
        allocator.record_daily_pnl("futures", 200.0)

        summary = allocator.get_summary()
        assert summary["futures"]["days_tracked"] == 2

    def test_rebalance_after_pnl_changes(self):
        """Test that allocator tracks performance history (30-day rolling)."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        # Record some P&L
        for i in range(5):
            allocator.record_daily_pnl("futures", 100.0 + i * 10)

        summary = allocator.get_summary()
        assert summary["futures"]["days_tracked"] == 5

    def test_performance_history_rolling_30_days(self):
        """Test that performance history keeps only 30 days."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        # Record 35 days of P&L
        for _ in range(35):
            allocator.record_daily_pnl("futures", 100.0)

        summary = allocator.get_summary()
        # Should only keep 30 most recent
        assert summary["futures"]["days_tracked"] == 30

    def test_get_summary_returns_all_markets(self):
        """Test get_summary returns info for all markets."""
        allocations = {"futures": 10_000.0, "options": 5_000.0, "crypto": 3_000.0}
        allocator = CapitalAllocator(allocations)

        summary = allocator.get_summary()

        assert len(summary) == 3
        assert "futures" in summary
        assert "options" in summary
        assert "crypto" in summary
        assert summary["futures"]["base_capital"] == 10_000.0
        assert summary["options"]["base_capital"] == 5_000.0

    def test_summary_includes_ramp_factor(self):
        """Test that summary includes ramp factor."""
        allocations = {"futures": 10_000.0}
        allocator = CapitalAllocator(allocations)

        allocator.ramp_up("futures")  # 0.25 -> 0.50

        summary = allocator.get_summary()
        assert summary["futures"]["ramp_factor"] == 0.50
        assert summary["futures"]["effective_capital"] == 5_000.0


class TestCorrelationMonitor:
    """Test CorrelationMonitor directional exposure tracking."""

    def test_tracks_positions_correctly(self):
        """Test that monitor tracks market positions."""
        monitor = CorrelationMonitor(total_capital=100_000.0)

        monitor.update("futures", 15_000.0)  # 15% long
        monitor.update("options", 5_000.0)   # 5% long

        status = monitor.get_status()
        assert status["by_market"]["futures"] == 15_000.0
        assert status["by_market"]["options"] == 5_000.0

    def test_calculates_directional_exposure(self):
        """Test directional exposure calculation."""
        monitor = CorrelationMonitor(total_capital=100_000.0)

        monitor.update("futures", 20_000.0)  # 20% long
        monitor.update("options", 10_000.0)  # 10% long

        exposure_pct = monitor.total_net_exposure_pct()
        assert exposure_pct == 0.30  # 30%

    def test_net_exposure_includes_shorts(self):
        """Test that net exposure includes short positions."""
        monitor = CorrelationMonitor(total_capital=100_000.0)

        monitor.update("futures", 20_000.0)   # 20% long
        monitor.update("options", -10_000.0)  # 10% short

        net_exposure = monitor.total_net_exposure()
        assert net_exposure == 10_000.0  # 20k - 10k
        assert monitor.total_net_exposure_pct() == 0.10

    def test_blocks_new_position_above_threshold(self):
        """Test that overexposure flag is set at 30% threshold."""
        monitor = CorrelationMonitor(total_capital=100_000.0, max_directional_pct=0.30)

        # At exactly 30%
        monitor.update("futures", 30_000.0)
        assert not monitor.is_overexposed()

        # Just above 30%
        monitor.update("futures", 30_001.0)
        assert monitor.is_overexposed()

    def test_gets_status(self):
        """Test get_status returns complete status."""
        monitor = CorrelationMonitor(total_capital=100_000.0)
        monitor.update("futures", 15_000.0)

        status = monitor.get_status()

        assert status["total_capital"] == 100_000.0
        assert status["net_exposure_usd"] == 15_000.0
        assert status["net_exposure_pct"] == 15.0
        assert status["max_directional_pct"] == 30.0
        assert not status["overexposed"]

    def test_zero_capital_handles_gracefully(self):
        """Test monitor handles zero capital gracefully."""
        monitor = CorrelationMonitor(total_capital=0.0)

        monitor.update("futures", 0.0)
        assert monitor.total_net_exposure_pct() == 0.0
        assert not monitor.is_overexposed()

    def test_short_positions_reduce_net_exposure(self):
        """Test that short positions reduce net long exposure."""
        monitor = CorrelationMonitor(total_capital=100_000.0)

        monitor.update("futures", 50_000.0)   # 50% long
        monitor.update("options", -30_000.0)  # 30% short

        net = monitor.total_net_exposure()
        assert net == 20_000.0  # 50k - 30k

        pct = monitor.total_net_exposure_pct()
        assert pct == 0.20  # 20%

    def test_custom_threshold(self):
        """Test custom max directional percentage."""
        monitor = CorrelationMonitor(total_capital=100_000.0, max_directional_pct=0.15)

        monitor.update("futures", 14_999.0)
        assert not monitor.is_overexposed()

        monitor.update("futures", 15_001.0)
        assert monitor.is_overexposed()


class TestCrossMarketRiskManager:
    """Test CrossMarketRiskManager cross-market risk enforcement."""

    def test_per_market_halt_at_minus_2_percent(self):
        """Test per-market halt when loss exceeds -2% of market capital."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0},
            max_market_loss_pct=2.0,
        )

        # -2.1% of 10k = -210
        actions = manager.update_pnl("futures", -210.0)

        assert "market_halted" in actions
        assert manager.is_market_halted("futures")

    def test_portfolio_halt_at_minus_5_percent(self):
        """Test portfolio-wide halt at -5% of total capital."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0},  # Total 15k
            max_portfolio_loss_pct=5.0,
        )

        # Trigger portfolio loss > 5%
        actions = manager.update_pnl("futures", -800.0)

        # Should halt entire portfolio
        assert "portfolio_halted" in actions
        assert manager.is_portfolio_halted()

    def test_portfolio_halt_halts_all_markets(self):
        """Test that portfolio halt also halts all individual markets."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0},
            max_portfolio_loss_pct=5.0,
        )

        manager.update_pnl("futures", -800.0)  # Trigger portfolio halt

        assert manager.is_market_halted("futures")
        assert manager.is_market_halted("options")

    def test_market_halt_doesnt_halt_portfolio(self):
        """Test that single market halt doesn't halt portfolio."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0},
            max_market_loss_pct=2.0,
            max_portfolio_loss_pct=5.0,
        )

        manager.update_pnl("futures", -300.0)  # -3% on 10k market

        assert manager.is_market_halted("futures")
        assert not manager.is_portfolio_halted()

    def test_halt_callback_invoked(self):
        """Test that halt callbacks are called."""
        callback = Mock()
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0},
            max_market_loss_pct=2.0,
        )
        manager.register_halt_callback(callback)

        manager.update_pnl("futures", -300.0)

        assert callback.called
        callback.assert_called_once()

    def test_reset_daily_clears_pnl(self):
        """Test that reset_daily clears daily P&L tracking."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0}
        )

        manager.update_pnl("futures", 500.0)
        manager.reset_daily()

        status = manager.get_status()
        assert status["total_daily_pnl"] == 0.0
        assert status["markets"]["futures"]["daily_pnl"] == 0.0

    def test_reset_daily_clears_halts(self):
        """Test that reset_daily clears halt flags."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0},
            max_market_loss_pct=2.0,
        )

        manager.update_pnl("futures", -300.0)  # Halt market
        assert manager.is_market_halted("futures")

        manager.reset_daily()
        assert not manager.is_market_halted("futures")

    def test_get_status_returns_market_states(self):
        """Test get_status returns status for all markets."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0}
        )

        manager.update_pnl("futures", 150.0)
        manager.update_pnl("options", -100.0)

        status = manager.get_status()

        assert "futures" in status["markets"]
        assert "options" in status["markets"]
        assert status["markets"]["futures"]["daily_pnl"] == 150.0
        assert status["markets"]["options"]["daily_pnl"] == -100.0

    def test_unknown_market_handled_gracefully(self):
        """Test that unknown market is handled gracefully."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0}
        )

        actions = manager.update_pnl("unknown_market", 100.0)

        # Should return empty actions for unknown market
        assert actions == {}

    def test_portfolio_loss_percentage_calculation(self):
        """Test portfolio loss percentage is calculated correctly."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0}  # Total 15k
        )

        manager.update_pnl("futures", -300.0)  # -2%
        manager.update_pnl("options", -100.0)  # -2%

        status = manager.get_status()
        # Total loss: -400 / 15000 = -2.67%
        assert abs(status["portfolio_loss_pct"] - (-2.667)) < 0.01

    def test_market_loss_percentage_calculated_correctly(self):
        """Test individual market loss percentage is correct."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0}
        )

        manager.update_pnl("futures", -150.0)

        status = manager.get_status()
        # -150 / 10000 = -1.5%
        assert abs(status["markets"]["futures"]["loss_pct"] - (-1.5)) < 0.01

    def test_multiple_updates_same_market(self):
        """Test multiple P&L updates for same market."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0}
        )

        manager.update_pnl("futures", 100.0)
        manager.update_pnl("futures", 150.0)  # Update again

        status = manager.get_status()
        assert status["markets"]["futures"]["daily_pnl"] == 150.0  # Latest value

    def test_aggregate_portfolio_pnl(self):
        """Test portfolio P&L aggregates across markets."""
        manager = CrossMarketRiskManager(
            market_capitals={"futures": 10_000.0, "options": 5_000.0, "crypto": 5_000.0}
        )

        manager.update_pnl("futures", 200.0)
        manager.update_pnl("options", 100.0)
        manager.update_pnl("crypto", -50.0)

        status = manager.get_status()
        assert status["total_daily_pnl"] == 250.0  # 200 + 100 - 50
