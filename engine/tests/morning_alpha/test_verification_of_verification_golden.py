import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from morning_alpha.research import (
    ConformanceStatus,
    ExecutionIntent,
    ExecutionQuote,
    ExecutionReplayStatus,
    OrderSide,
    RedTeamCase,
    RedTeamStatus,
    VerificationComponentEvidence,
    VerificationIdentity,
    VerificationStatus,
    build_verification_receipt,
    replay_execution,
    run_placebo_battery,
    run_red_team,
    run_statistical_conformance,
)
from morning_alpha.research.statistical_models import MatchedEdgeObservation

TS = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def _rows():
    edges = [0.2, 0.1, 0.3, -0.05, 0.25, 0.15]
    rows = []
    for i, edge in enumerate(edges):
        ts = datetime(2024, 1, i + 1, 9, tzinfo=timezone.utc)
        rows.append(MatchedEdgeObservation(
            candidate_id=f"C{i}", decision_timestamp=ts, trading_date=ts.date(),
            symbol=f"S{i}", sector="TECH" if i % 2 == 0 else "HEALTH",
            strategy_return=edge, control_return=0.0,
            gross_r=0.5 + i * 0.05, cost_r_per_bps=0.01,
        ))
    return tuple(rows)


def _evidence_id(model) -> str:
    raw = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def test_golden_verifier_chain_separates_verification_from_edge_promotion():
    rows = _rows()
    conformance = run_statistical_conformance(rows, seed=7, resamples=4000, bootstrap_tolerance=0.05)
    assert conformance.overall_status is ConformanceStatus.VERIFIED

    red = run_red_team((RedTeamCase("known_corruption", "CAUGHT", lambda: "CAUGHT"),))
    assert red.status is RedTeamStatus.VERIFIED

    placebo = run_placebo_battery(rows, seed=7, rotations=6)
    assert 0 <= placebo.real_median_edge_percentile <= 1

    intent = ExecutionIntent(
        candidate_id="C1", side=OrderSide.BUY, quantity=100, trigger_timestamp=TS,
        reference_price=100.0, stop_price=99.0, target_price=101.0, risk_per_share=1.0,
        max_delay_seconds=60, max_participation_fraction=1.0,
    )
    entry = ExecutionQuote(timestamp=TS + timedelta(seconds=30), bid=100.7, ask=100.8, bid_size=1000, ask_size=1000, source="fixture")
    exit_q = ExecutionQuote(timestamp=TS + timedelta(seconds=40), bid=100.5, ask=100.7, bid_size=1000, ask_size=1000, source="fixture")
    execution = replay_execution(
        intent, (entry,), delay_seconds=30,
        exit_quotes=(exit_q,), exit_trigger_timestamp=TS + timedelta(seconds=40),
    )
    assert execution.status is ExecutionReplayStatus.FILLED
    assert execution.theoretical_exit_r == 1.0
    assert execution.realized_r is not None and execution.realized_r <= 0.0

    identity = VerificationIdentity(
        code_commit="fixture", spec_version="v15-v19.1",
        data_manifest_hash="a"*64, candidate_population_hash="b"*64,
        trial_ledger_hash="c"*64, seeds={"conformance": 7, "placebo": 7},
    )
    receipt = build_verification_receipt(identity, (
        VerificationComponentEvidence(name="conformance", status=VerificationStatus.VERIFIED, evidence_id=conformance.report_id),
        VerificationComponentEvidence(name="red_team", status=VerificationStatus.VERIFIED, evidence_id=red.report_id),
        VerificationComponentEvidence(name="placebo", status=VerificationStatus.VERIFIED, evidence_id=placebo.battery_id),
        VerificationComponentEvidence(name="execution", status=VerificationStatus.VERIFIED, evidence_id=_evidence_id(execution)),
    ))
    assert receipt.overall_status is VerificationStatus.VERIFIED
    assert "NOT A STRATEGY PROMOTION" in receipt.disclaimer


def test_golden_contaminated_verifier_chain_fails_receipt():
    bad_red = run_red_team((RedTeamCase("uncaught_future_leak", "TEMPORAL_LEAKAGE", lambda: None),))
    assert bad_red.status is RedTeamStatus.FAILED
    receipt = build_verification_receipt(
        VerificationIdentity(
            code_commit="fixture", spec_version="v15-v19.1",
            data_manifest_hash="a"*64, candidate_population_hash="b"*64,
            trial_ledger_hash="c"*64, seeds={},
        ),
        (VerificationComponentEvidence(name="red_team", status=VerificationStatus.FAILED, evidence_id=bad_red.report_id),),
    )
    assert receipt.overall_status is VerificationStatus.FAILED
