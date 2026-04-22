"""
Test suite for Position Sizing Calculator.
Tests risk-based position sizing, Kelly criterion, and drawdown scaling.
"""

import pytest

from risk.position_sizer import (
    PositionSize,
    calculate_position_size,
    drawdown_scale_factor,
    kelly_fraction,
)


class TestBasicPositionSize:
    """Test normal position sizing scenarios."""

    def test_basic_position_size_normal_inputs(self):
        """Normal inputs should produce correct result."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
            max_contracts=2,
            max_position_pct=5.0,
            drawdown_pct=0.0,
        )

        assert isinstance(result, PositionSize)
        assert result.contracts >= 0
        assert result.contracts <= 2
        assert result.risk_amount >= 0
        assert result.max_loss >= 0
        assert result.scale_factor == 1.0
        assert result.sizing_method == "atr_based"

    def test_respects_max_contracts_limit(self):
        """Position size should never exceed max_contracts."""
        result = calculate_position_size(
            equity=100000.0,  # Large equity
            risk_pct=5.0,  # High risk
            atr=5.0,  # Small ATR
            contract_multiplier=5.0,
            max_contracts=2,
            max_position_pct=5.0,
            drawdown_pct=0.0,
        )

        assert result.contracts <= 2

    def test_respects_max_position_pct_limit(self):
        """Position value should not exceed max_position_pct of equity."""
        equity = 10000.0
        max_position_pct = 5.0
        max_position_value = (equity * max_position_pct) / 100.0

        result = calculate_position_size(
            equity=equity,
            risk_pct=2.0,
            atr=20.0,
            contract_multiplier=10.0,
            max_contracts=5,
            max_position_pct=max_position_pct,
            drawdown_pct=0.0,
        )

        position_value = result.contracts * 20.0 * 10.0
        assert position_value <= max_position_value

    def test_zero_equity_returns_zero(self):
        """Edge case: zero equity should return 0 contracts."""
        result = calculate_position_size(
            equity=0.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
        )

        assert result.contracts == 0
        assert result.risk_amount == 0.0
        assert result.max_loss == 0.0

    def test_negative_equity_returns_zero(self):
        """Edge case: negative equity should return 0 contracts."""
        result = calculate_position_size(
            equity=-5000.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
        )

        assert result.contracts == 0

    def test_zero_atr_returns_zero(self):
        """Edge case: zero ATR should return 0 contracts."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=0.0,
            contract_multiplier=5.0,
        )

        assert result.contracts == 0
        assert result.risk_amount == 0.0

    def test_negative_atr_returns_zero(self):
        """Edge case: negative ATR should return 0 contracts."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=-15.0,
            contract_multiplier=5.0,
        )

        assert result.contracts == 0

    def test_zero_risk_pct_returns_zero(self):
        """Edge case: zero risk % should return 0 contracts."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=0.0,
            atr=15.0,
            contract_multiplier=5.0,
        )

        assert result.contracts == 0

    def test_small_account_floor(self):
        """Small account with reasonable risk should allow at least 1 contract."""
        result = calculate_position_size(
            equity=5000.0,
            risk_pct=1.0,
            atr=10.0,
            contract_multiplier=5.0,
            max_contracts=2,
            max_position_pct=5.0,
            drawdown_pct=0.0,
        )

        # With $5000 equity, 1% risk = $50, ATR $50 = 1 contract viable
        assert result.contracts >= 1


class TestKellyFraction:
    """Test Kelly criterion implementation."""

    def test_kelly_fraction_positive_win_rate(self):
        """Win rate > break-even should return positive Kelly fraction."""
        # 55% win rate, 1:1 risk/reward
        kelly = kelly_fraction(win_rate=0.55, avg_win=100.0, avg_loss=100.0)

        assert kelly > 0
        assert kelly <= 0.25  # Capped at quarter-Kelly

    def test_kelly_fraction_break_even_win_rate(self):
        """Win rate at break-even should return 0."""
        # 50% win rate
        kelly = kelly_fraction(win_rate=0.50, avg_win=100.0, avg_loss=100.0)

        assert kelly == 0.0

    def test_kelly_fraction_losing_win_rate(self):
        """Win rate < break-even should return 0."""
        # 45% win rate
        kelly = kelly_fraction(win_rate=0.45, avg_win=100.0, avg_loss=100.0)

        assert kelly == 0.0

    def test_kelly_fraction_zero_loss(self):
        """Division by zero edge case."""
        kelly = kelly_fraction(win_rate=0.55, avg_win=100.0, avg_loss=0.0)

        assert kelly == 0.0

    def test_kelly_fraction_zero_win(self):
        """Zero win amount edge case."""
        kelly = kelly_fraction(win_rate=0.55, avg_win=0.0, avg_loss=100.0)

        assert kelly == 0.0

    def test_kelly_fraction_invalid_win_rate_low(self):
        """Win rate <= 0 should return 0."""
        kelly = kelly_fraction(win_rate=0.0, avg_win=100.0, avg_loss=100.0)

        assert kelly == 0.0

    def test_kelly_fraction_invalid_win_rate_high(self):
        """Win rate >= 1 should return 0."""
        kelly = kelly_fraction(win_rate=1.0, avg_win=100.0, avg_loss=100.0)

        assert kelly == 0.0

    def test_kelly_fraction_favorable_odds(self):
        """Higher win amount should increase Kelly fraction."""
        # 55% win, 2:1 risk/reward (avg_win=200, avg_loss=100)
        kelly = kelly_fraction(win_rate=0.55, avg_win=200.0, avg_loss=100.0)

        assert kelly > 0
        assert kelly <= 0.25

    def test_kelly_fraction_capped_at_quarter_kelly(self):
        """Kelly should never exceed 0.25 for safety."""
        # Artificially high numbers to test cap
        kelly = kelly_fraction(win_rate=0.95, avg_win=1000.0, avg_loss=10.0)

        assert kelly <= 0.25


class TestDrawdownScaling:
    """Test drawdown-based position scaling."""

    def test_drawdown_scale_no_drawdown(self):
        """0% drawdown should return 1.0x scale."""
        scale = drawdown_scale_factor(0.0)

        assert scale == 1.0

    def test_drawdown_scale_small_drawdown(self):
        """2.5% drawdown should return 1.0x scale."""
        scale = drawdown_scale_factor(2.5)

        assert scale == 1.0

    def test_drawdown_scale_at_5_percent(self):
        """5% drawdown should transition to 0.75x scale."""
        scale = drawdown_scale_factor(5.0)

        assert scale == 0.75

    def test_drawdown_scale_between_5_and_8(self):
        """6.5% drawdown should return 0.75x scale."""
        scale = drawdown_scale_factor(6.5)

        assert scale == 0.75

    def test_drawdown_scale_at_8_percent(self):
        """8% drawdown should transition to 0.5x scale."""
        scale = drawdown_scale_factor(8.0)

        assert scale == 0.5

    def test_drawdown_scale_between_8_and_10(self):
        """9% drawdown should return 0.5x scale."""
        scale = drawdown_scale_factor(9.0)

        assert scale == 0.5

    def test_drawdown_scale_at_10_percent(self):
        """10% drawdown should stop trading (0.0x scale)."""
        scale = drawdown_scale_factor(10.0)

        assert scale == 0.0

    def test_drawdown_scale_deep_drawdown(self):
        """>10% drawdown should return 0.0x scale (kill switch)."""
        scale = drawdown_scale_factor(15.0)

        assert scale == 0.0

    def test_drawdown_scale_negative_input(self):
        """Negative drawdown (profit) should return 1.0x."""
        scale = drawdown_scale_factor(-2.0)

        assert scale == 1.0


class TestDrawdownScalingIntegration:
    """Test position sizing with drawdown scaling applied."""

    def test_position_size_reduces_with_drawdown(self):
        """Position size should reduce as drawdown increases."""
        result_no_dd = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
            drawdown_pct=0.0,
        )

        result_small_dd = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
            drawdown_pct=6.0,
        )

        result_mid_dd = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
            drawdown_pct=9.0,
        )

        assert result_no_dd.contracts >= result_small_dd.contracts
        assert result_small_dd.contracts >= result_mid_dd.contracts

    def test_deep_drawdown_stops_trading(self):
        """10%+ drawdown should force 0 contracts."""
        result = calculate_position_size(
            equity=10000.0,
            risk_pct=1.0,
            atr=15.0,
            contract_multiplier=5.0,
            drawdown_pct=10.5,
        )

        assert result.contracts == 0
        assert result.scale_factor == 0.0


class TestPositionSizeDataclass:
    """Test PositionSize dataclass."""

    def test_position_size_creation(self):
        """PositionSize should be created with all fields."""
        ps = PositionSize(
            contracts=2,
            risk_amount=500.0,
            max_loss=500.0,
            sizing_method="atr_based",
            scale_factor=1.0,
        )

        assert ps.contracts == 2
        assert ps.risk_amount == 500.0
        assert ps.max_loss == 500.0
        assert ps.sizing_method == "atr_based"
        assert ps.scale_factor == 1.0
