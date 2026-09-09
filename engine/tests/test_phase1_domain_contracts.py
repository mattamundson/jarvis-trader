from __future__ import annotations

import datetime as dt

import pytest

from domain.contracts import (
    ActorKind,
    ExecutionEnvironment,
    MutationEffect,
    OrderKind,
    OrderSide,
    TradeIntentContract,
)


def _intent(**overrides):
    values = {
        "intent_id": "intent-1",
        "idempotency_key": "idem-key-123",
        "symbol": " mes ",
        "side": OrderSide.BUY,
        "order_kind": OrderKind.MARKET,
        "mutation_effect": MutationEffect.INCREASE_EXPOSURE,
        "environment": ExecutionEnvironment.PAPER,
        "actor_kind": ActorKind.HUMAN,
        "created_at_utc": dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc),
        "protective_stop": 5998.0,
        "take_profit": 6004.0,
    }
    values.update(overrides)
    return TradeIntentContract(**values)


def test_contract_normalizes_symbol_and_never_self_authorizes():
    intent = _intent()
    assert intent.symbol == "MES"
    assert intent.can_self_authorize is False
    assert intent.to_dict()["can_self_authorize"] is False


def test_live_environment_remains_descriptive_not_authorizing():
    intent = _intent(environment=ExecutionEnvironment.LIVE)
    assert intent.environment is ExecutionEnvironment.LIVE
    assert intent.can_self_authorize is False


def test_exposure_increase_requires_protective_geometry_fields():
    with pytest.raises(ValueError, match="protective_stop and take_profit"):
        _intent(protective_stop=None)


def test_reduce_or_cancel_contract_does_not_require_target():
    intent = _intent(
        mutation_effect=MutationEffect.CANCEL,
        protective_stop=None,
        take_profit=None,
    )
    assert intent.mutation_effect is MutationEffect.CANCEL


def test_limit_requires_limit_price():
    with pytest.raises(ValueError, match="LIMIT intents require limit_price"):
        _intent(order_kind=OrderKind.LIMIT)


def test_created_timestamp_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        _intent(created_at_utc=dt.datetime(2026, 9, 3, 5, 0))


def test_requested_quantity_must_be_positive_if_present():
    with pytest.raises(ValueError, match="requested_quantity"):
        _intent(requested_quantity=0)
