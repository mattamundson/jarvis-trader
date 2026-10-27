from datetime import datetime, timedelta, timezone

from morning_alpha.models import StrategyKey
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.candidate_store import CandidatePopulationWriter, verify_population_artifact
from morning_alpha.research.oos import LockedOOSEvaluator, OOSIdentity, OOSLockSpec
from morning_alpha.research.population import (
    CandidateDecisionState,
    CandidateObservation,
    PopulationBuildResult,
    candidate_identity,
)
from morning_alpha.research.red_team import RedTeamCase, RedTeamStatus, run_red_team
from morning_alpha.research.validation import PopulationValidator

TS = datetime(2024, 7, 10, 9, tzinfo=timezone.utc)
STRATEGY = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")
H = "a" * 64


def _ready(ok=True):
    return DataReadinessReport(ready=ok, root="fixture", file_count=1, symbols=("AAA",), reasons=() if ok else ("PIT_UNIVERSE_UNCERTIFIED",))


def _row(**updates):
    base = dict(
        candidate_id=candidate_identity(STRATEGY, "SEC-1", TS),
        campaign_id="campaign",
        strategy=STRATEGY,
        stable_security_id="SEC-1",
        symbol="AAA",
        decision_timestamp=TS,
        trading_date=TS.date(),
        sector="Technology",
        sector_etf="XLK",
        decision_state=CandidateDecisionState.REJECTED,
        rejection_reason="DETECTOR_REJECTED",
        feature_hash="f" * 64,
        universe_hash="u" * 64,
        data_manifest_hash="d" * 64,
        source_lineage_hash="s" * 64,
        feature_snapshot={
            "latest_source_timestamp": (TS - timedelta(minutes=1)).isoformat(),
            "lineage": {
                "stock_endpoint": (TS - timedelta(days=1)).isoformat(),
                "spy_endpoint": (TS - timedelta(days=1)).isoformat(),
                "sector_endpoint": (TS - timedelta(days=1)).isoformat(),
            },
        },
        detector_candidate=None,
        listing_timestamp=TS - timedelta(days=1000),
        sector_effective_from=TS - timedelta(days=1000),
        market_data_timestamp=TS - timedelta(minutes=1),
    )
    base.update(updates)
    return CandidateObservation(**base)


def _result(row=None):
    row = row or _row()
    return PopulationBuildResult(
        decision_timestamp=TS,
        observations=(row,),
        source_record_count=1,
        input_universe_count=1,
        qualified_count=0,
        rejected_count=1,
        rejection_counts={"DETECTOR_REJECTED": 1},
        universe_hash="u" * 64,
        population_hash="p" * 64,
    )


def _validation_code(result, *, readiness=None, manifest="d" * 64):
    report = PopulationValidator().validate(result, readiness=readiness, expected_manifest_hash=manifest)
    return report.issues[0].code.value if report.issues else None


def _value_error_code(fn):
    try:
        fn()
    except ValueError as exc:
        return str(exc).split(":", 1)[0]
    return None


def test_red_team_catches_all_mandatory_corruption_classes(tmp_path):
    valid = _result()

    future_bar = valid.model_copy(update={
        "observations": (valid.observations[0].model_copy(update={
            "feature_snapshot": {"latest_source_timestamp": (TS + timedelta(seconds=1)).isoformat()}
        }),)
    })
    future_available = valid.model_copy(update={
        "observations": (valid.observations[0].model_copy(update={"market_data_timestamp": TS + timedelta(seconds=1)}),)
    })
    future_listing = valid.model_copy(update={
        "observations": (valid.observations[0].model_copy(update={"listing_timestamp": TS + timedelta(days=1)}),)
    })
    expired_sector = valid.model_copy(update={
        "observations": (valid.observations[0].model_copy(update={"sector_effective_to": TS}),)
    })
    shifted_benchmark = valid.model_copy(update={
        "observations": (valid.observations[0].model_copy(update={
            "feature_snapshot": {
                "latest_source_timestamp": (TS - timedelta(minutes=1)).isoformat(),
                "lineage": {
                    "stock_endpoint": (TS - timedelta(days=1)).isoformat(),
                    "spy_endpoint": (TS - timedelta(days=2)).isoformat(),
                    "sector_endpoint": (TS - timedelta(days=1)).isoformat(),
                },
            }
        }),)
    })
    duplicate = valid.model_copy(update={
        "observations": (valid.observations[0], valid.observations[0]),
        "input_universe_count": 2,
        "source_record_count": 2,
        "rejected_count": 2,
        "rejection_counts": {"DETECTOR_REJECTED": 2},
    })
    manifest_mismatch = valid.model_copy(update={
        "observations": (valid.observations[0].model_copy(update={"data_manifest_hash": "x" * 64}),)
    })

    artifact_dir = tmp_path / "population"
    manifest = CandidatePopulationWriter().write(valid, artifact_dir, code_commit="abc", split_registry_hash=H)
    (artifact_dir / "candidates.jsonl").write_text("tampered\n", encoding="utf-8")

    membership_dir = tmp_path / "membership"
    membership_manifest = CandidatePopulationWriter().write(valid, membership_dir, code_commit="abc", split_registry_hash=H)
    (membership_dir / "membership_rejections.jsonl").write_text("tampered\n", encoding="utf-8")

    overlap_probe = lambda: OOSLockSpec(
        campaign_id="c", strategy_key="s", parameter_hash=H, trigger_version="t", exit_version="e",
        data_manifest_hash=H, candidate_population_hash=H, trial_ledger_hash=H, trial_count=1,
        development_start=TS.date(), development_end=TS.date()+timedelta(days=10),
        validation_start=TS.date()+timedelta(days=10), validation_end=TS.date()+timedelta(days=20),
        oos_start=TS.date()+timedelta(days=21), oos_end=TS.date()+timedelta(days=30),
        purge_sessions=1, embargo_sessions=1, code_commit="abc", locked_at=TS,
    )

    lock = OOSLockSpec(
        campaign_id="c", strategy_key="s", parameter_hash=H, trigger_version="t", exit_version="e",
        data_manifest_hash=H, candidate_population_hash=H, trial_ledger_hash=H, trial_count=1,
        development_start=TS.date(), development_end=TS.date()+timedelta(days=9),
        validation_start=TS.date()+timedelta(days=10), validation_end=TS.date()+timedelta(days=20),
        oos_start=TS.date()+timedelta(days=21), oos_end=TS.date()+timedelta(days=30),
        purge_sessions=1, embargo_sessions=1, code_commit="abc", locked_at=TS,
    ).seal()
    changed_identity = OOSIdentity(
        strategy_key="s", parameter_hash="b"*64, data_manifest_hash=H,
        candidate_population_hash=H, trial_ledger_hash=H, trial_count=1, code_commit="abc",
    )

    cases = (
        RedTeamCase("future_price_bar", "TEMPORAL_LEAKAGE", lambda: _validation_code(future_bar)),
        RedTeamCase("future_available_at", "TEMPORAL_LEAKAGE", lambda: _validation_code(future_available)),
        RedTeamCase("survivor_universe_substitution", "DATA_NOT_CERTIFIED", lambda: _validation_code(valid, readiness=_ready(False))),
        RedTeamCase("future_listing", "TEMPORAL_LEAKAGE", lambda: _validation_code(future_listing)),
        RedTeamCase("expired_sector_membership", "TEMPORAL_LEAKAGE", lambda: _validation_code(expired_sector)),
        RedTeamCase("benchmark_endpoint_shift", "BENCHMARK_ALIGNMENT_FAILED", lambda: _validation_code(shifted_benchmark)),
        RedTeamCase("duplicate_candidate", "DUPLICATE_CANDIDATE", lambda: _validation_code(duplicate)),
        RedTeamCase("manifest_identity_change", "MANIFEST_IDENTITY_MISMATCH", lambda: _validation_code(manifest_mismatch)),
        RedTeamCase("candidate_artifact_tamper", "ARTIFACT_HASH_MISMATCH", lambda: None if verify_population_artifact(artifact_dir, manifest) else "ARTIFACT_HASH_MISMATCH"),
        RedTeamCase("membership_artifact_tamper", "ARTIFACT_HASH_MISMATCH", lambda: None if verify_population_artifact(membership_dir, membership_manifest) else "ARTIFACT_HASH_MISMATCH"),
        RedTeamCase("oos_interval_overlap", "OOS_INTERVAL_OVERLAP", lambda: _value_error_code(overlap_probe)),
        RedTeamCase("oos_parameter_mutation", "OOS_IDENTITY_MISMATCH", lambda: _value_error_code(lambda: LockedOOSEvaluator(lock).evaluate(changed_identity, lambda: {"x": 1}))),
    )

    report = run_red_team(cases)
    assert report.status is RedTeamStatus.VERIFIED
    assert report.total_cases == 12
    assert report.caught_cases == 12
    assert all(case.caught for case in report.results)


def test_red_team_fails_when_expected_detector_is_not_observed():
    report = run_red_team((RedTeamCase("miss", "EXPECTED", lambda: None),))
    assert report.status is RedTeamStatus.FAILED
    assert report.results[0].caught is False
