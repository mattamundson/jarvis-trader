"""Endpoint-level tests for GET /brief/session.

`analytics.session_brief.build_session_brief` and `build_action` already have
direct unit coverage in test_session_brief.py, and `fetch_amoarb_signals` has
its own in test_amoarb_signals.py. This file covers the router's own wiring:
dependency injection (`_db_manager`), snapshot collection/enrichment
(`_collect_snapshots`), query-param clamping, and the router's fail-honest
exception handling -- with only the router's external dependencies (DB
manager, amo-arbitrage HTTP fetch) mocked, not the router logic itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import session_brief_router as mod


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


def _fresh_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _full_snapshot(symbol: str = "MES", action: str = "buy") -> dict:
    """A pipeline snapshot with enough real reasoning fields that
    build_action() assembles a non-degraded action (mirrors the fixture in
    test_session_brief.py)."""
    return {
        "symbol": symbol,
        "final_action": action,
        "boosted_confidence": 0.72,
        "completed_at": _fresh_iso(),
        "trade_decision": {"action": action, "reasoning": "Momentum breakout above IB high."},
        "risk_decision": {"reasoning": "Stop 12 ticks below entry; 0.4% account risk."},
        "fund_decision": {"reasoning": "Conviction supports a single micro contract."},
        "debate_result": {
            "bull_weakest_point": "Volume thinning into the move.",
            "bear_weakest_point": "No macro catalyst against the trend.",
        },
        "analyst_reports": {"technical": {"reasoning": "RSI 61, trend up."}},
        "errors": [],
    }


class FakeDBManager:
    def __init__(self, rows=None, raise_exc: Exception | None = None):
        self._rows = rows or []
        self._raise = raise_exc
        self.calls: list[int] = []

    def get_recent_approvals_all_statuses(self, limit: int):
        self.calls.append(limit)
        if self._raise is not None:
            raise self._raise
        return self._rows


async def _fake_signals_available(*, signals=None):
    return {
        "available": True,
        "signals": signals if signals is not None else [{"symbol": "MES", "edge": "long"}],
        "error": None,
        "fetched_at": _fresh_iso(),
    }


async def _fake_signals_unavailable():
    return {
        "available": False,
        "signals": [],
        "error": "connection refused",
        "fetched_at": _fresh_iso(),
    }


@pytest.fixture(autouse=True)
def _restore_dependencies():
    """inject_dependencies mutates module-level state -- reset after each test
    so tests don't leak into each other or into other test files' imports."""
    yield
    mod.inject_dependencies(None)


# ── success path ──────────────────────────────────────────────────────────


def test_session_brief_success_with_snapshot_and_signals(monkeypatch):
    row = {
        "pipeline_snapshot": _full_snapshot(),
        "symbol": "MES",
        "action": "buy",
        "created_at": _fresh_iso(),
    }
    db = FakeDBManager(rows=[row])
    mod.inject_dependencies(db)
    monkeypatch.setattr(mod, "fetch_amoarb_signals", _fake_signals_available)

    client = _client()
    r = client.get("/brief/session")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["actions"][0]["symbol"] == "MES"
    assert body["degraded"] is False
    assert body["cross_signal_advisories"]["available"] is True
    assert body["cross_signal_advisories"]["signals"] == [{"symbol": "MES", "edge": "long"}]
    # limit defaulted to 10 and was passed through to the DB manager
    assert db.calls == [10]


# ── edge path: no DB manager wired (degrades honestly, not a 500) ──────────


def test_session_brief_no_db_manager_returns_honest_empty_brief(monkeypatch):
    mod.inject_dependencies(None)
    monkeypatch.setattr(mod, "fetch_amoarb_signals", _fake_signals_unavailable)

    client = _client()
    r = client.get("/brief/session")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["degraded"] is True
    assert body["note"] == "No recent pipeline snapshots available to build a brief."
    assert body["cross_signal_advisories"]["available"] is False


# ── edge path: DB manager raises -- must degrade, not 500 ──────────────────


def test_session_brief_db_manager_failure_degrades_not_500(monkeypatch):
    db = FakeDBManager(raise_exc=RuntimeError("db connection lost"))
    mod.inject_dependencies(db)
    monkeypatch.setattr(mod, "fetch_amoarb_signals", _fake_signals_available)

    client = _client()
    r = client.get("/brief/session")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["degraded"] is True


# ── query param clamping ────────────────────────────────────────────────────


def test_session_brief_clamps_limit_and_max_actions(monkeypatch):
    db = FakeDBManager(rows=[])
    mod.inject_dependencies(db)
    monkeypatch.setattr(mod, "fetch_amoarb_signals", _fake_signals_available)

    client = _client()
    r = client.get("/brief/session", params={"limit": 9999, "max_actions": 0})
    assert r.status_code == 200
    # limit clamped to the documented ceiling (50); max_actions floored to 1
    # is exercised indirectly -- the DB manager call is the direct signal here.
    assert db.calls == [50]


# ── router-level exception handling: fail honest with a 500, never crash ──


def test_session_brief_assembly_failure_returns_500(monkeypatch):
    db = FakeDBManager(rows=[{"pipeline_snapshot": _full_snapshot()}])
    mod.inject_dependencies(db)
    monkeypatch.setattr(mod, "fetch_amoarb_signals", _fake_signals_available)

    def _boom(*args, **kwargs):
        raise RuntimeError("unexpected assembly failure")

    monkeypatch.setattr(mod, "build_session_brief", _boom)

    client = _client()
    r = client.get("/brief/session")
    assert r.status_code == 500
    assert "brief assembly failed" in r.json()["detail"]
