from __future__ import annotations

import datetime as dt

import pytest

from domain.authorization import AuthorizationEvidence, AuthorizationTier, VerificationRung
from domain.contracts import ActorKind, ExecutionEnvironment, MutationEffect
from domain.events import AuditEventEnvelope, EventKind
from domain.oms import OmsState, automatic_submit_retry_allowed, requires_reconciliation_before_resubmit, validate_transition
from domain.risk_policy import LEGACY_RISK_FIELD_MAP, RiskPolicyV1

NOW = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)


def test_audit_envelope_is_deterministic_and_non_authorizing():
    event = AuditEventEnvelope(
        event_id="evt-1",
        event_kind=EventKind.RISK_DECISION,
        aggregate_type="trade_intent",
        aggregate_id="intent-1",
        occurred_at_utc=NOW,
        recorded_at_utc=NOW,
        actor_kind=ActorKind.SYSTEM,
        environment=ExecutionEnvironment.PAPER,
        correlation_id="corr-1",
        payload={"b": 2, "a": 1},
    )
    assert len(event.payload_hash) == 64
    assert event.can_authorize_execution is False
    assert event.to_dict()["can_authorize_execution"] is False


def test_live_authorization_evidence_reports_missing_human_and_capital_evidence():
    evidence = AuthorizationEvidence(
        authorization_id="auth-1",
        tier=AuthorizationTier.RESEARCH,
        environment=ExecutionEnvironment.LIVE,
        verification_rung=VerificationRung.V4,
        issued_at_utc=NOW,
        expires_at_utc=NOW + dt.timedelta(hours=1),
    )
    findings = evidence.structural_findings(now=NOW)
    assert evidence.can_self_authorize is False
    assert any("V5" in finding for finding in findings)
    assert "human approval evidence is required" in findings
    assert "capital authorization evidence is required" in findings
    assert "LIVE environment requires a live authorization tier" in findings


def _risk_payload():
    values = {
        "policy_id": "risk-v1",
        "version": 1,
        "effective_from_utc": NOW,
        "max_position_size_pct": 0.1,
        "max_daily_loss_pct": 0.06,
        "max_daily_loss_usd": 100.0,
        "max_trade_loss_usd": 50.0,
        "max_drawdown_pct": 0.2,
        "max_orders_per_minute": 10,
        "max_correlated_exposure_pct": 0.5,
        "price_collar_pct": 0.05,
        "max_single_order_value": 100000.0,
        "max_margin_utilization": 0.4,
        "max_contracts_per_instrument": 2,
        "max_overnight_contracts": 1,
        "correlated_pair_max_contracts": 1,
    }
    assert set(LEGACY_RISK_FIELD_MAP).issubset(values)
    return values


def test_risk_policy_schema_is_inert_even_with_structurally_valid_values():
    policy = RiskPolicyV1.from_mapping(_risk_payload())
    assert policy.active is False
    assert policy.can_activate_itself is False


def test_risk_policy_rejects_invalid_fraction():
    payload = _risk_payload()
    payload["max_drawdown_pct"] = 1.5
    with pytest.raises(ValueError, match="max_drawdown_pct"):
        RiskPolicyV1.from_mapping(payload)


def test_oms_ambiguous_is_not_retryable_and_requires_reconciliation():
    assert automatic_submit_retry_allowed(OmsState.AMBIGUOUS) is False
    assert requires_reconciliation_before_resubmit(OmsState.AMBIGUOUS) is True
    validate_transition(OmsState.AMBIGUOUS, OmsState.RECONCILED)
    with pytest.raises(ValueError, match="illegal OMS transition"):
        validate_transition(OmsState.AMBIGUOUS, OmsState.ROUTING)


@pytest.mark.parametrize(
    "state",
    [OmsState.ROUTING, OmsState.ACKNOWLEDGED, OmsState.PARTIALLY_FILLED, OmsState.CANCEL_PENDING],
)
def test_post_broker_states_are_never_automatic_submit_retry_candidates(state: OmsState):
    assert automatic_submit_retry_allowed(state) is False
    assert requires_reconciliation_before_resubmit(state) is True


def test_only_pre_routing_states_can_be_future_retry_candidates():
    assert automatic_submit_retry_allowed(OmsState.CREATED) is True
    assert automatic_submit_retry_allowed(OmsState.VALIDATED) is True
    assert automatic_submit_retry_allowed(OmsState.CLAIMED) is True
