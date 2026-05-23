"""
JARVIS TRADER — IB Bracket Order Tests
=======================================
Tests for engine/brokers/bracket_orders.py.

All tests are fully offline — no real IB connection is made.
IBGatewayManager calls are mocked via AsyncMock.

Test plan
---------
1. test_build_bracket_returns_3_orders        — build_bracket returns exactly 3 specs
2. test_parent_transmit_false                 — entry spec has transmit=False
3. test_target_transmit_true                  — TP spec has transmit=True
4. test_oca_group_links_stop_and_target       — STP and TP share oca_group, entry does not
5. test_disabled_falls_back_to_single_order   — ENABLE_BRACKET_ORDERS=0 → is_bracket_orders_enabled() False
6. test_missing_stop_falls_back_in_service    — no stop_price in snapshot → execute_approved_trade uses submit_paper_order
7. test_submit_bracket_rolls_back_on_child_failure — STP placement fails → parent cancelled, approved=False
8. test_submit_bracket_success                — happy path returns approved=True with all 3 IDs
9. test_submit_bracket_no_gateway             — None gateway → approved=False immediately
10. test_build_bracket_child_action_reversed  — BUY entry → SELL children; SELL entry → BUY children
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_parent(action: str = "BUY", quantity: int = 1) -> dict[str, Any]:
    return {"action": action, "quantity": quantity, "order_type": "MKT"}


# ── build_bracket tests ───────────────────────────────────────────────────────


def test_build_bracket_returns_3_orders():
    """build_bracket always returns a list of exactly 3 order specs."""
    from brokers.bracket_orders import build_bracket

    orders = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    assert len(orders) == 3, f"Expected 3 order specs, got {len(orders)}"


def test_parent_transmit_false():
    """IB convention: entry (parent) must have transmit=False."""
    from brokers.bracket_orders import build_bracket

    entry, _stp, _tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    assert entry["transmit"] is False, "Entry (parent) must NOT transmit until all legs are built"


def test_target_transmit_true():
    """IB convention: TP (final child) must have transmit=True to trigger atomic batch."""
    from brokers.bracket_orders import build_bracket

    _entry, _stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    assert tp["transmit"] is True, "TP child must transmit=True (triggers atomic IB submission)"


def test_oca_group_links_stop_and_target():
    """STP and TP share an oca_group so one cancels the other; entry has no oca_group."""
    from brokers.bracket_orders import build_bracket

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)

    assert (
        "oca_group" not in entry or entry.get("oca_group") is None
    ), "Entry should NOT carry an oca_group"
    assert stp.get("oca_group") is not None, "STP child must carry an oca_group"
    assert tp.get("oca_group") is not None, "TP child must carry an oca_group"
    assert (
        stp["oca_group"] == tp["oca_group"]
    ), "STP and TP must share the SAME oca_group so one cancels the other"


def test_build_bracket_child_action_reversed():
    """BUY entry → SELL children; SELL entry → BUY children."""
    from brokers.bracket_orders import build_bracket

    # BUY entry
    entry_b, stp_b, tp_b = build_bracket(
        _make_parent("BUY"), stop_price=5690.0, target_price=5720.0
    )
    assert entry_b["action"] == "BUY"
    assert stp_b["action"] == "SELL"
    assert tp_b["action"] == "SELL"

    # SELL entry
    entry_s, stp_s, tp_s = build_bracket(
        _make_parent("SELL"), stop_price=5690.0, target_price=5720.0
    )
    assert entry_s["action"] == "SELL"
    assert stp_s["action"] == "BUY"
    assert tp_s["action"] == "BUY"


# ── is_bracket_orders_enabled tests ──────────────────────────────────────────


def test_disabled_falls_back_to_single_order(monkeypatch):
    """ENABLE_BRACKET_ORDERS=0 → is_bracket_orders_enabled() returns False."""
    from brokers.bracket_orders import is_bracket_orders_enabled

    monkeypatch.setenv("ENABLE_BRACKET_ORDERS", "0")
    assert is_bracket_orders_enabled() is False


def test_enabled_default(monkeypatch):
    """Absent or '1' → is_bracket_orders_enabled() returns True."""
    from brokers.bracket_orders import is_bracket_orders_enabled

    monkeypatch.delenv("ENABLE_BRACKET_ORDERS", raising=False)
    assert is_bracket_orders_enabled() is True

    monkeypatch.setenv("ENABLE_BRACKET_ORDERS", "1")
    assert is_bracket_orders_enabled() is True


# ── submit_bracket tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_bracket_success():
    """Happy path: all 3 legs return order IDs, approved=True, bracket_status=attached."""
    from brokers.bracket_orders import build_bracket, submit_bracket

    fake_gw = AsyncMock()
    # side_effect: entry=1001, STP=1002, TP=1003
    fake_gw.place_paper_order = AsyncMock(side_effect=[1001, 1002, 1003])

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    result = await submit_bracket(fake_gw, "MES", entry, stp, tp)

    assert result["approved"] is True
    assert result["parent_order_id"] == "1001"
    assert result["stop_order_id"] == "1002"
    assert result["target_order_id"] == "1003"
    assert result["bracket_status"] == "attached"
    assert fake_gw.place_paper_order.await_count == 3


@pytest.mark.asyncio
async def test_submit_bracket_rolls_back_on_child_failure():
    """If STP placement fails (returns None), entry is cancelled, approved=False."""
    from brokers.bracket_orders import build_bracket, submit_bracket

    fake_gw = AsyncMock()
    # entry succeeds (1001), STP fails (returns None), cancel is called
    fake_gw.place_paper_order = AsyncMock(side_effect=[1001, None])
    fake_gw.cancel_order = AsyncMock(return_value=True)

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    result = await submit_bracket(fake_gw, "MES", entry, stp, tp)

    assert result["approved"] is False
    assert result["stop_order_id"] is None
    assert result["bracket_status"] == "failed"
    # Rollback cancel should have been called with the entry order id
    fake_gw.cancel_order.assert_awaited_once_with(1001)


@pytest.mark.asyncio
async def test_submit_bracket_no_gateway():
    """None gateway → approved=False immediately without calling any broker API."""
    from brokers.bracket_orders import build_bracket, submit_bracket

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    result = await submit_bracket(None, "MES", entry, stp, tp)

    assert result["approved"] is False
    assert result["parent_order_id"] is None
    assert result["bracket_status"] == "failed"


@pytest.mark.asyncio
async def test_submit_bracket_tp_failure_partial():
    """TP placement fails → entry + STP succeed, bracket_status='partial', approved=True."""
    from brokers.bracket_orders import build_bracket, submit_bracket

    fake_gw = AsyncMock()
    # entry=1001, STP=1002, TP placement raises
    fake_gw.place_paper_order = AsyncMock(side_effect=[1001, 1002, Exception("TP timeout")])

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    result = await submit_bracket(fake_gw, "MES", entry, stp, tp)

    assert result["approved"] is True
    assert result["parent_order_id"] == "1001"
    assert result["stop_order_id"] == "1002"
    assert result["target_order_id"] is None
    assert result["bracket_status"] == "partial"


# ── approval service integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_stop_falls_back_to_single():
    """No stop_price in snapshot → execute_approved_trade routes single submit_paper_order."""
    from approval.service import execute_approved_trade

    mock_safety = MagicMock()
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": True, "order_id": "999", "routed_to_ib": True}
    )
    mock_safety.submit_entry_with_stop = AsyncMock()

    with (
        patch("approval.service.settings.ENABLE_BROKER_BRACKETS", True),
        patch.dict(os.environ, {"ENABLE_BRACKET_ORDERS": "1"}),
    ):
        # stop_price=None → bracket path skipped regardless of flags
        result = await execute_approved_trade(
            safety_layer=mock_safety,
            symbol="MCL",
            action="BUY",
            quantity=1,
            entry_price=75.0,
            stop_price=None,  # ← no stop → single-order path
            target_price=78.0,
        )

    mock_safety.submit_paper_order.assert_awaited_once()
    mock_safety.submit_entry_with_stop.assert_not_awaited()
    assert result["approved"] is True


# ── _verify_parent_linkage tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_parent_linkage_confirmed():
    """get_order_status returns matching parentId → True."""
    from brokers.bracket_orders import _verify_parent_linkage

    fake_gw = MagicMock()
    fake_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "1001"})

    result = await _verify_parent_linkage(fake_gw, "MES", "1001", "1002")

    assert result is True
    fake_gw.get_order_status.assert_awaited_once_with(1002)


@pytest.mark.asyncio
async def test_verify_parent_linkage_mismatch():
    """get_order_status returns a different parentId → False."""
    from brokers.bracket_orders import _verify_parent_linkage

    fake_gw = MagicMock()
    fake_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "9999"})

    result = await _verify_parent_linkage(fake_gw, "MES", "1001", "1002")

    assert result is False


@pytest.mark.asyncio
async def test_verify_parent_linkage_missing_parent_key():
    """get_order_status returns a dict without parent_order_id → False."""
    from brokers.bracket_orders import _verify_parent_linkage

    fake_gw = MagicMock()
    fake_gw.get_order_status = AsyncMock(return_value={"status": "Submitted"})

    result = await _verify_parent_linkage(fake_gw, "MES", "1001", "1002")

    assert result is False


@pytest.mark.asyncio
async def test_verify_parent_linkage_gateway_raises():
    """get_order_status raises → False (don't let verification crash the caller)."""
    from brokers.bracket_orders import _verify_parent_linkage

    fake_gw = MagicMock()
    fake_gw.get_order_status = AsyncMock(side_effect=ConnectionError("IB disconnected"))

    result = await _verify_parent_linkage(fake_gw, "MES", "1001", "1002")

    assert result is False


@pytest.mark.asyncio
async def test_verify_parent_linkage_non_dict_status():
    """get_order_status returns a non-dict (unexpected) → False."""
    from brokers.bracket_orders import _verify_parent_linkage

    fake_gw = MagicMock()
    fake_gw.get_order_status = AsyncMock(return_value="OK")

    result = await _verify_parent_linkage(fake_gw, "MES", "1001", "1002")

    assert result is False


@pytest.mark.asyncio
async def test_verify_parent_linkage_no_method_on_gateway():
    """Gateway without get_order_status → True (graceful skip, not a failure)."""
    from brokers.bracket_orders import _verify_parent_linkage

    class _MinimalGateway:
        pass

    result = await _verify_parent_linkage(_MinimalGateway(), "MES", "1001", "1002")

    assert result is True


@pytest.mark.asyncio
async def test_submit_bracket_includes_parent_linkage_verified_field():
    """submit_bracket result includes parent_linkage_verified key on success path."""
    from brokers.bracket_orders import build_bracket, submit_bracket

    fake_gw = AsyncMock()
    fake_gw.place_paper_order = AsyncMock(side_effect=[1001, 1002, 1003])
    fake_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "1001"})

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    result = await submit_bracket(fake_gw, "MES", entry, stp, tp)

    assert (
        "parent_linkage_verified" in result
    ), "submit_bracket result must carry parent_linkage_verified for monitoring"
    assert result["parent_linkage_verified"] is True
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_submit_bracket_linkage_unconfirmed_still_approved():
    """Linkage check fails (parentId mismatch) but bracket is live — approved=True.

    The bracket was already submitted to IB; we cannot roll it back at this
    stage. The unconfirmed linkage is surfaced via the return field and a
    WARNING log so operations can monitor manually.
    """
    from brokers.bracket_orders import build_bracket, submit_bracket

    fake_gw = AsyncMock()
    fake_gw.place_paper_order = AsyncMock(side_effect=[1001, 1002, 1003])
    # Simulate IB reporting a wrong parentId (stale data during the race window)
    fake_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "0"})

    entry, stp, tp = build_bracket(_make_parent(), stop_price=5690.0, target_price=5720.0)
    result = await submit_bracket(fake_gw, "MES", entry, stp, tp)

    assert result["approved"] is True, "Bracket is live even when linkage check fails"
    assert result["parent_linkage_verified"] is False
    assert result["bracket_status"] == "attached"
