from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from morning_alpha.research.oos import LockedOOSEvaluator, OOSIdentity, OOSLockSpec

NY = ZoneInfo("America/New_York")


def _spec():
    return OOSLockSpec(campaign_id="morning_alpha_v1",strategy_key="relative_strength_breakout@1.0.0",parameter_hash="a"*64,trigger_version="prior_day_high@1",exit_version="2r_stop@1",data_manifest_hash="b"*64,candidate_population_hash="c"*64,trial_ledger_hash="d"*64,trial_count=17,development_start=date(2018,1,1),development_end=date(2021,12,31),validation_start=date(2022,1,1),validation_end=date(2023,12,31),oos_start=date(2024,1,1),oos_end=date(2025,12,31),purge_sessions=20,embargo_sessions=20,code_commit="deadbeef",locked_at=datetime(2026,1,1,9,tzinfo=NY))


def test_oos_lock_rejects_overlapping_intervals():
    payload=_spec().model_dump(); payload["validation_end"]=date(2024,2,1)
    with pytest.raises(ValueError,match="OOS_INTERVAL_OVERLAP"):
        OOSLockSpec.model_validate(payload)


def test_oos_lock_hash_is_deterministic_and_sensitive_to_identity():
    a=_spec().seal(); b=_spec().seal(); assert a.lock_hash==b.lock_hash
    changed=_spec().model_copy(update={"parameter_hash":"f"*64}).seal(); assert changed.lock_hash!=a.lock_hash


def test_locked_evaluator_rejects_mismatched_identity_before_running():
    lock=_spec().seal(); calls=[]; evaluator=LockedOOSEvaluator(lock)
    identity=OOSIdentity(strategy_key=lock.strategy_key,parameter_hash="f"*64,data_manifest_hash=lock.data_manifest_hash,candidate_population_hash=lock.candidate_population_hash,trial_ledger_hash=lock.trial_ledger_hash,trial_count=lock.trial_count,code_commit=lock.code_commit)
    with pytest.raises(ValueError,match="OOS_IDENTITY_MISMATCH"):
        evaluator.evaluate(identity,lambda:calls.append("ran") or {"expectancy":1.0})
    assert calls==[]


def test_locked_evaluator_runs_when_identity_matches_and_binds_result_to_lock():
    lock=_spec().seal(); result=LockedOOSEvaluator(lock).evaluate(lock.identity,lambda:{"expectancy":0.25,"n":205})
    assert result.lock_hash==lock.lock_hash and result.metrics=={"expectancy":0.25,"n":205} and len(result.evidence_hash)==64
