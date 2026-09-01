from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trade_intents.core import compute_trade_intent_preview
from trade_intents.store import TradeIntentStore, TradeIntentStoreError

NOW = datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)


def preview():
    return compute_trade_intent_preview(
        symbol="MES",
        direction="BUY",
        order_type="MARKET",
        entry_price=6500,
        stop_loss=6498,
        take_profit=6504,
        account_equity=3000,
    )


def payload(stop=6498):
    return {
        "symbol": "MES",
        "direction": "BUY",
        "order_type": "MARKET",
        "stop_loss": stop,
        "take_profit": 6504,
        "max_risk_fraction": 0.005,
    }


def test_same_idempotency_key_and_same_payload_returns_same_preview(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    first = store.create_preview(
        idempotency_key="intent-key-0001",
        request_payload=payload(),
        preview=preview(),
        now=NOW,
    )
    second = store.create_preview(
        idempotency_key="intent-key-0001",
        request_payload=payload(),
        preview=preview(),
        now=NOW + timedelta(seconds=1),
    )
    assert first["intent_id"] == second["intent_id"]


def test_same_active_payload_with_different_key_reuses_existing_intent(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    first = store.create_preview(
        idempotency_key="intent-key-1001",
        request_payload=payload(),
        preview=preview(),
        now=NOW,
    )
    second = store.create_preview(
        idempotency_key="intent-key-1002",
        request_payload=payload(),
        preview=preview(),
        now=NOW + timedelta(seconds=1),
    )
    assert first["intent_id"] == second["intent_id"]
    assert first["request_hash"] == second["request_hash"]


def test_reusing_idempotency_key_for_different_payload_is_rejected(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    store.create_preview(
        idempotency_key="intent-key-0002",
        request_payload=payload(),
        preview=preview(),
        now=NOW,
    )
    with pytest.raises(TradeIntentStoreError, match="different request payload"):
        store.create_preview(
            idempotency_key="intent-key-0002",
            request_payload=payload(stop=6497),
            preview=preview(),
            now=NOW,
        )


def test_expired_intent_fails_closed_and_persists_expired_status(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    created = store.create_preview(
        idempotency_key="intent-key-0003",
        request_payload=payload(),
        preview=preview(),
        ttl_seconds=30,
        now=NOW,
    )
    with pytest.raises(TradeIntentStoreError, match="expired"):
        store.require_submittable(
            created["intent_id"],
            now=NOW + timedelta(seconds=31),
        )
    assert store.get(created["intent_id"])["status"] == "EXPIRED"


def test_submission_requires_atomic_claim_and_then_is_idempotent(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    created = store.create_preview(
        idempotency_key="intent-key-0004",
        request_payload=payload(),
        preview=preview(),
        now=NOW,
    )
    claimed = store.claim_for_submission(
        created["intent_id"], now=NOW + timedelta(seconds=1)
    )
    assert claimed["status"] == "SUBMITTING"

    with pytest.raises(TradeIntentStoreError, match="not claimable"):
        store.claim_for_submission(
            created["intent_id"], now=NOW + timedelta(seconds=1, milliseconds=1)
        )

    submitted = store.mark_submitted(
        created["intent_id"],
        broker_result={"approved": True, "order_id": "IB-123"},
        order_id="IB-123",
        now=NOW + timedelta(seconds=2),
    )
    again = store.claim_for_submission(
        created["intent_id"], now=NOW + timedelta(seconds=3)
    )
    assert submitted["status"] == "SUBMITTED"
    assert again["status"] == "SUBMITTED"
    assert again["order_id"] == "IB-123"


def test_mark_submitted_before_claim_is_rejected(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    created = store.create_preview(
        idempotency_key="intent-key-0006",
        request_payload=payload(),
        preview=preview(),
        now=NOW,
    )
    with pytest.raises(TradeIntentStoreError, match="cannot submit intent from status PREVIEWED"):
        store.mark_submitted(
            created["intent_id"],
            broker_result={"approved": True},
            order_id="IB-456",
            now=NOW + timedelta(seconds=1),
        )


def test_blocked_intent_cannot_return_to_previewed_state(tmp_path) -> None:
    store = TradeIntentStore(tmp_path / "intents.db")
    created = store.create_preview(
        idempotency_key="intent-key-0005",
        request_payload=payload(),
        preview=preview(),
        now=NOW,
    )
    blocked = store.mark_terminal(
        created["intent_id"], status="BLOCKED", reason="reconciliation mismatch"
    )
    assert blocked["status"] == "BLOCKED"
    with pytest.raises(TradeIntentStoreError, match="not submittable"):
        store.require_submittable(created["intent_id"], now=NOW + timedelta(seconds=1))
