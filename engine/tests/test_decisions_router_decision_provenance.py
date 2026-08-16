"""Data-provenance stamping for decisions_router's POST /decisions/log caller.

PR #286 stamped {last_bar_source, serve_age_s} onto main.py's `_log_decision`
path only. This pins the same stamping on decisions_router's `log_decision`
endpoint (the path agents call directly to log decisions), additive only —
no schema change, no change to existing signal_data fields.

Integration style via FastAPI TestClient, matching
tests/test_decisions_router_typed.py's conventions.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import decisions_router


class _FakeDM:
    def __init__(self, source, freshness):
        self._last_bar_source = source
        self._freshness = freshness

    def symbol_freshness(self):
        return self._freshness


class _FakeDBManager:
    def __init__(self):
        self.inserted: list[dict] = []

    def insert_decision(self, **kwargs: Any) -> int:
        self.inserted.append(kwargs)
        return len(self.inserted)


def _mk_client(db, dm=None) -> TestClient:
    app = FastAPI()
    app.include_router(decisions_router.router)
    decisions_router.set_db_manager(db)
    decisions_router.set_data_manager(dm)
    return TestClient(app)


def test_log_decision_stamps_provenance_when_data_manager_injected():
    db = _FakeDBManager()
    dm = _FakeDM("sqlite_cache", {"MGC": 9.0})
    client = _mk_client(db, dm)

    resp = client.post(
        "/decisions/log",
        json={"symbol": "MGC", "action": "sell", "confidence": 0.6, "rsi": 42},
    )

    assert resp.status_code == 200
    assert len(db.inserted) == 1
    sig = db.inserted[0]["signal_data"]
    assert sig["data_provenance"] == {"last_bar_source": "sqlite_cache", "serve_age_s": 9.0}
    assert sig["rsi"] == 42  # caller's fields preserved


def test_log_decision_survives_when_data_manager_absent():
    db = _FakeDBManager()
    client = _mk_client(db, dm=None)

    resp = client.post(
        "/decisions/log",
        json={"symbol": "MES", "action": "hold"},
    )

    assert resp.status_code == 200
    assert len(db.inserted) == 1
    sig = db.inserted[0]["signal_data"]
    assert "data_provenance" not in sig
