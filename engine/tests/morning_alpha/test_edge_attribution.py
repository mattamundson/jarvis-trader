import pytest

from morning_alpha.research.attribution import EdgeAttributionEngine


def test_attribution_reconciles_strategy_increment_over_market():
    result = EdgeAttributionEngine().attribute(
        strategy_return=0.43,
        next_open_return=0.19,
        sector_return=0.10,
        market_return=0.04,
    )

    assert result.total_increment == pytest.approx(0.39)
    assert result.components["sector_increment"] == pytest.approx(0.06)
    assert result.components["selection_increment"] == pytest.approx(0.09)
    assert result.components["timing_increment"] == pytest.approx(0.24)
    assert sum(result.components.values()) == pytest.approx(result.total_increment)


def test_negative_selection_and_timing_are_preserved_not_clipped():
    result = EdgeAttributionEngine().attribute(
        strategy_return=-0.02,
        next_open_return=0.01,
        sector_return=0.04,
        market_return=0.02,
    )

    assert result.components["selection_increment"] == pytest.approx(-0.03)
    assert result.components["timing_increment"] == pytest.approx(-0.03)
    assert result.total_increment == pytest.approx(-0.04)
    assert sum(result.components.values()) == pytest.approx(-0.04)


def test_exit_and_filter_adjustments_reconcile_through_residual():
    result = EdgeAttributionEngine().attribute(
        strategy_return=0.20,
        next_open_return=0.12,
        sector_return=0.08,
        market_return=0.03,
        exit_adjustment=0.02,
        filter_adjustment=0.01,
    )

    assert result.components["exit_adjustment"] == pytest.approx(0.02)
    assert result.components["filter_adjustment"] == pytest.approx(0.01)
    assert sum(result.components.values()) == pytest.approx(result.total_increment)
    assert result.reconciles is True


def test_raw_counterfactuals_are_preserved_for_audit():
    result = EdgeAttributionEngine().attribute(0.15, 0.10, 0.07, 0.02)
    assert result.strategy_return == pytest.approx(0.15)
    assert result.next_open_return == pytest.approx(0.10)
    assert result.sector_return == pytest.approx(0.07)
    assert result.market_return == pytest.approx(0.02)
