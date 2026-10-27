from datetime import UTC, date, datetime

from morning_alpha.models import StrategyKey
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.population import CandidateDecisionState, CandidateObservation, PopulationBuildResult, candidate_identity
from morning_alpha.research.validation import PopulationValidator, ValidationCode

TS = datetime(2024, 7, 10, 13, 0, tzinfo=UTC)
STRATEGY = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")


def _obs(*, manifest="d" * 64, feature_snapshot=None, stable_id="SEC-1"):
    return CandidateObservation(candidate_id=candidate_identity(STRATEGY, stable_id, TS),campaign_id="morning_alpha_v1",strategy=STRATEGY,stable_security_id=stable_id,symbol="AAA",decision_timestamp=TS,trading_date=date(2024, 7, 10),sector="Technology",sector_etf="XLK",decision_state=CandidateDecisionState.REJECTED,rejection_reason="DETECTOR_REJECTED",feature_hash="f" * 64,universe_hash="u" * 64,data_manifest_hash=manifest,source_lineage_hash="s" * 64,feature_snapshot=feature_snapshot or {})


def _result(obs=None, **updates):
    row = obs or _obs()
    data = dict(decision_timestamp=TS,observations=(row,),input_universe_count=1,qualified_count=0,rejected_count=1,rejection_counts={"DETECTOR_REJECTED": 1},universe_hash="u" * 64,population_hash="p" * 64)
    data.update(updates)
    return PopulationBuildResult(**data)


def _ready(ready=True):
    return DataReadinessReport(ready=ready,root="fixture",file_count=1,symbols=("AAA",),reasons=() if ready else ("MANIFEST_INVALID",))


def _codes(report):
    return {issue.code for issue in report.issues}


def test_validator_rejects_uncertified_data_and_manifest_mismatch():
    report = PopulationValidator().validate(_result(),readiness=_ready(False),expected_manifest_hash="x" * 64)
    assert ValidationCode.DATA_NOT_CERTIFIED in _codes(report)
    assert ValidationCode.MANIFEST_IDENTITY_MISMATCH in _codes(report)
    assert not report.valid


def test_validator_detects_temporal_leakage_and_benchmark_misalignment():
    feature = {"latest_source_timestamp": "2024-07-10T14:00:00Z","lineage": {"stock_endpoint": "2024-07-09T20:00:00Z","spy_endpoint": "2024-07-08T20:00:00Z","sector_endpoint": "2024-07-09T20:00:00Z"}}
    report = PopulationValidator().validate(_result(_obs(feature_snapshot=feature)))
    assert ValidationCode.TEMPORAL_LEAKAGE in _codes(report)
    assert ValidationCode.BENCHMARK_ALIGNMENT_FAILED in _codes(report)


def test_validator_detects_duplicates_and_accounting_even_on_unchecked_model():
    row = _obs()
    invalid = PopulationBuildResult.model_construct(decision_timestamp=TS,observations=(row, row),input_universe_count=3,qualified_count=0,rejected_count=1,rejection_counts={"DETECTOR_REJECTED": 1},universe_hash="u" * 64,population_hash="p" * 64)
    report = PopulationValidator().validate(invalid)
    assert ValidationCode.DUPLICATE_CANDIDATE in _codes(report)
    assert ValidationCode.ACCOUNTING_MISMATCH in _codes(report)


def test_validator_detects_nondeterministic_repeat_runs():
    first = _result()
    second = first.model_copy(update={"population_hash": "q" * 64})
    report = PopulationValidator().validate(second, repeat_reference=first)
    assert ValidationCode.NON_DETERMINISTIC_RESEARCH in _codes(report)
    assert not report.valid


def test_validator_accepts_clean_population():
    report = PopulationValidator().validate(_result(), readiness=_ready(True), expected_manifest_hash="d" * 64)
    assert report.valid
    assert report.issues == ()
