"""Tests for Capital Path V1 dynamic equity accounting."""

from __future__ import annotations

import pytest

from backtest.capital_path_core import (
    CapitalPathConfig,
    DrawdownBand,
    RiskPolicy,
    simulate_r_path,
)


def test_dynamic_fractional_compounding_is_exact() -> None:
    result = simulate_r_path(
        [1.0, 1.0],
        config=CapitalPathConfig(
            start_equity=3_000,
            target_equity=10_000,
            milestones=(5_000, 10_000),
            ruin_drawdown=None,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.01, drawdown_bands=(), halt_drawdown=None),
    )
    assert result.equity_path == pytest.approx((3000.0, 3030.0, 3060.3))
    assert result.terminal_state == "EXHAUSTED"


def test_first_passage_is_recorded_at_first_crossing() -> None:
    result = simulate_r_path(
        [10.0, -5.0, 10.0],
        config=CapitalPathConfig(
            start_equity=100.0,
            target_equity=121.0,
            milestones=(110.0, 121.0),
            ruin_drawdown=None,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.10, drawdown_bands=(), halt_drawdown=None),
    )
    # Trade 1 doubles account to 200, so every milestone is first crossed there.
    assert result.target_first_passage_trade == 1
    assert result.milestone_first_passage[110.0] == 1
    assert result.milestone_first_passage[121.0] == 1
    assert result.terminal_state == "SUCCESS"


def test_drawdown_governor_reduces_next_trade_risk() -> None:
    policy = RiskPolicy(
        base_risk_fraction=0.01,
        drawdown_bands=(DrawdownBand(0.05, 0.50),),
        halt_drawdown=0.20,
    )
    result = simulate_r_path(
        [-6.0, 1.0],
        config=CapitalPathConfig(
            start_equity=10_000,
            target_equity=20_000,
            milestones=(20_000,),
            ruin_drawdown=None,
        ),
        risk_policy=policy,
    )
    assert result.drawdown_path[1] == pytest.approx(0.06)
    assert result.risk_fraction_path == pytest.approx((0.01, 0.005))


def test_ruin_drawdown_terminates_path_before_later_recovery() -> None:
    result = simulate_r_path(
        [-25.0, 100.0],
        config=CapitalPathConfig(
            start_equity=1000,
            target_equity=5000,
            milestones=(5000,),
            ruin_drawdown=0.20,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.01, drawdown_bands=(), halt_drawdown=None),
    )
    assert result.terminal_state == "RUIN"
    assert result.ruin_trade == 1
    assert len(result.equity_path) == 2


def test_drawdown_halt_is_distinct_from_ruin() -> None:
    result = simulate_r_path(
        [-12.0, 2.0],
        config=CapitalPathConfig(
            start_equity=1000,
            target_equity=5000,
            milestones=(5000,),
            ruin_drawdown=0.30,
        ),
        risk_policy=RiskPolicy(
            base_risk_fraction=0.01,
            drawdown_bands=(DrawdownBand(0.05, 0.5),),
            halt_drawdown=0.10,
        ),
    )
    assert result.drawdown_path[1] == pytest.approx(0.12)
    assert result.terminal_state == "HALTED"
    assert result.halt_trade == 1
    assert result.ruin_trade is None


def test_longest_underwater_period_counts_consecutive_trades_below_peak() -> None:
    result = simulate_r_path(
        [2.0, -1.0, -1.0, 3.0],
        config=CapitalPathConfig(
            start_equity=1000,
            target_equity=5000,
            milestones=(5000,),
            ruin_drawdown=None,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.10, drawdown_bands=(), halt_drawdown=None),
    )
    assert result.longest_underwater_trades >= 2


def test_total_loss_is_ruin_even_without_explicit_ruin_thresholds() -> None:
    result = simulate_r_path(
        [-100.0],
        config=CapitalPathConfig(
            start_equity=1000,
            target_equity=5000,
            milestones=(5000,),
            ruin_equity_floor=None,
            ruin_drawdown=None,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.01, drawdown_bands=(), halt_drawdown=None),
    )
    assert result.terminal_state == "RUIN"
    assert result.terminal_equity == 0.0
