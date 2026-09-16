from datetime import UTC, date, datetime

from morning_alpha.cli import main
from morning_alpha.models import StrategyKey
from morning_alpha.research.candidate_store import CandidatePopulationWriter
from morning_alpha.research.population import CandidateDecisionState, CandidateObservation, PopulationBuildResult, candidate_identity
from morning_alpha.research.population_report import build_population_diagnostics, render_population_report
from morning_alpha.research.validation import PopulationValidator

TS=datetime(2024,7,10,13,0,tzinfo=UTC)
STRATEGY=StrategyKey(strategy_id="relative_strength_breakout",version="1.0.0")


def _result():
    rows=[]
    for stable,symbol,state,reason,sector in [("SEC-1","AAA",CandidateDecisionState.QUALIFIED,None,"Technology"),("SEC-2","BBB",CandidateDecisionState.REJECTED,"DETECTOR_REJECTED","Technology")]:
        detector=None
        if state is CandidateDecisionState.QUALIFIED:
            from morning_alpha.models import SetupCandidate
            detector=SetupCandidate(symbol=symbol,strategy=STRATEGY,as_of=TS,side="long",setup_type="relative_strength_breakout",thesis_code="RS",proposed_entry=101,proposed_stop=99,sector=sector)
        rows.append(CandidateObservation(candidate_id=candidate_identity(STRATEGY,stable,TS),campaign_id="morning_alpha_v1",strategy=STRATEGY,stable_security_id=stable,symbol=symbol,decision_timestamp=TS,trading_date=date(2024,7,10),sector=sector,sector_etf="XLK",decision_state=state,rejection_reason=reason,feature_hash=("f" if stable=="SEC-1" else "g")*64,universe_hash="u"*64,data_manifest_hash="d"*64,source_lineage_hash="s"*64,feature_snapshot={},detector_candidate=detector))
    return PopulationBuildResult(decision_timestamp=TS,observations=tuple(rows),input_universe_count=2,qualified_count=1,rejected_count=1,rejection_counts={"DETECTOR_REJECTED":1},universe_hash="u"*64,population_hash="p"*64)


def test_population_report_contains_required_sections_and_no_edge_claim():
    result=_result(); validation=PopulationValidator().validate(result,expected_manifest_hash="d"*64); diagnostics=build_population_diagnostics(result); text=render_population_report(result,validation,diagnostics)
    for section in ("POPULATION IDENTITY","ACCOUNTING","VALIDATION","DISTRIBUTION","RESEARCH STATUS"):
        assert section in text
    assert "POPULATION_VALIDATED" in text
    assert "EDGE CONFIRMED" not in text.upper()


def test_population_diagnostics_reconcile_counts():
    diagnostics=build_population_diagnostics(_result())
    assert diagnostics.by_state=={"qualified":1,"rejected":1}
    assert diagnostics.by_rejection=={"DETECTOR_REJECTED":1}
    assert diagnostics.by_sector=={"Technology":2}
    assert diagnostics.by_symbol=={"AAA":1,"BBB":1}
    assert diagnostics.by_month=={"2024-07":2}
    assert diagnostics.by_year=={"2024":2}


def test_population_validate_cli_returns_zero_for_valid_artifact(tmp_path,capsys):
    root=tmp_path/"pop"; CandidatePopulationWriter().write(_result(),root,code_commit="abc",split_registry_hash="s"*64)
    rc=main(["research-population-validate","--population-manifest",str(root/"population_manifest.json"),"--json"]); output=capsys.readouterr().out
    assert rc==0
    assert '"status": "POPULATION_VALIDATED"' in output
    assert "EDGE CONFIRMED" not in output.upper()


def test_population_validate_cli_fails_on_tampered_artifact(tmp_path,capsys):
    root=tmp_path/"pop"; manifest=CandidatePopulationWriter().write(_result(),root,code_commit="abc",split_registry_hash="s"*64); (root/manifest.candidates_path).write_text("tampered\n")
    rc=main(["research-population-validate","--population-manifest",str(root/"population_manifest.json"),"--json"]); output=capsys.readouterr().out
    assert rc==2
    assert '"status": "POPULATION_INVALID"' in output
    assert "EDGE CONFIRMED" not in output.upper()
