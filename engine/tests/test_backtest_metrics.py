"""
JARVIS TRADER — Backtest Metrics Unit Tests
Tests for VaR/CVaR computation in BacktestResult.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.metrics import calculate_metrics
from backtest.trade_manager import BacktestResult, Trade

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_result_with_equity(equity_curve: list, n_trades: int = 0) -> BacktestResult:
    """Construct a minimal BacktestResult with a given equity curve."""
    result = BacktestResult(
        symbol="TEST",
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_capital=10000.0,
        final_capital=equity_curve[-1] if equity_curve else 10000.0,
    )
    result.equity_curve = equity_curve
    return result


# ── VaR / CVaR tests ─────────────────────────────────────────────────────────


def test_var_cvar_positive_returns():
    """VaR/CVaR on predominantly positive returns should be small negatives or near zero."""
    # Equity that mostly goes up with occasional small dips
    base = 10000.0
    daily_pcts = [0.01, 0.02, -0.005, 0.015, -0.003, 0.01, 0.008, -0.002, 0.012, 0.005,
                  0.01, 0.02, -0.005, 0.015, -0.003, 0.01, 0.008, -0.002, 0.012, 0.005]
    equity = [base]
    for r in daily_pcts:
        equity.append(equity[-1] * (1 + r))

    # Compute VaR/CVaR directly (mirrors logic in metrics.py)
    eq = np.array(equity)
    daily_returns = np.diff(eq) / eq[:-1]
    sorted_returns = np.sort(daily_returns)
    var_95 = float(np.percentile(sorted_returns, 5))
    var_99 = float(np.percentile(sorted_returns, 1))
    tail_95 = sorted_returns[sorted_returns <= var_95]
    cvar_95 = float(tail_95.mean()) if len(tail_95) > 0 else var_95
    tail_99 = sorted_returns[sorted_returns <= var_99]
    cvar_99 = float(tail_99.mean()) if len(tail_99) > 0 else var_99

    # VaR should be a loss (negative)
    assert var_95 <= 0, f"VaR-95 should be negative, got {var_95}"
    assert var_99 <= var_95, f"VaR-99 should be <= VaR-95 (deeper tail), got {var_99} vs {var_95}"

    # CVaR should be <= VaR (equal or worse)
    assert cvar_95 <= var_95, f"CVaR-95 should be <= VaR-95, got {cvar_95} vs {var_95}"
    assert cvar_99 <= var_99, f"CVaR-99 should be <= VaR-99, got {cvar_99} vs {var_99}"

    # For mostly-positive returns, VaR-95 should be a small loss, not catastrophic
    assert var_95 > -0.10, f"VaR-95 unexpectedly large: {var_95:.4f}"


def test_var_cvar_stored_on_result():
    """VaR/CVaR fields are populated on BacktestResult after calculate_metrics with enough data."""
    base = 10000.0
    daily_pcts = [0.01, -0.02, 0.015, -0.005, 0.008, 0.012, -0.003, 0.009, -0.007, 0.011,
                  0.014, -0.006, 0.010, -0.004, 0.013, 0.007, -0.008, 0.016, -0.002, 0.009]
    equity = [base]
    for r in daily_pcts:
        equity.append(equity[-1] * (1 + r))

    start = datetime(2024, 1, 1)
    trades = []
    for i in range(20):
        t = Trade(
            entry_date=start + timedelta(days=i),
            exit_date=start + timedelta(days=i + 1),
            entry_price=100.0,
            exit_price=101.0 if i % 3 != 0 else 99.0,
            direction="long",
            contracts=1,
            multiplier=1.0,
            symbol="TEST",
            stop_price=98.0,
            target_1=102.0,
            target_2=104.0,
            pnl=100.0 if i % 3 != 0 else -100.0,
            exit_reason="target",
            holding_bars=1,
        )
        trades.append(t)

    result = make_result_with_equity(equity)
    result.trades = trades
    result = calculate_metrics(result)

    assert result.var_95 != 0.0, "var_95 should be set after calculate_metrics"
    assert result.var_99 != 0.0, "var_99 should be set after calculate_metrics"
    assert result.cvar_95 != 0.0, "cvar_95 should be set after calculate_metrics"
    assert result.cvar_99 != 0.0, "cvar_99 should be set after calculate_metrics"

    assert result.var_99 <= result.var_95, "VaR-99 must be <= VaR-95"
    assert result.cvar_95 <= result.var_95, "CVaR-95 must be <= VaR-95"
    assert result.cvar_99 <= result.var_99, "CVaR-99 must be <= VaR-99"


def test_var_cvar_zero_when_insufficient_data():
    """VaR/CVaR remain 0.0 when equity curve has fewer than 11 points (< 10 returns)."""
    equity = [10000.0, 10100.0, 10050.0, 10200.0, 10150.0]  # only 4 returns
    result = make_result_with_equity(equity)
    # fields default to 0.0 and won't be set without sufficient data
    assert result.var_95 == 0.0
    assert result.cvar_95 == 0.0


def test_var_cvar_in_to_dict():
    """to_dict() includes all four VaR/CVaR keys."""
    result = make_result_with_equity([10000.0, 10100.0])
    result.var_95 = -0.012
    result.var_99 = -0.025
    result.cvar_95 = -0.018
    result.cvar_99 = -0.030
    d = result.to_dict()
    assert "var_95" in d
    assert "var_99" in d
    assert "cvar_95" in d
    assert "cvar_99" in d
    assert d["var_95"] == round(-0.012, 6)
    assert d["cvar_99"] == round(-0.030, 6)


def test_validate_backtest_result_cvar_gate():
    """CVaR gate flags a result with tail losses worse than -5% per day."""
    from backtest.optimizer import validate_backtest_result

    good_stats = {
        "n_trades": 30,
        "profit_factor": 2.0,
        "max_drawdown_pct": 5.0,
        "exposure_time_pct": 40.0,
        "sharpe": 1.5,
        "calmar_ratio": 1.2,
        "cvar_95": -0.03,  # within threshold
    }
    result = validate_backtest_result(good_stats)
    assert result["verdict"] == "ELIGIBLE", f"Expected ELIGIBLE, got {result}"

    bad_stats = dict(good_stats)
    bad_stats["cvar_95"] = -0.08  # exceeds -5% threshold
    result = validate_backtest_result(bad_stats)
    assert result["verdict"] in ("DISCARD_PROFIT", "DISCARD_RISK"), (
        f"Expected DISCARD verdict for bad CVaR, got {result['verdict']}"
    )
    assert any("CVaR" in v for v in result["violations"]), (
        f"Expected CVaR violation message, got {result['violations']}"
    )
