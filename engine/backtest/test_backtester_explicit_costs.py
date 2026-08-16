"""Regression coverage for configuration-independent research backtests."""

from backtest import backtester as backtester_module
from backtest.backtester import Backtester


def test_explicit_execution_costs_do_not_load_runtime_settings(monkeypatch) -> None:
    def fail_if_called():
        raise AssertionError("runtime settings must not load when all costs are explicit")

    monkeypatch.setattr(backtester_module, "_get_settings", fail_if_called)
    backtester = Backtester(
        commission_per_contract=1.25,
        slippage_ticks=1.0,
        spread_ticks=0.0,
    )
    assert backtester.commission_per_contract == 1.25
    assert backtester.slippage_ticks == 1.0
    assert backtester.spread_ticks == 0.0
    assert backtester.commission_enabled is True
    assert backtester.slippage_enabled is True
    assert backtester.spread_enabled is False
