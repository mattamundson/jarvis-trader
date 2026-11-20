from datetime import UTC, date, datetime

from morning_alpha.models import StrategyKey
from morning_alpha.research.candidate_store import CandidatePopulationWriter, verify_population_artifact
from morning_alpha.research.population import CandidateDecisionState, CandidateObservation, PopulationBuildResult, candidate_identity

TS = datetime(2024, 7, 10, 13, 0, tzinfo=UTC)
STRATEGY = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")


def _result(*, feature_hash="f" * 64, manifest_hash="d" * 64, population_hash="p" * 64):
    obs = CandidateObservation(candidate_id=candidate_identity(STRATEGY,"SEC-1",TS),campaign_id="morning_alpha_v1",strategy=STRATEGY,stable_security_id="SEC-1",symbol="AAA",decision_timestamp=TS,trading_date=date(2024,7,10),sector="Technology",sector_etf="XLK",decision_state=CandidateDecisionState.REJECTED,rejection_reason="DETECTOR_REJECTED",feature_hash=feature_hash,universe_hash="u"*64,data_manifest_hash=manifest_hash,source_lineage_hash="s"*64,feature_snapshot={"returns_20d":0.12})
    return PopulationBuildResult(decision_timestamp=TS,observations=(obs,),input_universe_count=1,qualified_count=0,rejected_count=1,rejection_counts={"DETECTOR_REJECTED":1},universe_hash="u"*64,population_hash=population_hash)


def test_identical_population_writes_have_identical_content_hash(tmp_path):
    writer=CandidatePopulationWriter()
    first=writer.write(_result(),tmp_path/"a",code_commit="abc123",split_registry_hash="s"*64)
    second=writer.write(_result(),tmp_path/"b",code_commit="abc123",split_registry_hash="s"*64)
    assert first.content_sha256==second.content_sha256
    assert first.population_identity==second.population_identity


def test_feature_or_manifest_change_changes_population_identity(tmp_path):
    writer=CandidatePopulationWriter()
    baseline=writer.write(_result(),tmp_path/"base",code_commit="abc123",split_registry_hash="s"*64)
    changed_feature=writer.write(_result(feature_hash="g"*64,population_hash="q"*64),tmp_path/"feature",code_commit="abc123",split_registry_hash="s"*64)
    changed_manifest=writer.write(_result(manifest_hash="m"*64,population_hash="r"*64),tmp_path/"manifest",code_commit="abc123",split_registry_hash="s"*64)
    assert baseline.population_identity != changed_feature.population_identity
    assert baseline.population_identity != changed_manifest.population_identity


def test_artifact_tamper_is_detected(tmp_path):
    root=tmp_path/"population"
    manifest=CandidatePopulationWriter().write(_result(),root,code_commit="abc123",split_registry_hash="s"*64)
    assert verify_population_artifact(root,manifest)
    artifact=root/manifest.candidates_path
    artifact.write_text(artifact.read_text()+"tampered\n")
    assert not verify_population_artifact(root,manifest)
