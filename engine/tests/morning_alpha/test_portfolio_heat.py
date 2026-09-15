from datetime import UTC, datetime

import pytest

from morning_alpha.models import StrategyKey, TradePlan
from morning_alpha.portfolio import HeatRejectionReason, PortfolioHeatEngine

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def plan(symbol: str, risk: float, *, theme: str | None, equity: float = 3000.0):
    return TradePlan(
        symbol=symbol,
        strategy=StrategyKey(strategy_id="test", version="1.0.0"),
        as_of=AS_OF,
        side="long",
        entry=100.0,
        stop=99.0,
        targets=(101.0, 102.0, 103.0, 104.0),
        risk_per_share=1.0,
        account_equity=equity,
        risk_fraction=min(0.01, risk / equity),
        shares=max(1, int(risk)),
        max_dollar_risk=risk,
        expected_r=4.0,
        theme=theme,
    )


def test_independent_cnc_xle_style_pair_fits_one_percent_total_heat():
    result = PortfolioHeatEngine().evaluate(
        [plan("CNC", 14.40, theme="managed_care"), plan("XLE", 14.85, theme="energy")]
    )
    assert result.accepted is True
    assert result.total_heat == pytest.approx((14.40 + 14.85) / 3000)


def test_ai_infrastructure_names_do_not_bypass_manual_theme_cap_without_correlation_data():
    plans = [
        plan("HPE", 13.60, theme="ai_infrastructure"),
        plan("NVDA", 14.20, theme="ai_infrastructure"),
        plan("SMH", 13.00, theme="ai_infrastructure"),
    ]
    result = PortfolioHeatEngine().evaluate(plans)
    assert result.accepted is False
    assert result.theme_heat["ai_infrastructure"] == pytest.approx(40.8 / 3000)
    assert any(v.reason is HeatRejectionReason.THEME_HEAT_LIMIT for v in result.violations)


def test_total_heat_cap_rejects_different_themes_above_1_25_percent():
    plans = [
        plan("AAA", 15, theme="a"),
        plan("BBB", 15, theme="b"),
        plan("CCC", 15, theme="c"),
    ]
    result = PortfolioHeatEngine().evaluate(plans)
    assert result.accepted is False
    assert any(v.reason is HeatRejectionReason.TOTAL_HEAT_LIMIT for v in result.violations)


def test_actual_heat_uses_modeled_dollar_risk_not_requested_fraction():
    capital_constrained = plan("EXPENSIVE", 3.0, theme="growth")
    assert PortfolioHeatEngine.actual_heat(capital_constrained) == pytest.approx(0.001)


def test_high_pairwise_correlation_adds_gate_even_with_different_manual_themes():
    a = plan("AAA", 18, theme="software")
    b = plan("BBB", 18, theme="communications")
    result = PortfolioHeatEngine().evaluate([a, b], correlations={("AAA", "BBB"): 0.91})
    assert result.accepted is False
    assert any(v.reason is HeatRejectionReason.CORRELATION_LIMIT for v in result.violations)


def test_missing_correlation_evidence_never_erases_manual_theme_limits():
    a = plan("NVDA", 16, theme="ai_infrastructure")
    b = plan("HPE", 16, theme="ai_infrastructure")
    result = PortfolioHeatEngine().evaluate([a, b], correlations={})
    assert result.accepted is False
    assert any(v.reason is HeatRejectionReason.THEME_HEAT_LIMIT for v in result.violations)


def test_empty_portfolio_is_valid_zero_heat():
    result = PortfolioHeatEngine().evaluate([])
    assert result.accepted is True
    assert result.total_heat == 0
    assert result.theme_heat == {}
