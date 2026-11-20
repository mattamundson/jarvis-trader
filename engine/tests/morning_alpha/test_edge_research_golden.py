from datetime import UTC, datetime, timedelta

from morning_alpha.models import MarketBar, Session, SetupCandidate, StrategyKey
from morning_alpha.research.ablation import AblationKind, AblationRunner
from morning_alpha.research.attribution import EdgeAttributionEngine
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.controls import UniverseMember
from morning_alpha.research.relative_strength_sprint import (
    RelativeStrengthResearchSprint,
    RelativeStrengthSprintInput,
    SprintStatus,
)
from morning_alpha.research.robustness import ParameterPoint, analyze_parameter_stability
from morning_alpha.research.trial_ledger import InMemoryTrialLedger

AS_OF = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)


def _candidate(entry=100.0):
    return SetupCandidate(
        symbol="AAA",
        strategy=StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        as_of=AS_OF,
        side="long",
        setup_type="relative_strength_breakout",
        thesis_code="rs_breakout",
        proposed_entry=entry,
        proposed_stop=98.0,
        sector="Technology",
    )


def _bar(symbol, day, open_, close):
    ts = AS_OF + timedelta(days=day, minutes=30)
    return MarketBar(
        symbol=symbol,
        timestamp=ts,
        open=open_,
        high=max(open_, close) + 0.25,
        low=min(open_, close) - 0.25,
        close=close,
        volume=1_000_000,
        session=Session.RTH,
        source="golden",
        ingested_at=ts,
    )


def _ready():
    return DataReadinessReport(
        ready=True,
        file_stage_ready=True,
        manifest_present=True,
        root="/golden",
        file_count=9,
        symbols=("AAA", "BBB", "SPY", "XLK"),
        providers=("golden",),
        daily_symbol_count=500,
        intraday_symbol_count=100,
        reasons=(),
    )


def _member(symbol):
    return UniverseMember(
        symbol=symbol,
        sector="Technology",
        effective_from=AS_OF - timedelta(days=365),
        eligible=True,
    )


def _inputs(aaa_close_5, xlk_close_5):
    bars = {
        "AAA": tuple(_bar("AAA", d, 102.0 if d == 0 else 103 + d, 103 + (aaa_close_5 - 103) * d / 5) for d in range(6)),
        "BBB": tuple(_bar("BBB", d, 50 + d, 50.5 + d) for d in range(6)),
        "SPY": tuple(_bar("SPY", d, 400 + d, 401 + d) for d in range(6)),
        "XLK": tuple(_bar("XLK", d, 200 + d, 201 + (xlk_close_5 - 201) * d / 5) for d in range(6)),
    }
    return RelativeStrengthSprintInput(
        readiness=_ready(),
        candidate=_candidate(),
        universe=(_member("BBB"),),
        sector_etf="XLK",
        bars_by_symbol=bars,
        data_manifest_hash="a" * 64,
        sample_start=AS_OF,
        sample_end=AS_OF + timedelta(days=5),
    )


def test_golden_positive_selection_and_timing_edge_reconciles_with_trial_and_diagnostics():
    ledger = InMemoryTrialLedger()
    report = RelativeStrengthResearchSprint(ledger=ledger).run(_inputs(120.0, 210.0))

    assert report.status is SprintStatus.INSUFFICIENT_DATA
    assert report.attribution is not None
    assert report.attribution.reconciles is True
    assert report.attribution.components["selection_increment"] > 0
    assert report.attribution.components["timing_increment"] > 0
    assert len(ledger.all()) == 1

    ablations = AblationRunner().run(
        _candidate().strategy,
        lambda _strategy, kind: {"expectancy_r": 0.4 if kind is AblationKind.FULL else 0.2},
        kinds=(AblationKind.FULL, AblationKind.FULL_MINUS_SECTOR_FILTER),
    )
    assert len(ablations) == 2
    assert ablations[0].strategy_key == "relative_strength_breakout@1.0.0"

    stability = analyze_parameter_stability(
        [
            ParameterPoint(parameter_value=5, expectancy_r=0.28, sample_size=250),
            ParameterPoint(parameter_value=6, expectancy_r=0.31, sample_size=250),
            ParameterPoint(parameter_value=7, expectancy_r=0.30, sample_size=250),
        ]
    )
    assert stability.stability_score > 0


def test_golden_negative_selection_edge_is_preserved():
    result = EdgeAttributionEngine().attribute(
        strategy_return=0.02,
        next_open_return=0.03,
        sector_return=0.08,
        market_return=0.01,
    )
    assert result.components["selection_increment"] < 0
    assert result.components["timing_increment"] < 0
    assert result.reconciles is True
