from datetime import UTC, datetime

from morning_alpha.research.campaign import DataReadinessReport, ResearchCampaignSpec
from morning_alpha.research.campaign_runner import (
    CampaignRunStatus,
    FamilyRunState,
    FamilyResearchResult,
    ResearchCampaignRunner,
)


def ready_report() -> DataReadinessReport:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    return DataReadinessReport(
        ready=True,
        file_stage_ready=True,
        manifest_present=True,
        root="/research",
        file_count=1000,
        symbols=("SPY",),
        providers=("fixture",),
        daily_symbol_count=800,
        intraday_symbol_count=250,
        earliest_timestamp=now,
        latest_timestamp=now,
        earliest_intraday_timestamp=now,
        latest_intraday_timestamp=now,
        reasons=(),
    )


def blocked_report() -> DataReadinessReport:
    return DataReadinessReport(
        ready=False,
        root="/research",
        file_count=0,
        symbols=(),
        reasons=("NO_BAR_FILES", "MANIFEST_MISSING"),
    )


def test_campaign_blocks_before_any_executor_call_when_data_not_ready():
    calls: list[str] = []

    def executor(strategy, spec):
        calls.append(strategy.canonical)
        raise AssertionError("executor must not run")

    result = ResearchCampaignRunner().run(blocked_report(), executor)
    assert result.status is CampaignRunStatus.BLOCKED
    assert calls == []
    assert all(row.state is FamilyRunState.BLOCKED for row in result.families)
    assert result.stopped_reason == "NO_BAR_FILES,MANIFEST_MISSING"


def test_campaign_runs_exact_frozen_strategy_order():
    calls: list[str] = []

    def executor(strategy, spec):
        calls.append(strategy.canonical)
        return FamilyResearchResult(
            strategy_key=strategy.canonical,
            state=FamilyRunState.COMPLETED,
            evidence={"campaign": spec.campaign_id},
        )

    spec = ResearchCampaignSpec()
    result = ResearchCampaignRunner(spec).run(ready_report(), executor)
    assert result.status is CampaignRunStatus.COMPLETED
    assert calls == [key.canonical for key in spec.strategies]
    assert [row.strategy_key for row in result.families] == calls


def test_campaign_stops_after_first_family_failure_and_does_not_execute_remaining():
    spec = ResearchCampaignSpec()
    calls: list[str] = []

    def executor(strategy, _spec):
        calls.append(strategy.canonical)
        if len(calls) == 2:
            raise RuntimeError("provider unavailable")
        return FamilyResearchResult(
            strategy_key=strategy.canonical,
            state=FamilyRunState.COMPLETED,
        )

    result = ResearchCampaignRunner(spec).run(ready_report(), executor)
    assert result.status is CampaignRunStatus.FAILED
    assert calls == [key.canonical for key in spec.strategies[:2]]
    assert result.families[0].state is FamilyRunState.COMPLETED
    assert result.families[1].state is FamilyRunState.FAILED
    assert all(row.state is FamilyRunState.SKIPPED for row in result.families[2:])
    assert "provider unavailable" in (result.stopped_reason or "")


def test_campaign_rejects_executor_result_for_wrong_strategy_key():
    spec = ResearchCampaignSpec()

    def executor(strategy, _spec):
        return FamilyResearchResult(
            strategy_key="wrong@1.0.0",
            state=FamilyRunState.COMPLETED,
        )

    result = ResearchCampaignRunner(spec).run(ready_report(), executor)
    assert result.status is CampaignRunStatus.FAILED
    assert result.families[0].state is FamilyRunState.FAILED
    assert "mismatched strategy key" in (result.stopped_reason or "")
