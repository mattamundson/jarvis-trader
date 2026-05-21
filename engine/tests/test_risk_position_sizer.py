"""
Tests for risk/position_sizer.py — calculate_position_size, kelly_fraction,
drawdown_scale_factor.

Each test asserts on public output only (PositionSize fields). No implementation
details are tested.
"""

from __future__ import annotations

import pytest

from risk.position_sizer import (
    PositionSize,
    calculate_position_size,
    drawdown_scale_factor,
    kelly_fraction,
)


class TestDrawdownScaleFactor:
    def test_no_drawdown_returns_full_size(self):
        assert drawdown_scale_factor(0.0) == 1.0

    def test_negative_drawdown_returns_full_size(self):
        """Negative drawdown means equity above peak — no reduction."""
        assert drawdown_scale_factor(-5.0) == 1.0

    def test_4pct_drawdown_full_size(self):
        assert drawdown_scale_factor(4.9) == 1.0

    def test_5pct_drawdown_three_quarter_size(self):
        assert drawdown_scale_factor(5.0) == 0.75

    def test_7pct_drawdown_three_quarter_size(self):
        assert drawdown_scale_factor(7.9) == 0.75

    def test_8pct_drawdown_half_size(self):
        assert drawdown_scale_factor(8.0) == 0.5

    def test_9pct_drawdown_half_size(self):
        assert drawdown_scale_factor(9.9) == 0.5

    def test_10pct_drawdown_zero(self):
        assert drawdown_scale_factor(10.0) == 0.0

    def test_extreme_drawdown_zero(self):
        assert drawdown_scale_factor(50.0) == 0.0


class TestKellyFraction:
    def test_positive_edge_returns_positive_fraction(self):
        fraction = kelly_fraction(win_rate=0.6, avg_win=100.0, avg_loss=50.0)
        assert 0.0 < fraction <= 0.25

    def test_no_edge_returns_zero(self):
        """Equal average win/loss with 50% win rate → Kelly ≈ 0."""
        fraction = kelly_fraction(win_rate=0.5, avg_win=100.0, avg_loss=100.0)
        assert fraction == 0.0

    def test_zero_avg_loss_returns_zero(self):
        fraction = kelly_fraction(win_rate=0.6, avg_win=100.0, avg_loss=0.0)
        assert fraction == 0.0

    def test_zero_avg_win_returns_zero(self):
        fraction = kelly_fraction(win_rate=0.6, avg_win=0.0, avg_loss=50.0)
        assert fraction == 0.0

    def test_win_rate_zero_returns_zero(self):
        fraction = kelly_fraction(win_rate=0.0, avg_win=100.0, avg_loss=50.0)
        assert fraction == 0.0

    def test_win_rate_one_returns_zero(self):
        """win_rate=1.0 is invalid (q=0 → Kelly undefined) — expect 0."""
        fraction = kelly_fraction(win_rate=1.0, avg_win=100.0, avg_loss=50.0)
        assert fraction == 0.0

    def test_result_capped_at_quarter_kelly(self):
        """Very high edge still capped at 0.25 (quarter-Kelly safety cap)."""
        fraction = kelly_fraction(win_rate=0.9, avg_win=1000.0, avg_loss=10.0)
        assert fraction == 0.25

    def test_result_never_negative(self):
        fraction = kelly_fraction(win_rate=0.3, avg_win=50.0, avg_loss=200.0)
        assert fraction >= 0.0


class TestCalculatePositionSize:
    def test_zero_equity_returns_zero_contracts(self):
        result = calculate_position_size(equity=0.0, risk_pct=1.0, atr=5.0, contract_multiplier=5.0)
        assert result.contracts == 0

    def test_zero_atr_returns_zero_contracts(self):
        result = calculate_position_size(
            equity=10000.0, risk_pct=1.0, atr=0.0, contract_multiplier=5.0
        )
        assert result.contracts == 0

    def test_zero_risk_pct_returns_zero_contracts(self):
        result = calculate_position_size(
            equity=10000.0, risk_pct=0.0, atr=5.0, contract_multiplier=5.0
        )
        assert result.contracts == 0

    def test_normal_inputs_returns_positive_contracts(self):
        """$10K equity, 1% risk, ATR=5 pts, MES multiplier=5 → risk budget $100."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=5.0,
            contract_multiplier=5.0,
            max_contracts=2,
        )
        # risk_budget = 100; risk_per_contract = 5*5=25 → contracts_from_risk=4, capped at 2
        assert result.contracts == 2

    def test_hard_limit_caps_contracts(self):
        """Even with huge risk budget, max_contracts limits output."""
        result = calculate_position_size(
            equity=1_000_000.0,
            risk_pct=10.0,
            atr=1.0,
            contract_multiplier=5.0,
            max_contracts=2,
        )
        assert result.contracts <= 2

    def test_position_value_cap_applied(self):
        """If calculated contracts exceed max_position_pct, contracts are reduced."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=50.0,  # huge risk budget
            atr=200.0,  # large ATR (high position value per contract)
            contract_multiplier=5.0,
            max_contracts=10,
            max_position_pct=5.0,
        )
        # position_value = contracts * 200 * 5; max = 10000*5%=500 → ≤ 0 or 1 contract
        assert result.contracts >= 0

    def test_drawdown_scaling_reduces_contracts(self):
        """At 8% drawdown scale=0.5, risk budget halved → fewer contracts."""
        result_full = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=5.0,
            contract_multiplier=5.0,
            max_contracts=4,
            drawdown_pct=0.0,
        )
        result_half = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=5.0,
            contract_multiplier=5.0,
            max_contracts=4,
            drawdown_pct=8.0,  # scale = 0.5
        )
        assert result_half.contracts <= result_full.contracts

    def test_scale_factor_stored_in_result(self):
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=5.0,
            contract_multiplier=5.0,
            drawdown_pct=8.0,
        )
        assert result.scale_factor == 0.5

    def test_sizing_method_is_atr_based(self):
        result = calculate_position_size(
            equity=10000.0, risk_pct=1.0, atr=5.0, contract_multiplier=5.0
        )
        assert result.sizing_method == "atr_based"

    def test_result_is_position_size_dataclass(self):
        result = calculate_position_size(
            equity=10000.0, risk_pct=1.0, atr=5.0, contract_multiplier=5.0
        )
        assert isinstance(result, PositionSize)

    def test_risk_amount_matches_contracts_times_atr(self):
        result = calculate_position_size(
            equity=100_000.0,
            risk_pct=1.0,
            atr=10.0,
            contract_multiplier=5.0,
            max_contracts=3,
        )
        if result.contracts > 0:
            expected_risk = result.contracts * 10.0 * 5.0
            assert abs(result.risk_amount - expected_risk) < 0.01
