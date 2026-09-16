import json

from morning_alpha.cli import main
from morning_alpha.research.acquisition import (
    RESEARCH_ACQUISITION_PLAN_V1,
    preferred_source_for,
)
from morning_alpha.research.campaign import ResearchArtifactKind


def test_acquisition_plan_covers_every_required_artifact_kind():
    kinds = {requirement.kind for requirement in RESEARCH_ACQUISITION_PLAN_V1}
    assert kinds == set(ResearchArtifactKind)
    assert all(requirement.required_fields for requirement in RESEARCH_ACQUISITION_PLAN_V1)
    assert all(requirement.sources for requirement in RESEARCH_ACQUISITION_PLAN_V1)


def test_point_in_time_reference_artifacts_prefer_databento():
    for kind in (
        ResearchArtifactKind.UNIVERSE_MEMBERSHIP,
        ResearchArtifactKind.DELISTED_SYMBOLS,
        ResearchArtifactKind.CORPORATE_ACTIONS,
        ResearchArtifactKind.SECTOR_HISTORY,
    ):
        source = preferred_source_for(kind)
        assert source.provider == "Databento Reference"
        assert source.point_in_time is True


def test_historical_earnings_prefers_report_date_consensus_source():
    source = preferred_source_for(ResearchArtifactKind.EARNINGS_EVENTS)
    assert source.provider == "Zacks Data"
    assert "consensus_on_report_date" in source.capabilities
    assert "report_date" in source.capabilities


def test_market_bars_and_premarket_prefer_massive():
    for kind in (
        ResearchArtifactKind.DAILY_BARS,
        ResearchArtifactKind.INTRADAY_BARS,
        ResearchArtifactKind.PREMARKET_BARS,
    ):
        assert preferred_source_for(kind).provider == "Massive"


def test_cli_research_source_plan_is_machine_readable(capsys):
    rc = main(["research-source-plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["plan_version"] == "1.0.0"
    assert len(payload["artifacts"]) == len(ResearchArtifactKind)
    earnings = next(row for row in payload["artifacts"] if row["kind"] == "earnings_events")
    assert earnings["sources"][0]["provider"] == "Zacks Data"
