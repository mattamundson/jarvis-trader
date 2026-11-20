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


def test_dominant_symbol_removal_recomputes_mean_edge():
    rows = (
        _row(0, 1.0, symbol="BIG", sector="Technology"),
        _row(1, -0.10, symbol="A", sector="Technology"),
        _row(2, -0.10, symbol="B", sector="Energy"),
        _row(3, -0.10, symbol="C", sector="Energy"),
    )
    report = analyze_edge_concentration(rows)
    assert report.symbol_stress.strongest_group == "BIG"
    assert report.symbol_stress.mean_after_remove_strongest == pytest.approx(-0.10)
    assert report.symbol_stress.n_after_remove_strongest == 3
    assert report.mean_after_remove_top_symbol == pytest.approx(-0.10)


def test_sector_year_and_regime_removals_are_reported():
    rows = (
        _row(0, 0.5, symbol="A", sector="Technology", year=2024, regime="bull"),
        _row(1, 0.4, symbol="B", sector="Technology", year=2024, regime="bull"),
        _row(2, -0.1, symbol="C", sector="Energy", year=2023, regime="bear"),
        _row(3, -0.1, symbol="D", sector="Energy", year=2023, regime="bear"),
    )
    report = analyze_edge_concentration(rows)
    assert report.sector_stress.strongest_group == "Technology"
    assert report.year_stress.strongest_group == "2024"
    assert report.regime_stress.strongest_group == "bull"
    assert report.sector_stress.mean_after_remove_strongest < 0
    assert report.year_stress.mean_after_remove_strongest < 0
    assert report.regime_stress.mean_after_remove_strongest < 0


def test_positive_hhi_is_higher_for_concentrated_symbol_contributions():
    concentrated = tuple(
        [_row(0, 1.0, symbol="BIG", sector="Technology")]
        + [_row(i, 0.0, symbol=f"S{i}", sector="Technology") for i in range(1, 6)]
    )
    diffuse = tuple(
        _row(i, 0.2, symbol=f"S{i}", sector="Technology") for i in range(5)
    )
    assert analyze_edge_concentration(concentrated).symbol_hhi > analyze_edge_concentration(diffuse).symbol_hhi


def test_symbol_top5_and_top10pct_group_removal_are_computed():
    rows = tuple(
        _row(i, (10 - i) / 100, symbol=f"S{i}", sector="Technology" if i < 5 else "Energy")
        for i in range(10)
    )
    report = analyze_edge_concentration(rows)
    assert report.mean_after_remove_top5_symbols is not None
    assert report.mean_after_remove_top10pct_symbols is not None
    assert report.mean_after_remove_top5_symbols < report.mean_edge
    assert report.mean_after_remove_top10pct_symbols < report.mean_edge


def test_group_removal_that_empties_sample_returns_none():
    rows = (
        _row(0, 0.5, symbol="ONLY", sector="Technology"),
        _row(1, 0.4, symbol="ONLY", sector="Technology"),
    )
    report = analyze_edge_concentration(rows)
    assert report.symbol_stress.mean_after_remove_strongest is None
    assert report.symbol_stress.n_after_remove_strongest == 0
