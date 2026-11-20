from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.research.concentration import analyze_edge_concentration
from morning_alpha.research.statistical_models import MatchedEdgeObservation


def _row(i, edge, *, symbol, sector, year=2024, regime="bull"):
    ts = datetime(year, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=i)
    return MatchedEdgeObservation(
        candidate_id=f"c-{year}-{i}-{symbol}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=symbol,
        sector=sector,
        regime=regime,
        strategy_return=edge,
        control_return=0.0,
    )


def test_group_stress_reports_mean_retention_ratio_after_strongest_removal():
    rows = (
        _row(0, 0.6, symbol="A", sector="Technology", year=2024, regime="bull"),
        _row(1, 0.4, symbol="B", sector="Technology", year=2024, regime="bull"),
        _row(2, 0.2, symbol="C", sector="Energy", year=2023, regime="neutral"),
        _row(3, 0.2, symbol="D", sector="Energy", year=2023, regime="neutral"),
    )
    report = analyze_edge_concentration(rows)
    assert report.mean_edge == pytest.approx(0.35)
    assert report.sector_stress.strongest_group == "Technology"
    assert report.sector_stress.mean_after_remove_strongest == pytest.approx(0.2)
    assert report.sector_stress.mean_retention_ratio == pytest.approx(0.2 / 0.35)
    assert report.year_stress.mean_retention_ratio is not None
    assert report.regime_stress.mean_retention_ratio is not None


def test_trade_removal_reports_retention_ratios():
    rows = tuple(
        _row(i, edge, symbol=f"S{i}", sector="Technology")
        for i, edge in enumerate((1.0, 0.5, 0.2, 0.1, -0.1, -0.2))
    )
    report = analyze_edge_concentration(rows)
    assert report.mean_retention_after_remove_top1 == pytest.approx(
        report.mean_after_remove_top1 / report.mean_edge
    )
    assert report.mean_retention_after_remove_top10pct == pytest.approx(
        report.mean_after_remove_top10pct / report.mean_edge
    )


def test_top_symbol_removal_removes_entire_symbol_even_with_mixed_trade_signs():
    rows = (
        _row(0, 1.2, symbol="BIG", sector="Technology"),
        _row(1, -0.2, symbol="BIG", sector="Technology"),
        _row(2, 0.1, symbol="A", sector="Energy"),
        _row(3, 0.1, symbol="B", sector="Energy"),
    )
    report = analyze_edge_concentration(rows)
    assert report.symbol_stress.strongest_group == "BIG"
    assert report.symbol_stress.strongest_group_total_edge == pytest.approx(1.0)
    assert report.mean_after_remove_top_symbol == pytest.approx(0.1)
