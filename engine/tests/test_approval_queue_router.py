"""
Tests for engine/routers/approval_queue_router.py

Covers:
  - test_pending_list_empty_initially
  - test_approve_requires_kill_switch_inactive
  - test_approve_requires_paper_mode
  - test_approve_submits_paper_order
  - test_reject_records_reason
  - test_expired_candidates_auto_filter
  - test_no_duplicate_candidates_for_same_symbol_direction (via scheduler module)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# -- import the router module directly (no FastAPI app needed for unit tests) --
from routers.approval_queue_router import (
    _ensure_schema,
    _get_candidate,
    _insert_candidate_direct,  # noqa: F401  (re-used in final helper block)
    _list_pending,
    _safety_guard_for_approve,
    _update_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test_queue.db")
    _ensure_schema(db_path)
    return db_path


def _insert_via_sql(
    db_path: str,
    symbol: str = "MCL",
    direction: str = "LONG",
    confidence: float = 0.80,
    ttl_seconds: int = 1800,
    status: str = "pending",
    expired: bool = False,
) -> int:
    now = datetime.now(timezone.utc)
    if expired:
        expires = (now - timedelta(seconds=60)).isoformat()
    else:
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pipeline_approval_queue
                (created_at, symbol, direction, confidence, verdict_json, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                symbol.upper(),
                direction.upper(),
                confidence,
                json.dumps({"trade_decision": {"entry_price": 2000.0}}),
                expires,
                status,
            ),
        )
        conn.commit()
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pending_list_empty_initially(tmp_path: Path) -> None:
    """A freshly created DB has no pending candidates."""
    db_path = _fresh_db(tmp_path)
    rows = _list_pending(db_path)
    assert rows == []


def test_approve_requires_kill_switch_inactive(tmp_path: Path) -> None:
    """When kill switch is active, _safety_guard_for_approve returns False."""
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": True}

    # Inject mock
    import routers.approval_queue_router as mod

    original_sl = mod._safety_layer
    original_db = mod._db_path
    try:
        mod._safety_layer = mock_safety
        mod._db_path = _fresh_db(tmp_path)

        # Patch config to keep LIVE_TRADING_ENABLED=False
        with patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False):
            ok, reason = _safety_guard_for_approve()

        assert ok is False
        assert "kill switch" in reason.lower()
    finally:
        mod._safety_layer = original_sl
        mod._db_path = original_db


def test_approve_requires_paper_mode(tmp_path: Path) -> None:
    """When LIVE_TRADING_ENABLED=True, _safety_guard_for_approve returns False."""
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}

    import routers.approval_queue_router as mod

    original_sl = mod._safety_layer
    original_db = mod._db_path
    try:
        mod._safety_layer = mock_safety
        mod._db_path = _fresh_db(tmp_path)

        with patch("routers.approval_queue_router._get_live_trading_enabled", return_value=True):
            ok, reason = _safety_guard_for_approve()

        assert ok is False
        assert "live" in reason.lower() or "LIVE_TRADING" in reason
    finally:
        mod._safety_layer = original_sl
        mod._db_path = original_db


@pytest.mark.asyncio
async def test_approve_submits_paper_order(tmp_path: Path) -> None:
    """approve_candidate calls submit_paper_order with correct shape."""
    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path, symbol="MCL", direction="LONG", confidence=0.75)

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={
            "approved": True,
            "routed_to_ib": True,
            "order_id": "TEST-42",
            "fill_id": "TEST-42",
        }
    )

    import routers.approval_queue_router as mod
    from execution.submission_dedup import SubmissionDedup

    original_sl = mod._safety_layer
    original_db = mod._db_path
    original_dedup = mod._dedup
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        mod._dedup = SubmissionDedup(Path(tmp_path) / "dedup.jsonl")  # isolate from default ledger

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            result = await approve_candidate(row_id, ApproveBody(entry_price=2010.0))

        # Verify submit was called
        mock_safety.submit_paper_order.assert_awaited_once()
        call_kwargs = mock_safety.submit_paper_order.call_args.kwargs
        assert call_kwargs["symbol"] == "MCL"
        assert call_kwargs["action"] == "BUY"
        assert call_kwargs["price"] == 2010.0

        # Verify DB updated
        candidate = _get_candidate(db_path, row_id)
        assert candidate is not None
        assert candidate["status"] == "approved"
        assert candidate["order_id"] == "TEST-42"

        assert result["status"] == "approved"
    finally:
        mod._safety_layer = original_sl
        mod._db_path = original_db
        mod._dedup = original_dedup


@pytest.mark.asyncio
async def test_approve_records_to_shared_dedup(tmp_path: Path) -> None:
    """An APPROVED submit claims the shared cross-path slot for (symbol, action, today)."""
    from execution.submission_dedup import SubmissionDedup

    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path, symbol="MCL", direction="LONG", confidence=0.75)

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "routed_to_ib": True, "order_id": "TEST-77"}
    )

    import routers.approval_queue_router as mod

    original_sl, original_db, original_dedup = mod._safety_layer, mod._db_path, mod._dedup
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        mod._dedup = SubmissionDedup(Path(tmp_path) / "dedup.jsonl")

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            await approve_candidate(row_id, ApproveBody(entry_price=2010.0))

        # the (symbol, action, today) key is now claimed in the shared ledger
        key = mod._dedup.make_key("MCL", "BUY", datetime.now(timezone.utc).date())
        assert mod._dedup.already_submitted(key) is True
    finally:
        mod._safety_layer, mod._db_path, mod._dedup = original_sl, original_db, original_dedup


@pytest.mark.asyncio
async def test_approve_skips_when_cross_path_already_submitted(tmp_path: Path) -> None:
    """If the bridge already submitted MCL BUY today, the queue refuses (no 2x fill)."""
    from execution.submission_dedup import SubmissionDedup

    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path, symbol="MCL", direction="LONG", confidence=0.75)

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "order_id": "SHOULD-NOT-FIRE"}
    )

    import routers.approval_queue_router as mod

    original_sl, original_db, original_dedup = mod._safety_layer, mod._db_path, mod._dedup
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        shared = SubmissionDedup(Path(tmp_path) / "dedup.jsonl")
        # the bridge already submitted MCL BUY today
        shared.record(
            shared.make_key("MCL", "BUY", datetime.now(timezone.utc).date()),
            source="bridge",
            native_id="MCL_x_rank1",
        )
        mod._dedup = shared

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            with pytest.raises(HTTPException) as exc_info:
                await approve_candidate(row_id, ApproveBody(entry_price=2010.0))

        assert exc_info.value.status_code == 409
        assert "cross-path" in str(exc_info.value.detail).lower()
        mock_safety.submit_paper_order.assert_not_awaited()
        # candidate stays pending — nothing was submitted
        candidate = _get_candidate(db_path, row_id)
        assert candidate is not None and candidate["status"] == "pending"
    finally:
        mod._safety_layer, mod._db_path, mod._dedup = original_sl, original_db, original_dedup


def test_reject_records_reason(tmp_path: Path) -> None:
    """reject_candidate sets status=rejected and records the reason."""
    import asyncio

    from routers.approval_queue_router import RejectBody, reject_candidate

    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path)

    import routers.approval_queue_router as mod

    original_db = mod._db_path
    try:
        mod._db_path = db_path
        result = asyncio.get_event_loop().run_until_complete(
            reject_candidate(row_id, RejectBody(reason="not the right setup"))
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "not the right setup"

        row = _get_candidate(db_path, row_id)
        assert row is not None
        assert row["status"] == "rejected"
        assert row["reviewer_notes"] == "not the right setup"
    finally:
        mod._db_path = original_db


def test_expired_candidates_auto_filter(tmp_path: Path) -> None:
    """Expired candidates do NOT appear in /pending results."""
    db_path = _fresh_db(tmp_path)
    _insert_via_sql(db_path, symbol="MCL", expired=True)  # should be hidden
    _insert_via_sql(db_path, symbol="MNQ", expired=False)  # should appear

    rows = _list_pending(db_path)
    symbols = [r["symbol"] for r in rows]
    assert "MNQ" in symbols
    assert "MCL" not in symbols


def test_no_duplicate_candidates_for_same_symbol_direction(tmp_path: Path) -> None:
    """
    When the autonomous tick runs twice for the same (symbol, direction),
    only one candidate should be enqueued (idempotency guard).
    """
    from scheduler.pipeline_autonomous import (
        _ensure_table,
        _has_pending_candidate,
        _insert_candidate,
    )

    db_path = str(tmp_path / "dup_test.db")
    _ensure_table(db_path)

    # First insert
    row1 = _insert_candidate(
        db_path=db_path,
        symbol="MCL",
        direction="LONG",
        confidence=0.80,
        verdict_json="{}",
        ttl_seconds=1800,
    )
    assert row1 > 0

    # Idempotency check: guard should detect existing live candidate
    assert _has_pending_candidate(db_path, "MCL", "LONG") is True

    # If the tick correctly checks, it would NOT insert a second row.
    # Verify the guard works for the opposite direction too.
    assert _has_pending_candidate(db_path, "MCL", "SHORT") is False


@pytest.mark.asyncio
async def test_approve_writes_ledger_with_stop_and_target(tmp_path: Path) -> None:
    """An approved candidate must write a paper_trades row (stop+target) when
    paper_tracker is injected — the 2026-08-16 ledger-gap fix.

    Before the fix, approve_candidate routed orders to IB but never recorded
    the paper_trades row, so 386 approved queue rows matched ZERO ledger rows.
    """
    db_path = _fresh_db(tmp_path)
    # Insert candidate whose snapshot carries stop_price and target_1 (the
    # pipeline's trade_decision shape).
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pipeline_approval_queue
                (created_at, symbol, direction, confidence, verdict_json, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                now.isoformat(),
                "MCL",
                "LONG",
                0.75,
                json.dumps(
                    {
                        "trade_decision": {
                            "entry_price": 2000.0,
                            "stop_price": 1990.0,
                            "target_1": 2030.0,
                            "target_2": 2050.0,
                        }
                    }
                ),
                (now + timedelta(seconds=1800)).isoformat(),
            ),
        )
        row_id = cur.lastrowid
        conn.commit()

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "routed_to_ib": True, "order_id": "TEST-LEDGER-1"}
    )
    mock_tracker = MagicMock()
    mock_tracker.add_paper_trade = MagicMock(return_value="trade-abc123")

    import routers.approval_queue_router as mod
    from execution.submission_dedup import SubmissionDedup

    original_sl = mod._safety_layer
    original_db = mod._db_path
    original_dedup = mod._dedup
    original_tracker = mod._paper_tracker
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        mod._dedup = SubmissionDedup(Path(tmp_path) / "dedup_ledger.jsonl")
        mod._paper_tracker = mock_tracker

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            result = await approve_candidate(row_id, ApproveBody(entry_price=2000.0))

        assert result["status"] == "approved"

        # Ledger write: add_paper_trade must have been called with stop + target
        # lifted from the pipeline snapshot, not None/omitted.
        mock_tracker.add_paper_trade.assert_called_once()
        kwargs = mock_tracker.add_paper_trade.call_args.kwargs
        assert kwargs["symbol"] == "MCL"
        assert kwargs["side"] == "buy"
        assert kwargs["entry_price"] == 2000.0
        assert kwargs["stop_loss"] == 1990.0
        assert kwargs["take_profit"] == 2030.0  # target_1 preferred over target_2
        assert kwargs["strategy_params"]["candidate_id"] == row_id
    finally:
        mod._safety_layer = original_sl
        mod._db_path = original_db
        mod._dedup = original_dedup
        mod._paper_tracker = original_tracker


@pytest.mark.asyncio
async def test_approve_ledger_failure_does_not_fail_order(tmp_path: Path) -> None:
    """A ledger write failure must not fail the already-submitted order — the
    queue row remains the audit record of the broker submission."""
    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path, symbol="MCL", direction="LONG", confidence=0.75)

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "routed_to_ib": True, "order_id": "TEST-LEDGER-2"}
    )
    mock_tracker = MagicMock()
    mock_tracker.add_paper_trade = MagicMock(side_effect=RuntimeError("db locked"))

    import routers.approval_queue_router as mod
    from execution.submission_dedup import SubmissionDedup

    original_sl = mod._safety_layer
    original_db = mod._db_path
    original_dedup = mod._dedup
    original_tracker = mod._paper_tracker
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        mod._dedup = SubmissionDedup(Path(tmp_path) / "dedup_ledger2.jsonl")
        mod._paper_tracker = mock_tracker

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            # Should NOT raise despite the ledger failure.
            result = await approve_candidate(row_id, ApproveBody(entry_price=2010.0))

        assert result["status"] == "approved"
        candidate = _get_candidate(db_path, row_id)
        assert candidate["status"] == "approved"
        assert candidate["order_id"] == "TEST-LEDGER-2"
    finally:
        mod._safety_layer = original_sl
        mod._db_path = original_db
        mod._dedup = original_dedup
        mod._paper_tracker = original_tracker


@pytest.mark.asyncio
async def test_approve_not_routed_fails_closed(tmp_path: Path) -> None:
    """2026-10-26 phantom row 346: safety passed (approved=True) but the broker
    call raised, so routed_to_ib=False. The approve path must not write a
    paper_trades row, must not claim the cross-path dedup slot, and must mark
    the candidate rejected."""
    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path, symbol="MES", direction="LONG", confidence=0.75)

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={
            "approved": True,
            "routed_to_ib": False,
            "order_id": None,
            "reason": "Safety checks passed but IB order failed: unexpected keyword 'take_profit'",
        }
    )
    mock_tracker = MagicMock()

    import routers.approval_queue_router as mod
    from execution.submission_dedup import SubmissionDedup

    dedup = SubmissionDedup(Path(tmp_path) / "dedup_not_routed.jsonl")
    original_sl = mod._safety_layer
    original_db = mod._db_path
    original_dedup = mod._dedup
    original_tracker = mod._paper_tracker
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        mod._dedup = dedup
        mod._paper_tracker = mock_tracker

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            with pytest.raises(HTTPException) as exc_info:
                await approve_candidate(row_id, ApproveBody(entry_price=7671.25))

        assert exc_info.value.status_code == 502
        mock_tracker.add_paper_trade.assert_not_called()
        today = datetime.now(timezone.utc).date()
        assert dedup.already_submitted(dedup.make_key("MES", "BUY", today)) is False
        with sqlite3.connect(db_path) as conn:
            status = conn.execute(
                "SELECT status FROM pipeline_approval_queue WHERE id=?", (row_id,)
            ).fetchone()[0]
        assert status == "rejected"
    finally:
        mod._safety_layer = original_sl
        mod._db_path = original_db
        mod._dedup = original_dedup
        mod._paper_tracker = original_tracker


@pytest.mark.asyncio
async def test_approve_ledger_records_stop_target_sent_to_broker(tmp_path: Path) -> None:
    """2026-10-27 cert row 347: the stop/target arrived in the request body (the
    verdict carried none). The broker got the body stop -- IB placed STP child 6
    and TP child 7 -- but the ledger re-derived stop/target from the verdict only
    and stored NULL. The ledger must record exactly what was sent to the broker,
    plus the entry order id so fills can be matched back to the row."""
    db_path = _fresh_db(tmp_path)
    row_id = _insert_via_sql(db_path, symbol="MES", direction="LONG", confidence=0.75)

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={
            "approved": True,
            "routed_to_ib": True,
            "order_id": "5",
            "stop_order_id": 6,
            "target_order_id": 7,
        }
    )
    mock_tracker = MagicMock()
    mock_tracker.add_paper_trade = MagicMock(return_value="trade-cert-347")

    import routers.approval_queue_router as mod
    from execution.submission_dedup import SubmissionDedup

    original = (mod._safety_layer, mod._db_path, mod._dedup, mod._paper_tracker)
    try:
        mod._safety_layer = mock_safety
        mod._db_path = db_path
        mod._dedup = SubmissionDedup(Path(tmp_path) / "dedup_ledger_body.jsonl")
        mod._paper_tracker = mock_tracker

        with (
            patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
            patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
            patch("routers.approval_queue_router._stamp_bracket_ids", return_value=True),
        ):
            from routers.approval_queue_router import ApproveBody, approve_candidate

            await approve_candidate(
                row_id,
                ApproveBody(entry_price=7704.75, stop_price=7690.0, take_profit=7720.0),
            )

        sent = mock_safety.submit_paper_order.call_args.kwargs
        kwargs = mock_tracker.add_paper_trade.call_args.kwargs
        assert sent["stop_price"] == 7690.0
        assert kwargs["stop_loss"] == sent["stop_price"]
        assert kwargs["take_profit"] == sent["take_profit"] == 7720.0
        assert kwargs["strategy_params"]["entry_order_id"] == "5"
    finally:
        mod._safety_layer, mod._db_path, mod._dedup, mod._paper_tracker = original
