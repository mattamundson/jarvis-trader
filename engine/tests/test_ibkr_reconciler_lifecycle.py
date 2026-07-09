"""
Coverage gap fix (US-103): execution/ibkr_reconciler.py's ``reconcile()``,
``get_fills()`` and ``_get_connector()`` had zero direct coverage — only the
pure ``compare_fills_to_trades()`` helper is exercised by
tests/test_fill_reconciliation.py.

``reconcile()`` is the write path that imports live IBKR execution fills into
``ibkr_fills`` (see execution/ibkr_reconciler.py module docstring — it is
what gives JARVIS read-side visibility into fills that happened outside the
JARVIS order-routing pipeline, e.g. the DUP662235 demo-seed positions). Its
idempotency (never double-inserting the same exec_id) and its fail-open
behavior when the gateway is unreachable or raises are exactly the kind of
branch a coverage-gap audit should catch, since a crash here must never
propagate into the request that triggered it (POST /brokers/reconcile).

Test-only: no changes to execution/ibkr_reconciler.py.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from execution.ibkr_reconciler import IBKRReconciler


def _seed_ibkr_fills_table(db_path: str) -> None:
    from database.migrations import migration_036, migration_037

    conn = sqlite3.connect(db_path)
    migration_036(conn)
    migration_037(conn)
    conn.commit()
    conn.close()


def _make_fill(exec_id: str, **overrides) -> dict:
    base = {
        "exec_id": exec_id,
        "account": "DUP662235",
        "symbol": "MES",
        "sec_type": "FUT",
        "expiry": "",
        "side": "BOT",
        "quantity": 1.0,
        "price": 5000.0,
        "avg_price": 5000.0,
        "commission": 1.0,
        "exchange": "GLOBEX",
        "currency": "USD",
        "fill_time": "2026-06-02 14:00:00+00:00",
        "order_id": 11,
        "order_ref": "JARVIS-aaa",
        "parent_order_id": None,
    }
    base.update(overrides)
    return base


# ── _get_connector ────────────────────────────────────────────────────────────


def test_get_connector_returns_none_when_data_manager_is_none(tmp_path):
    reconciler = IBKRReconciler(tmp_path / "db.sqlite", data_manager=None)
    assert reconciler._get_connector() is None


def test_get_connector_returns_none_when_ibkr_attr_missing(tmp_path):
    dm = SimpleNamespace()  # no .ibkr attribute at all
    reconciler = IBKRReconciler(tmp_path / "db.sqlite", data_manager=dm)
    assert reconciler._get_connector() is None


def test_get_connector_returns_the_live_gateway(tmp_path):
    gw = object()
    dm = SimpleNamespace(ibkr=gw)
    reconciler = IBKRReconciler(tmp_path / "db.sqlite", data_manager=dm)
    assert reconciler._get_connector() is gw


# ── reconcile() ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_without_gateway_is_a_safe_noop(tmp_path):
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))

    reconciler = IBKRReconciler(str(db), data_manager=None)
    result = await reconciler.reconcile()

    assert result["connected"] is False
    assert result["imported"] == 0
    assert result["skipped"] == 0
    assert result["fills_from_ib"] == 0


@pytest.mark.asyncio
async def test_reconcile_imports_new_fills_and_is_idempotent(tmp_path):
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))

    gw = SimpleNamespace(get_executions=AsyncMock(return_value=[_make_fill("E1")]))
    reconciler = IBKRReconciler(str(db), data_manager=SimpleNamespace(ibkr=gw))

    first = await reconciler.reconcile()
    assert first["connected"] is True
    assert first["imported"] == 1
    assert first["skipped"] == 0
    assert first["total_in_db"] == 1

    # Same exec_id returned again (e.g. IBKR replays recent executions) -> the
    # PRIMARY KEY on exec_id must dedupe, not raise and not double-count.
    second = await reconciler.reconcile()
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert second["total_in_db"] == 1


@pytest.mark.asyncio
async def test_reconcile_skips_fills_with_no_exec_id(tmp_path):
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))

    gw = SimpleNamespace(
        get_executions=AsyncMock(return_value=[_make_fill(exec_id="")])
    )
    reconciler = IBKRReconciler(str(db), data_manager=SimpleNamespace(ibkr=gw))

    result = await reconciler.reconcile()
    assert result["imported"] == 0
    assert result["skipped"] == 0
    assert result["total_in_db"] == 0


@pytest.mark.asyncio
async def test_reconcile_get_executions_failure_is_fail_open(tmp_path):
    """A broker-side exception fetching executions must not propagate — the
    caller (POST /brokers/reconcile) must always get a structured result."""
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))

    gw = SimpleNamespace(
        get_executions=AsyncMock(side_effect=ConnectionError("gateway reset"))
    )
    reconciler = IBKRReconciler(str(db), data_manager=SimpleNamespace(ibkr=gw))

    result = await reconciler.reconcile()
    assert result["connected"] is False
    assert result["imported"] == 0
    assert result["total_in_db"] == 0


@pytest.mark.asyncio
async def test_reconcile_imports_multiple_distinct_fills(tmp_path):
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))

    fills = [_make_fill("E1"), _make_fill("E2", symbol="MGC", side="SLD")]
    gw = SimpleNamespace(get_executions=AsyncMock(return_value=fills))
    reconciler = IBKRReconciler(str(db), data_manager=SimpleNamespace(ibkr=gw))

    result = await reconciler.reconcile()
    assert result["imported"] == 2
    assert result["total_in_db"] == 2


# ── get_fills() ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_fills_filters_by_symbol_and_account(tmp_path):
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))

    fills = [
        _make_fill("E1", symbol="MES", account="DUP662235"),
        _make_fill("E2", symbol="MGC", account="DUP662235"),
        _make_fill("E3", symbol="MES", account="OTHER999"),
    ]
    gw = SimpleNamespace(get_executions=AsyncMock(return_value=fills))
    reconciler = IBKRReconciler(str(db), data_manager=SimpleNamespace(ibkr=gw))
    await reconciler.reconcile()

    mes_only = reconciler.get_fills(symbol="mes")  # case-insensitive
    assert {f["exec_id"] for f in mes_only} == {"E1", "E3"}

    mes_dup = reconciler.get_fills(symbol="MES", account="DUP662235")
    assert {f["exec_id"] for f in mes_dup} == {"E1"}

    all_fills = reconciler.get_fills()
    assert len(all_fills) == 3


def test_get_fills_returns_empty_list_when_table_missing(tmp_path):
    db = tmp_path / "no_table.db"
    sqlite3.connect(str(db)).close()  # no ibkr_fills table at all

    reconciler = IBKRReconciler(str(db), data_manager=None)
    assert reconciler.get_fills() == []


def test_get_fills_respects_limit(tmp_path):
    db = tmp_path / "recon.db"
    _seed_ibkr_fills_table(str(db))
    conn = sqlite3.connect(str(db))
    for i in range(5):
        f = _make_fill(f"E{i}", fill_time=f"2026-06-02 1{i}:00:00+00:00")
        conn.execute(
            """
            INSERT INTO ibkr_fills
                (exec_id, account, symbol, sec_type, expiry, side, quantity,
                 price, avg_price, commission, exchange, currency, fill_time,
                 order_id, order_ref, parent_order_id, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f["exec_id"], f["account"], f["symbol"], f["sec_type"],
                f["expiry"], f["side"], f["quantity"], f["price"],
                f["avg_price"], f["commission"], f["exchange"], f["currency"],
                f["fill_time"], f["order_id"], f["order_ref"],
                f["parent_order_id"], "now",
            ),
        )
    conn.commit()
    conn.close()

    reconciler = IBKRReconciler(str(db), data_manager=None)
    assert len(reconciler.get_fills(limit=2)) == 2
