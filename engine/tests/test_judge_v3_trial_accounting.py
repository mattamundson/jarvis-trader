"""Tests for Judge V3 preregistered campaign trial-count diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backtest.judge_v3_trial_accounting import (
    dsr_trial_count_for_review,
    trial_accounting_diagnostic,
)
from backtest.research_trial_ledger import TrialLedger


def _time(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _plan(ledger: TrialLedger, trial_id: str, family: str, minute: int) -> None:
    ledger.append_plan(
        event_id=f"plan-{trial_id}",
        trial_id=trial_id,
        created_at=_time(minute),
        strategy_family=family,
        parameters={"p": minute},
        feature_ids=["stc_main_v2"],
        data_fingerprint="data",
        code_commit="abc123",
        evaluation_plan={"metric": "pf"},
    )


def test_honest_trial_count_uses_preregistered_campaign_when_larger(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    for i in range(5):
        _plan(ledger, f"m-{i}", "momentum", i)

    diag = trial_accounting_diagnostic(
        ledger, strategy_family="momentum", gate_n_trials=3
    )
    assert diag.planned_trials == 5
    assert diag.honest_n_trials == 5
    assert diag.undercount == 2
    assert diag.inflation_factor == 5 / 3
    assert diag.gate_understates_campaign is True
    assert dsr_trial_count_for_review(
        ledger, strategy_family="momentum", gate_n_trials=3
    ) == 5


def test_runner_count_remains_floor_when_ledger_has_fewer_trials(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    _plan(ledger, "m-1", "momentum", 0)

    diag = trial_accounting_diagnostic(
        ledger, strategy_family="momentum", gate_n_trials=9
    )
    assert diag.honest_n_trials == 9
    assert diag.undercount == 0
    assert diag.inflation_factor == 1.0
    assert diag.gate_understates_campaign is False


def test_family_filter_does_not_mix_unrelated_research_campaigns(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    for i in range(4):
        _plan(ledger, f"m-{i}", "momentum", i)
    for i in range(7):
        _plan(ledger, f"v-{i}", "vwap", 10 + i)

    momentum = trial_accounting_diagnostic(
        ledger, strategy_family="momentum", gate_n_trials=1
    )
    vwap = trial_accounting_diagnostic(
        ledger, strategy_family="vwap", gate_n_trials=1
    )
    assert momentum.planned_trials == 4
    assert vwap.planned_trials == 7


def test_completion_fraction_comes_from_results_not_plans(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    for i in range(4):
        _plan(ledger, f"m-{i}", "momentum", i)
    for i in range(2):
        ledger.append_result(
            event_id=f"result-m-{i}",
            trial_id=f"m-{i}",
            created_at=_time(20 + i),
            metrics={"pf": 1.1 + i},
            status="completed",
        )

    diag = trial_accounting_diagnostic(
        ledger, strategy_family="momentum", gate_n_trials=1
    )
    assert diag.planned_trials == 4
    assert diag.completed_trials == 2
    assert diag.completion_fraction == 0.5


def test_empty_family_does_not_invent_trials(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    diag = trial_accounting_diagnostic(
        ledger, strategy_family="unknown", gate_n_trials=3
    )
    assert diag.planned_trials == 0
    assert diag.honest_n_trials == 3
    assert diag.completion_fraction == 0.0
