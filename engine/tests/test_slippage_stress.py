"""Tests for the breakeven-slippage stress test in backtest.monte_carlo.

Covers:
- `run_slippage_stress` (BacktestResult-based) and `slippage_stress_from_pnls`
  (flat-PnL-list-based) are byte-identical on the same trade series -- they
  share one core implementation (`_slippage_stress_core`), this is the
  refactor's central invariant.
- Verdict buckets (ROBUST / ADEQUATE / MARGINAL / FRAGILE / NO_TRADES).
- `_gate_v2_trade_metrics.trade_level_slippage_stress` delegates correctly on
  a concatenated OOS trade list and is fail-safe on too few trades.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from backtest._gate_v2_trade_metrics import trade_level_slippage_stress
from backtest.monte_carlo import run_slippage_stress, slippage_stress_from_pnls
from backtest.trade_manager import BacktestResult, Trade


def _trade(pnl: float) -> Trade:
    return Trade(
        entry_date=datetime.now(),
        symbol="MES",
        direction="long",
        entry_price=0.0,
        stop_price=0.0,
        target_1=0.0,
        target_2=0.0,
        contracts=1,
        multiplier=1.0,
        pnl=pnl,
    )


def _result(pnls: list[float]) -> BacktestResult:
    trades = [_trade(p) for p in pnls]
    return BacktestResult(
        symbol="MES",
        start_date="",
        end_date="",
        initial_capital=10_000.0,
        final_capital=10_000.0 + sum(pnls),
        trades=trades,
    )


class TestParityBetweenEntryPoints:
    def test_run_slippage_stress_matches_from_pnls(self):
        """The two public entry points must return identical results on the
        same trade series -- they delegate to the same `_slippage_stress_core`."""
        pnls = [50.0, -20.0, 80.0, -40.0, 30.0, -60.0, 100.0, -10.0]
        result = _result(pnls)

        from_result = run_slippage_stress(result, symbol="MES")
        from_pnls = slippage_stress_from_pnls(pnls, symbol="MES")

        assert from_result["breakeven_extra_ticks"] == from_pnls["breakeven_extra_ticks"]
        assert from_result["verdict"] == from_pnls["verdict"]
        assert from_result["scenarios"] == from_pnls["scenarios"]
        assert from_result["tick_value"] == from_pnls["tick_value"]
        assert from_result["n_trades"] == from_pnls["n_trades"] == len(pnls)

    def test_empty_pnls_both_report_no_trades(self):
        assert run_slippage_stress(_result([]), symbol="MES")["verdict"] == "NO_TRADES"
        assert slippage_stress_from_pnls([], symbol="MES")["verdict"] == "NO_TRADES"


class TestVerdictBuckets:
    def test_robust_when_pf_never_crosses_breakeven(self):
        # Large, consistent wins vs small losses -- PF stays > 1.0 even at
        # the widest stress scenario (8 ticks).
        pnls = [1000.0] * 20 + [-50.0] * 5
        report = slippage_stress_from_pnls(pnls, symbol="MES")
        assert report["breakeven_extra_ticks"] is None
        assert report["verdict"] == "ROBUST"

    def test_fragile_when_thin_edge(self):
        # PF barely above 1.0 at zero slippage -- any added cost breaks even
        # almost immediately (breakeven < 2 ticks).
        pnls = [10.0] * 10 + [-9.5] * 10
        report = slippage_stress_from_pnls(pnls, symbol="MES")
        assert report["breakeven_extra_ticks"] is not None
        assert report["breakeven_extra_ticks"] < 2
        assert report["verdict"] == "FRAGILE"


class TestTradeLevelSlippageStress:
    def _window(self, pnls):
        return SimpleNamespace(trades=[SimpleNamespace(pnl=p) for p in pnls])

    def test_matches_canonical_primitive_on_concatenated_pnls(self):
        pnls = [50.0, -20.0, 80.0, -40.0, 30.0, -60.0, 100.0, -10.0]
        windows = [self._window(pnls[:4]), self._window(pnls[4:])]
        expected = slippage_stress_from_pnls(pnls, symbol="MGC")
        actual = trade_level_slippage_stress(windows, symbol="MGC")
        assert actual == expected

    def test_failsafe_when_too_few_trades(self):
        result = trade_level_slippage_stress([self._window([42.0])], symbol="MES")
        assert result["breakeven_extra_ticks"] is None
        assert result["verdict"] == "NO_TRADES"

    def test_failsafe_when_empty(self):
        result = trade_level_slippage_stress([self._window([])], symbol="MES")
        assert result["breakeven_extra_ticks"] is None
        assert result["verdict"] == "NO_TRADES"

    def test_does_not_raise_and_returns_symbol(self):
        windows = [self._window([100.0, -50.0, 30.0])]
        result = trade_level_slippage_stress(windows, symbol="MGC")
        assert result["symbol"] == "MGC"
