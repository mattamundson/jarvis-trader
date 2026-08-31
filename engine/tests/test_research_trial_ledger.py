"""Adversarial tests for the append-only research trial ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backtest.research_trial_ledger import (
    TrialLedger,
    TrialLedgerError,
    TrialLedgerIntegrityError,
)


def _time(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _plan(ledger: TrialLedger, trial_id: str = "trial-1", event_id: str = "plan-1") -> None:
    ledger.append_plan(
        event_id=event_id,
        trial_id=trial_id,
        created_at=_time(),
        strategy_family="momentum_breakout",
        parameters={"rs_min": 80, "rvol_min": 1.5},
        feature_ids=["stc_main_v2", "session_vwap_v2"],
        data_fingerprint="sha256:data",
        code_commit="deadbeef",
        evaluation_plan={"metric": "net_expectancy_r", "accept": ">0"},
    )


def test_plan_result_selection_chain_verifies(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    _plan(ledger)
    ledger.append_result(
        event_id="result-1",
        trial_id="trial-1",
        created_at=_time(10),
        metrics={"net_expectancy_r": 0.21, "n": 240},
        status="completed",
    )
    ledger.append_selection(
        event_id="selection-1",
        trial_id="trial-1",
        created_at=_time(11),
        decision="retain_for_cpcv",
        rationale="positive preregistered metric",
    )

    assert ledger.verify()
    assert ledger.trial_counts() == {"planned": 1, "completed": 1, "selection_events": 1}


def test_result_requires_preregistered_plan(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    with pytest.raises(TrialLedgerError, match="no preregistered plan"):
        ledger.append_result(
            event_id="result-1",
            trial_id="trial-1",
            created_at=_time(),
            metrics={},
            status="completed",
        )


def test_duplicate_plan_and_result_are_rejected(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    _plan(ledger)
    with pytest.raises(TrialLedgerError, match="already planned"):
        _plan(ledger, event_id="plan-2")

    ledger.append_result(
        event_id="result-1",
        trial_id="trial-1",
        created_at=_time(10),
        metrics={},
        status="completed",
    )
    with pytest.raises(TrialLedgerError, match="already has a result"):
        ledger.append_result(
            event_id="result-2",
            trial_id="trial-1",
            created_at=_time(11),
            metrics={},
            status="completed",
        )


def test_duplicate_event_id_is_rejected_across_trials(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    _plan(ledger, trial_id="trial-1", event_id="shared-event")
    with pytest.raises(TrialLedgerError, match="event_id already exists"):
        _plan(ledger, trial_id="trial-2", event_id="shared-event")


def test_result_timestamp_cannot_predate_plan(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    _plan(ledger)
    with pytest.raises(TrialLedgerError, match="predates plan"):
        ledger.append_result(
            event_id="result-1",
            trial_id="trial-1",
            created_at=_time(-1),
            metrics={},
            status="completed",
        )


def test_selection_timestamp_cannot_predate_result(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    _plan(ledger)
    ledger.append_result(
        event_id="result-1",
        trial_id="trial-1",
        created_at=_time(10),
        metrics={},
        status="completed",
    )
    with pytest.raises(TrialLedgerError, match="predates result"):
        ledger.append_selection(
            event_id="selection-1",
            trial_id="trial-1",
            created_at=_time(5),
            decision="promote",
            rationale="invalid chronology",
        )


def test_timezone_naive_event_is_rejected(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    with pytest.raises(TrialLedgerError, match="timezone-aware"):
        ledger.append_plan(
            event_id="plan-1",
            trial_id="trial-1",
            created_at=datetime(2026, 8, 31, 15, 0),
            strategy_family="x",
            parameters={},
            feature_ids=[],
            data_fingerprint="data",
            code_commit="commit",
            evaluation_plan={},
        )


def test_manual_tamper_is_detected(tmp_path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = TrialLedger(path)
    _plan(ledger)
    ledger.append_result(
        event_id="result-1",
        trial_id="trial-1",
        created_at=_time(10),
        metrics={"pf": 1.2},
        status="completed",
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["event"]["payload"]["metrics"]["pf"] = 9.9
    lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(TrialLedgerIntegrityError, match="event-hash mismatch"):
        ledger.verify()
