from datetime import UTC, datetime, timedelta

from morning_alpha.models import MarketBar, Session, SetupCandidate, StrategyKey
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.controls import UniverseMember
from morning_alpha.research.relative_strength_sprint import (
    RelativeStrengthResearchSprint,
    RelativeStrengthSprintInput,
    SprintStatus,
)
from morning_alpha.research.trial_ledger import InMemoryTrialLedger

AS_OF = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)


def candidate():
    return SetupCandidate(
        symbol="AAA",
        strategy=StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        as_of=AS_OF,
        side="long",
        setup_type="relative_strength_breakout",
        thesis_code="rs_breakout",
        proposed_entry=100.0,
        proposed_stop=98.0,
        sector="Technology",
    )


def readiness(ready=True):
    return DataReadinessReport(
        ready=ready,
        file_stage_ready=ready,
        manifest_present=ready,
        root="/research",
        file_count=10 if ready else 0,
        symbols=("AAA", "BBB", "SPY", "XLK") if ready else (),
        providers=("fixture",) if ready else (),
        daily_symbol_count=500 if ready else 0,
        intraday_symbol_count=100 if ready else 0,
        reasons=() if ready else ("DATA_ROOT_MISSING",),
    )


def member(symbol, sector="Technology"):
    return UniverseMember(
        symbol=symbol,
        sector=sector,
        effective_from=AS_OF - timedelta(days=365),
        effective_to=None,
        eligible=True,
    )


def bar(symbol, day, open_, close):
    ts = AS_OF + timedelta(days=day, minutes=30)
    return MarketBar(
        symbol=symbol,
        timestamp=ts,
        open=open_,
        high=max(open_, close) + 0.5,
        low=min(open_, close) - 0.5,
        close=close,
        volume=1_000_000,
        session=Session.RTH,
        source="fixture",
        ingested_at=ts,
    )


def synthetic_bars():
    return {
        "AAA": tuple(bar("AAA", day, 100 + day, 101 + day * 2) for day in range(0, 7)),
        "BBB": tuple(bar("BBB", day, 50 + day, 50.5 + day) for day in range(0, 7)),
        "SPY": tuple(bar("SPY", day, 400 + day, 401 + day) for day in range(0, 7)),
        "XLK": tuple(bar("XLK", day, 200 + day, 201 + day * 1.2) for day in range(0, 7)),
    }


def sprint_input(ready=True):
    return RelativeStrengthSprintInput(
        readiness=readiness(ready),
        candidate=candidate(),
        universe=(member("BBB"),),
        sector_etf="XLK",
        bars_by_symbol=synthetic_bars(),
        data_manifest_hash="a" * 64,
        sample_start=AS_OF,
        sample_end=AS_OF + timedelta(days=6),
    )


def test_uncertified_data_blocks_before_trial_or_control_research():
    ledger = InMemoryTrialLedger()
    report = RelativeStrengthResearchSprint(ledger=ledger).run(sprint_input(False))

    assert report.status is SprintStatus.BLOCKED
    assert report.reasons == ("DATA_ROOT_MISSING",)
    assert ledger.all() == ()


def test_synthetic_ready_fixture_emits_explicit_control_counts_and_attribution():
    ledger = InMemoryTrialLedger()
    report = RelativeStrengthResearchSprint(ledger=ledger).run(sprint_input(True))

    assert report.strategy_key == "relative_strength_breakout@1.0.0"
    assert report.status is SprintStatus.INSUFFICIENT_DATA
    assert report.control_counts["random_universe"] == 1
    assert report.control_counts["random_same_sector"] == 1
    assert report.control_counts["next_open"] == 1
    assert report.control_counts["spy"] == 1
    assert report.control_counts["sector_etf"] == 1
    assert report.attribution is not None
    assert report.attribution.reconciles is True
    assert len(report.trial_ids) == 1
    assert len(ledger.all()) == 1


def test_sprint_rejects_non_frozen_strategy_version():
    wrong = sprint_input(True).model_copy(
        update={
            "candidate": candidate().model_copy(
                update={"strategy": StrategyKey(strategy_id="relative_strength_breakout", version="1.1.0")}
            )
        }
    )

    try:
        RelativeStrengthResearchSprint().run(wrong)
    except ValueError as exc:
        assert "relative_strength_breakout@1.0.0" in str(exc)
    else:
        raise AssertionError("expected frozen strategy identity rejection")


def test_missing_sector_benchmark_yields_insufficient_data_not_false_pass():
    inp = sprint_input(True).model_copy(update={"sector_etf": None})
    report = RelativeStrengthResearchSprint().run(inp)
    assert report.status is SprintStatus.INSUFFICIENT_DATA
    assert report.attribution is None
    assert "ATTRIBUTION_INPUT_MISSING" in report.reasons
