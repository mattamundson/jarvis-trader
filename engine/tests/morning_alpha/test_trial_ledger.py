from datetime import UTC, datetime

import pytest

from morning_alpha.research.trial_ledger import InMemoryTrialLedger, ResearchTrial, TrialStatus

START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2025, 12, 31, tzinfo=UTC)


def build(**overrides):
    values = dict(
        campaign_id="morning_alpha_v1",
        strategy_key="relative_strength_breakout@1.0.0",
        control_version="controls@1.0.0",
        trigger_version="prior_day_high@1.0.0",
        exit_version="stop_2r@1.0.0",
        ablation_kind="full",
        parameter_fingerprint="sha256:params-a",
        cost_bps=5,
        data_manifest_hash="a" * 64,
        sample_start=START,
        sample_end=END,
        status=TrialStatus.COMPLETED,
        sample_size=250,
    )
    values.update(overrides)
    return ResearchTrial.build(**values)


def test_identical_experiment_identity_generates_same_trial_id():
    assert build().trial_id == build().trial_id


def test_changing_trigger_or_cost_changes_trial_id():
    base = build()
    trigger = build(trigger_version="orb_15m@1.0.0")
    cost = build(cost_bps=10)
    assert len({base.trial_id, trigger.trial_id, cost.trial_id}) == 3


def test_failed_trial_remains_queryable_after_later_success():
    ledger = InMemoryTrialLedger()
    failed = build(
        trigger_version="orb_5m@1.0.0",
        status=TrialStatus.FAILED,
        sample_size=0,
        error="fixture failure",
    )
    successful = build(trigger_version="orb_15m@1.0.0")

    ledger.append(failed)
    ledger.append(successful)

    assert ledger.get(failed.trial_id) == failed
    assert ledger.get(failed.trial_id).status is TrialStatus.FAILED
    assert ledger.get(successful.trial_id).status is TrialStatus.COMPLETED
    assert len(ledger.all()) == 2


def test_ledger_is_append_only_for_same_trial_identity():
    ledger = InMemoryTrialLedger()
    trial = build()
    ledger.append(trial)
    with pytest.raises(ValueError, match="already recorded"):
        ledger.append(trial)


def test_result_fields_do_not_change_identity():
    completed = build(output_hash="b" * 64, output_path="reports/run.json")
    failed_same_identity = build(status=TrialStatus.FAILED, sample_size=0, error="failed")
    assert completed.trial_id == failed_same_identity.trial_id


def test_sample_interval_must_be_ordered():
    with pytest.raises(ValueError, match="sample_end"):
        build(sample_start=END, sample_end=START)
