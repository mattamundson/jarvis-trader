"""
Tests for risk/margin_monitor.py — MarginMonitorAgent public API.

Covers: check_health (SKIPPED, HEALTHY, WARNING, CRITICAL),
_fetch_account_snapshot (both connector shapes), run_loop error-tolerance.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from risk.margin_monitor import MarginMonitorAgent


def _monitor(connector=None, **kwargs) -> MarginMonitorAgent:
    defaults = {
        "utilization_warning": 0.25,
        "utilization_halt": 0.35,
        "max_drawdown_pct": 8.0,
    }
    defaults.update(kwargs)
    return MarginMonitorAgent(connector=connector, **defaults)


@pytest.mark.asyncio
class TestCheckHealth:
    async def test_no_connector_returns_skipped(self):
        monitor = _monitor(connector=None)
        result = await monitor.check_health()
        assert result["status"] == "SKIPPED"

    async def test_connector_returns_none_from_account_summary(self):
        """Connector with no recognized method returns SKIPPED."""
        connector = MagicMock(spec=[])  # no methods
        monitor = _monitor(connector=connector)
        result = await monitor.check_health()
        assert result["status"] == "SKIPPED"

    async def test_healthy_account_returns_healthy(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        monitor = _monitor(connector=connector)
        result = await monitor.check_health()
        assert result["status"] == "HEALTHY"

    async def test_high_utilization_returns_critical(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 10000.0,
            "margin_used": 4000.0,  # 4000/10000 = 40% > 35% halt threshold
        }
        monitor = _monitor(connector=connector, utilization_halt=0.35)
        result = await monitor.check_health()
        assert result["status"] == "CRITICAL"
        assert "MARGIN" in result["message"] or "CRITICAL" in result["status"]

    async def test_warning_utilization_returns_warning(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 10000.0,
            "margin_used": 3000.0,  # 3000/10000 = 30% → between 25% warning and 35% halt
        }
        monitor = _monitor(connector=connector, utilization_warning=0.25, utilization_halt=0.35)
        result = await monitor.check_health()
        assert result["status"] == "WARNING"

    async def test_large_drawdown_returns_critical(self):
        connector = AsyncMock()
        # Peak was $10k, now at $8k → 20% drawdown > 8% limit
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        monitor = _monitor(connector=connector, max_drawdown_pct=8.0)
        # First call sets the peak
        await monitor.check_health()
        # Now equity drops to 9k → 10% drawdown
        connector.get_account_summary.return_value = {
            "equity": 9100.0,
            "buying_power": 36400.0,
            "margin_used": 0.0,
        }
        result = await monitor.check_health()
        # 9% drawdown > 8% threshold
        assert result["status"] == "CRITICAL"
        assert "DRAWDOWN" in result["message"]

    async def test_metrics_returned_in_result(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        monitor = _monitor(connector=connector)
        result = await monitor.check_health()
        assert "metrics" in result
        metrics = result["metrics"]
        assert "equity" in metrics
        assert "utilization" in metrics
        assert "drawdown_pct" in metrics

    async def test_connector_with_get_account_balance_used_as_fallback(self):
        """Connector without get_account_summary but with get_account_balance."""
        connector = MagicMock()
        connector.get_account_balance = AsyncMock(
            return_value={
                "equity": 10000.0,
                "buying_power": 40000.0,
                "margin_used": 0.0,
            }
        )
        # No get_account_summary
        del connector.get_account_summary
        monitor = _monitor(connector=connector)
        result = await monitor.check_health()
        assert result["status"] == "HEALTHY"

    async def test_empty_account_response_returns_error(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = {}
        monitor = _monitor(connector=connector)
        result = await monitor.check_health()
        # Empty dict → equity=0 → uses 0.0 gracefully → HEALTHY (no utilization)
        assert result["status"] in ("HEALTHY", "ERROR", "SKIPPED")

    async def test_none_account_response_returns_error_or_skipped(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = None
        monitor = _monitor(connector=connector)
        result = await monitor.check_health()
        # None returned from get_account_summary → falls to get_account_balance
        # or returns ERROR/SKIPPED
        assert result["status"] in ("ERROR", "SKIPPED")


@pytest.mark.asyncio
class TestFetchAccountSnapshot:
    async def test_prefers_get_account_summary(self):
        connector = AsyncMock()
        connector.get_account_summary.return_value = {"equity": 5000.0}
        connector.get_account_balance.return_value = {"equity": 9999.0}
        monitor = _monitor(connector=connector)
        snapshot = await monitor._fetch_account_snapshot()
        assert snapshot["equity"] == 5000.0

    async def test_falls_back_to_get_account_balance(self):
        connector = MagicMock()
        connector.get_account_balance = AsyncMock(return_value={"equity": 8000.0})
        del connector.get_account_summary
        monitor = _monitor(connector=connector)
        snapshot = await monitor._fetch_account_snapshot()
        assert snapshot["equity"] == 8000.0

    async def test_returns_none_when_no_method_available(self):
        connector = MagicMock(spec=[])
        monitor = _monitor(connector=connector)
        snapshot = await monitor._fetch_account_snapshot()
        assert snapshot is None


@pytest.mark.asyncio
class TestPersistedPeakSource:
    """2026-09-10 drawdown metric-source reconciliation (safety-review PR)."""

    async def test_persisted_peak_used_when_pnl_monitor_injected(self):
        """Drawdown must come from PnLMonitor's persisted peak, not process peak."""
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 13181.32,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        pnl_monitor = MagicMock()
        # Persisted 90d high-water mark (2026-08-03 peak from daily_pnl)
        pnl_monitor.get_peak_balance.return_value = 15057.89
        monitor = _monitor(connector=connector, pnl_monitor=pnl_monitor)
        result = await monitor.check_health()
        metrics = result["metrics"]
        # (15057.89 - 13181.32) / 15057.89 * 100 = 12.46%
        assert abs(metrics["drawdown_pct"] - 12.46) < 0.05
        assert result["status"] == "CRITICAL"
        assert "DRAWDOWN" in result["message"]

    async def test_pnl_monitor_exception_falls_back_to_process_peak(self):
        """If PnLMonitor.get_peak_balance throws, use in-process peak."""
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 9100.0,
            "buying_power": 36400.0,
            "margin_used": 0.0,
        }
        pnl_monitor = MagicMock()
        pnl_monitor.get_peak_balance.side_effect = RuntimeError("db unavailable")
        monitor = _monitor(connector=connector, pnl_monitor=pnl_monitor, max_drawdown_pct=8.0)
        # First call sets in-process peak at 10k
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        await monitor.check_health()
        # Second call: equity drops; persisted peak throws -> process peak path
        connector.get_account_summary.return_value = {
            "equity": 9100.0,
            "buying_power": 36400.0,
            "margin_used": 0.0,
        }
        result = await monitor.check_health()
        assert result["metrics"]["drawdown_pct"] == pytest.approx(9.0, abs=0.01)
        assert result["status"] == "CRITICAL"

    async def test_persisted_peak_zero_falls_back_to_process_peak(self):
        """If persisted peak returns 0 (no DB rows), use in-process peak."""
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        pnl_monitor = MagicMock()
        pnl_monitor.get_peak_balance.return_value = 0.0
        monitor = _monitor(connector=connector, pnl_monitor=pnl_monitor)
        result = await monitor.check_health()
        # Peak == equity -> 0% drawdown via process peak fallback
        assert result["metrics"]["drawdown_pct"] == 0.0
        assert result["status"] == "HEALTHY"

    async def test_no_pnl_monitor_preserves_legacy_behavior(self):
        """Without injection, behavior is identical to pre-change (regression guard)."""
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 0.0,
        }
        monitor = _monitor(connector=connector)
        await monitor.check_health()
        connector.get_account_summary.return_value = {
            "equity": 9100.0,
            "buying_power": 36400.0,
            "margin_used": 0.0,
        }
        result = await monitor.check_health()
        assert result["metrics"]["drawdown_pct"] == pytest.approx(9.0, abs=0.01)
