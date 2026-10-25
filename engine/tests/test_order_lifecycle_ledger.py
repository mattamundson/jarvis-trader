"""Tests for the append-only order lifecycle ledger."""

from __future__ import annotations

import json

from execution.order_lifecycle_ledger import (
    OrderLifecycleEvent,
    OrderLifecycleLedger,
    OrderLifecycleType,
)


def _event(**overrides) -> OrderLifecycleEvent:
    params = {
        "event_type": OrderLifecycleType.SUBMITTED,
        "idempotency_key": "MES|BUY|2026-09-02",
        "source": "approval_queue",
        "symbol": "mes",
        "timestamp": "2026-09-02T14:30:00+00:00",
        "strategy_id": "MES_trend_rank11",
        "decision_id": "approval-42",
        "safety_state_hash": "abc123",
        "feature_snapshot_id": "feat-001",
        "broker_order_id": "ib-777",
        "raw_broker_status": "Submitted",
        "metadata": {"quantity": 1, "action": "BUY"},
    }
    params.update(overrides)
    return OrderLifecycleEvent(**params)


def test_event_record_normalizes_symbol_and_account_mode() -> None:
    record = _event(account_mode="PAPER").to_record()

    assert record["event_type"] == "submitted"
    assert record["symbol"] == "MES"
    assert record["account_mode"] == "paper"
    assert record["metadata"] == {"quantity": 1, "action": "BUY"}
    assert len(record["event_id"]) == 64


def test_append_writes_jsonl_and_returns_true_for_new_event(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = OrderLifecycleLedger(path)

    assert ledger.append(_event()) is True

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["idempotency_key"] == "MES|BUY|2026-09-02"
    assert record["broker_order_id"] == "ib-777"


def test_append_is_idempotent_for_identical_event(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = OrderLifecycleLedger(path)
    event = _event()

    assert ledger.append(event) is True
    assert ledger.append(event) is False

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_different_lifecycle_events_for_same_order_are_preserved(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = OrderLifecycleLedger(path)

    assert ledger.append(_event(event_type=OrderLifecycleType.INTENT_CREATED)) is True
    assert ledger.append(_event(event_type=OrderLifecycleType.AUTHORIZED)) is True
    assert ledger.append(_event(event_type=OrderLifecycleType.SUBMITTED)) is True

    events = ledger.events_for_idempotency_key("MES|BUY|2026-09-02")
    assert [event["event_type"] for event in events] == [
        "intent_created",
        "authorized",
        "submitted",
    ]


def test_read_events_skips_malformed_lines(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    good_record = _event().to_record()
    path.write_text(
        json.dumps(good_record) + "\n"
        "not json\n"
        "\n"
        + json.dumps({"event_type": "accepted", "event_id": "ok"}) + "\n",
        encoding="utf-8",
    )

    events = OrderLifecycleLedger(path).read_events()

    assert [event["event_type"] for event in events] == ["submitted", "accepted"]


def test_events_for_idempotency_key_filters_records(tmp_path) -> None:
    ledger = OrderLifecycleLedger(tmp_path / "events.jsonl")
    ledger.append(_event(idempotency_key="MES|BUY|2026-09-02"))
    ledger.append(_event(idempotency_key="MGC|SELL|2026-09-02", symbol="MGC"))

    events = ledger.events_for_idempotency_key("MGC|SELL|2026-09-02")

    assert len(events) == 1
    assert events[0]["symbol"] == "MGC"


def test_default_ledger_path_under_engine_data() -> None:
    ledger = OrderLifecycleLedger()

    assert ledger._path.parts[-3:] == ("data", "order_lifecycle", "events.jsonl")
