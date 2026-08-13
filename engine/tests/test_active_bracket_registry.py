"""
JARVIS TRADER — ActiveBracketRegistry Tests
==========================================
Tests for engine/brokers/active_bracket_registry.py.

All tests are fully offline — no real IB connection.

Test plan
---------
1.  test_register_and_get_all              — register stores the record
2.  test_unregister_removes_record         — unregister clears it
3.  test_count_multiple                    — count() reflects multi-symbol state
4.  test_mark_entry_filled                 — entry_filled flag set correctly
5.  test_cancel_all_entries_cancels_pending — pending entries are cancelled
6.  test_cancel_all_entries_skips_filled   — filled entries are skipped
7.  test_cancel_all_entries_no_gateway     — None gateway is a no-op
8.  test_cancel_all_entries_no_cancel_order_method — gateway without method surfaces as errors
9.  test_cancel_all_entries_no_cancel_order_method_empty_registry — same, nothing pending
10. test_cancel_all_entries_partial_failure — one fails, rest still cancel
11. test_cancel_all_cancels_every_leg      — all 3 legs cancelled
12. test_cancel_all_no_tp                  — partial bracket (no TP) handled
13. test_cancel_all_no_gateway             — None gateway is a no-op
14. test_cancel_all_no_cancel_order_method — gateway without method surfaces as errors
15. test_get_registry_returns_singleton    — module singleton identity
16. test_submit_bracket_registers_in_registry — submit_bracket wires registry
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fresh_registry():
    """Return a new (not singleton) registry for test isolation."""
    from brokers.active_bracket_registry import ActiveBracketRegistry

    return ActiveBracketRegistry()


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def test_register_and_get_all():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003", "JARVIS_BRACKET_BUY_569000")
    records = reg.get_all()
    assert len(records) == 1
    r = records[0]
    assert r.symbol == "MES"
    assert r.entry_id == "1001"
    assert r.stp_id == "1002"
    assert r.tp_id == "1003"
    assert r.oca_group == "JARVIS_BRACKET_BUY_569000"
    assert r.entry_filled is False


def test_unregister_removes_record():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")
    reg.unregister("1001")
    assert reg.count() == 0


def test_unregister_missing_key_is_noop():
    reg = _fresh_registry()
    reg.unregister("9999")  # should not raise
    assert reg.count() == 0


def test_count_multiple():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")
    reg.register("MCL", "2001", "2002", "2003")
    assert reg.count() == 2


def test_mark_entry_filled():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")
    assert reg.get_all()[0].entry_filled is False
    reg.mark_entry_filled("1001")
    assert reg.get_all()[0].entry_filled is True


def test_mark_entry_filled_unknown_id_is_noop():
    reg = _fresh_registry()
    reg.mark_entry_filled("9999")  # should not raise


# ── cancel_all_entries ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_all_entries_cancels_pending():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")
    reg.register("MCL", "2001", "2002", "2003")

    fake_gw = MagicMock()
    fake_gw.cancel_order = AsyncMock(return_value=True)

    result = await reg.cancel_all_entries(fake_gw)

    assert set(result["cancelled"]) == {"1001", "2001"}
    assert result["errors"] == []
    assert result["skipped_filled"] == 0
    assert fake_gw.cancel_order.await_count == 2


@pytest.mark.asyncio
async def test_cancel_all_entries_skips_filled():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")
    reg.register("MCL", "2001", "2002", "2003")
    reg.mark_entry_filled("1001")  # MES entry already filled

    fake_gw = MagicMock()
    fake_gw.cancel_order = AsyncMock(return_value=True)

    result = await reg.cancel_all_entries(fake_gw)

    assert result["cancelled"] == ["2001"]
    assert result["skipped_filled"] == 1
    assert fake_gw.cancel_order.await_count == 1


@pytest.mark.asyncio
async def test_cancel_all_entries_no_gateway():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")

    result = await reg.cancel_all_entries(None)

    assert result["cancelled"] == []
    assert result["errors"] == []
    assert result["skipped_filled"] == 0


@pytest.mark.asyncio
async def test_cancel_all_entries_no_cancel_order_method():
    """A gateway missing cancel_order must surface as errors, not a silent
    empty result -- this is what the kill-switch path checks to know pending
    entries are still live and unprotected (2026-08-11 fail-open-safety-checks
    audit finding #4)."""
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")

    class _MinimalGateway:
        pass

    result = await reg.cancel_all_entries(_MinimalGateway())
    assert result["cancelled"] == []
    assert len(result["errors"]) == 1
    assert result["errors"][0]["entry_id"] == "1001"
    assert result["errors"][0]["symbol"] == "MES"
    assert "cancel_order" in result["errors"][0]["error"]


@pytest.mark.asyncio
async def test_cancel_all_entries_no_cancel_order_method_empty_registry():
    """No pending entries at all -- still a clean empty result, not an error
    per record that doesn't exist."""
    reg = _fresh_registry()

    class _MinimalGateway:
        pass

    result = await reg.cancel_all_entries(_MinimalGateway())
    assert result == {"cancelled": [], "errors": [], "skipped_filled": 0}


@pytest.mark.asyncio
async def test_cancel_all_entries_partial_failure():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")
    reg.register("MCL", "2001", "2002", "2003")

    fake_gw = MagicMock()
    fake_gw.cancel_order = AsyncMock(side_effect=[True, ConnectionError("IB down")])

    result = await reg.cancel_all_entries(fake_gw)

    assert len(result["cancelled"]) == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["error"] == "IB down"


@pytest.mark.asyncio
async def test_cancel_all_entries_empty_registry():
    reg = _fresh_registry()
    fake_gw = MagicMock()
    fake_gw.cancel_order = AsyncMock()

    result = await reg.cancel_all_entries(fake_gw)
    assert result["cancelled"] == []
    assert result["skipped_filled"] == 0
    fake_gw.cancel_order.assert_not_awaited()


# ── cancel_all ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_all_cancels_every_leg():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")  # entry + stp + tp = 3 legs

    fake_gw = MagicMock()
    fake_gw.cancel_order = AsyncMock(return_value=True)

    result = await reg.cancel_all(fake_gw)

    assert len(result["cancelled"]) == 3
    order_ids = {r["order_id"] for r in result["cancelled"]}
    assert order_ids == {"1001", "1002", "1003"}
    legs = {r["leg"] for r in result["cancelled"]}
    assert legs == {"entry", "stp", "tp"}


@pytest.mark.asyncio
async def test_cancel_all_no_tp():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", None)  # partial bracket — no TP

    fake_gw = MagicMock()
    fake_gw.cancel_order = AsyncMock(return_value=True)

    result = await reg.cancel_all(fake_gw)

    assert len(result["cancelled"]) == 2  # entry + stp only
    legs = {r["leg"] for r in result["cancelled"]}
    assert legs == {"entry", "stp"}


@pytest.mark.asyncio
async def test_cancel_all_no_gateway():
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")

    result = await reg.cancel_all(None)
    assert result["cancelled"] == []
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_cancel_all_no_cancel_order_method():
    """Emergency-flatten path: a gateway missing cancel_order must surface
    every leg as an error, not a silent empty result (2026-08-11
    fail-open-safety-checks audit finding #4)."""
    reg = _fresh_registry()
    reg.register("MES", "1001", "1002", "1003")  # entry + stp + tp = 3 legs

    class _MinimalGateway:
        pass

    result = await reg.cancel_all(_MinimalGateway())
    assert result["cancelled"] == []
    assert len(result["errors"]) == 3
    legs = {e["leg"] for e in result["errors"]}
    assert legs == {"entry", "stp", "tp"}


# ── singleton ─────────────────────────────────────────────────────────────────


def test_get_registry_returns_singleton():
    from brokers.active_bracket_registry import get_registry

    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


# ── submit_bracket integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_bracket_registers_in_registry():
    """submit_bracket() success path writes into the module-level singleton registry."""
    from brokers.active_bracket_registry import get_registry
    from brokers.bracket_orders import build_bracket, submit_bracket

    fake_gw = AsyncMock()
    fake_gw.place_paper_order = AsyncMock(side_effect=[5001, 5002, 5003])
    fake_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "5001"})

    entry, stp, tp = build_bracket(
        {"action": "BUY", "quantity": 1, "order_type": "MKT"},
        stop_price=5690.0,
        target_price=5720.0,
    )
    result = await submit_bracket(fake_gw, "MES", entry, stp, tp)

    assert result["approved"] is True
    assert result["parent_order_id"] == "5001"
    assert result["bracket_status"] == "attached"

    # The global registry should contain the bracket that was just submitted.
    # (Uses singleton, so we look for the entry_id we know was placed.)
    reg = get_registry()
    matching = [r for r in reg.get_all() if r.entry_id == "5001"]
    assert matching, "submit_bracket should have registered entry_id=5001 in the global registry"
    assert matching[0].symbol == "MES"
    assert matching[0].stp_id == "5002"
    assert matching[0].tp_id == "5003"
    # Cleanup singleton state so other tests don't see it
    reg.unregister("5001")
