"""Endpoint-level tests for GET /pipeline/actionable.

The pure derivation (analytics.actionable.derive_actionable_board /
derive_actionable_item / derive_status) has direct unit coverage in
test_actionable.py. This file covers the router's own wiring, specifically
the T8 decision-source fix: queue-first reads from the autonomous
``pipeline_approval_queue`` with legacy-table fallback, the ``source`` and
``last_pipeline_run_at`` empty-state diagnostics, and fail-honest handling —
with only the router's external dependencies (DB manager, price snapshot)
mocked, not the router logic itself.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import actionable_router as mod


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


def _queue_row(
    *,
    symbol: str = "MES",
    direction: str = "LONG",
    status: str = "approved",
    entry: float = 5000.0,
    stop: float = 4980.0,
    target_1: float = 5020.0,
    target_2: float = 5030.0,
    atr: float = 10.0,
    confidence: float = 0.7,
) -> dict:
    """A pipeline_approval_queue row with a verdict carrying trade geometry."""
    return {
        "id": 1,
        "symbol": symbol,
        "direction": direction,
        "status": status,
        "confidence": confidence,
        "created_at": "2026-07-16T10:00:00+00:00",
        "expires_at": "2026-07-16T10:30:00+00:00",
        "verdict": {
            "final_action": "buy" if direction == "LONG" else "sell",
            "final_quantity": 2,
            "timeframe": "1h",
            "trade_decision": {
                "action": "buy" if direction == "LONG" else "sell",
                "entry_price": entry,
                "stop_price": stop,
                "target_1": target_1,
                "target_2": target_2,
                "atr_used": atr,
                "confidence": confidence,
            },
        },
    }


class FakeDBManager:
    def __init__(
        self,
        queue_rows: list | None = None,
        legacy_rows: list | None = None,
        last_pipeline_run_at: str | None = "2026-07-16T09:59:00+00:00",
        queue_raise: Exception | None = None,
    ):
        # None queue_rows = table absent (get_recent_queue_decisions returns None);
        # [] = table present but empty.
        self._queue = queue_rows
        self._legacy = legacy_rows or []
        self._last_run = last_pipeline_run_at
        self._queue_raise = queue_raise
        self.calls: dict[str, list] = {"queue": [], "legacy": [], "last_run": []}

    def get_recent_queue_decisions(self, limit: int):
        self.calls["queue"].append(limit)
        if self._queue_raise is not None:
            raise self._queue_raise
        if self._queue is None:
            return None
        return list(self._queue)

    def get_recent_approvals_all_statuses(self, limit: int):
        self.calls["legacy"].append(limit)
        return list(self._legacy)

    def get_last_pipeline_run_at(self):
        self.calls["last_run"].append(True)
        return self._last_run


@pytest.fixture(autouse=True)
def _reset_db_manager():
    """inject_dependencies mutates module-level state — reset after each test."""
    mod.inject_dependencies(None)
    yield
    mod.inject_dependencies(None)


async def _fake_price_snapshot(symbols: str) -> dict:
    """Price snapshot stub: fresh, live-tier, one row per requested symbol."""
    out = {}
    for sym in symbols.split(","):
        out[sym] = {
            "symbol": sym,
            "last_price": 5000.0,
            "as_of": 1_752_600_000.0,
            "is_live": True,
            "source": "ibkr",
        }
    return out


def _stub_prices(monkeypatch):
    # Router imports get_price_snapshot lazily inside the handler, so stub it
    # at its real source module.
    from routers import prices_router

    monkeypatch.setattr(prices_router, "get_price_snapshot", _fake_price_snapshot)


# ── decision source selection (T8 core fix) ─────────────────────────────────


def test_queue_is_primary_source_when_rows_exist(monkeypatch):
    db = FakeDBManager(queue_rows=[_queue_row()])
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    r = _client().get("/pipeline/actionable")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["source"] == "queue"
    assert db.calls["queue"] == [25]      # default limit
    assert db.calls["legacy"] == []       # queue satisfied — legacy untouched
    assert body["count"] == 1
    item = body["items"][0]
    assert item["symbol"] == "MES"
    assert item["direction"] == "long"
    assert item["entry_price"] == 5000.0
    assert item["stop_loss"] == 4980.0
    assert item["target_1"] == 5020.0
    assert item["target_2"] == 5030.0
    assert item["atr"] == 10.0


def test_legacy_fallback_when_queue_table_absent(monkeypatch):
    # get_recent_queue_decisions() returns None for a DB predating the queue.
    db = FakeDBManager(queue_rows=None, legacy_rows=[
        {"approval_id": "leg-1", "symbol": "MES", "action": "buy", "status": "pending",
         "quantity": 1, "created_at": "2026-07-16T10:00:00+00:00", "timeframe": "1h",
         "pipeline_snapshot": {"trade_decision": {"entry_price": 5000.0,
                                                  "stop_price": 4980.0,
                                                  "target_1": 5020.0,
                                                  "target_2": 5030.0,
                                                  "atr_used": 10.0,
                                                  "confidence": 0.7}}},
    ])
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    r = _client().get("/pipeline/actionable")
    body = r.json()
    assert body["source"] == "legacy"
    assert db.calls["queue"] == [25]
    assert db.calls["legacy"] == [25]
    assert body["count"] == 1
    assert body["items"][0]["approval_id"] == "leg-1"


def test_legacy_fallback_when_queue_empty(monkeypatch):
    # Table exists but has zero rows → legacy fallback (empty/new DB).
    db = FakeDBManager(queue_rows=[], legacy_rows=[])
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    r = _client().get("/pipeline/actionable")
    body = r.json()
    assert body["source"] == "legacy"
    assert body["count"] == 0


def test_legacy_fallback_when_queue_read_fails(monkeypatch):
    db = FakeDBManager(queue_rows=[_queue_row()], queue_raise=RuntimeError("boom"),
                       legacy_rows=[])
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    r = _client().get("/pipeline/actionable")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["source"] == "legacy"
    assert body["count"] == 0


# ── empty-state diagnostics ─────────────────────────────────────────────────


def test_last_pipeline_run_at_in_response(monkeypatch):
    db = FakeDBManager(queue_rows=[_queue_row()], last_pipeline_run_at="2026-07-16T09:59:00+00:00")
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    body = _client().get("/pipeline/actionable").json()
    assert body["last_pipeline_run_at"] == "2026-07-16T09:59:00+00:00"


def test_last_pipeline_run_at_none_degrades(monkeypatch):
    db = FakeDBManager(queue_rows=[_queue_row()], last_pipeline_run_at=None)
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    body = _client().get("/pipeline/actionable").json()
    assert body["last_pipeline_run_at"] is None


def test_last_pipeline_run_at_read_failure_degrades(monkeypatch):
    class BoomDB(FakeDBManager):
        def get_last_pipeline_run_at(self):
            raise RuntimeError("boom")

    db = BoomDB(queue_rows=[_queue_row()])
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    body = _client().get("/pipeline/actionable").json()
    assert body["last_pipeline_run_at"] is None  # never 500


def test_raw_count_reflects_rows_fetched_before_filters(monkeypatch):
    # 2 queue rows: one qualifying buy, one HOLD action (filtered by derivation).
    hold = _queue_row(symbol="MGC", direction="FLAT")
    hold["verdict"]["final_action"] = "hold"
    hold["verdict"]["trade_decision"]["action"] = "hold"
    db = FakeDBManager(queue_rows=[hold, _queue_row()])
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    body = _client().get("/pipeline/actionable").json()
    assert body["raw_count"] == 2
    assert body["shown"] == 1
    assert body["count"] == 1


# ── fail-honest wiring ──────────────────────────────────────────────────────


def test_no_db_manager_returns_honest_unavailable():
    mod.inject_dependencies(None)
    r = _client().get("/pipeline/actionable")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["count"] == 0
    assert "Database not available" in body["note"]


def test_both_sources_failing_returns_honest_unavailable(monkeypatch):
    # Queue read raises; legacy read raises → must NOT look like an empty board.
    class BoomDB(FakeDBManager):
        def get_recent_approvals_all_statuses(self, limit: int):
            raise RuntimeError("legacy boom")

    db = BoomDB(queue_rows=None, queue_raise=RuntimeError("q"))
    mod.inject_dependencies(db)
    _stub_prices(monkeypatch)

    r = _client().get("/pipeline/actionable")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["count"] == 0
    assert "unreadable" in body["note"]


def test_price_snapshot_failure_degrades_not_500(monkeypatch):
    db = FakeDBManager(queue_rows=[_queue_row()])
    mod.inject_dependencies(db)

    async def _boom(symbols: str):
        raise RuntimeError("price feed down")

    from routers import prices_router

    monkeypatch.setattr(prices_router, "get_price_snapshot", _boom)

    r = _client().get("/pipeline/actionable")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["count"] == 1
    # No price → honest "unknown" status, not a fabricated one.
    assert body["items"][0]["status"] == "unknown"
    assert body["items"][0]["latest_price"] is None
