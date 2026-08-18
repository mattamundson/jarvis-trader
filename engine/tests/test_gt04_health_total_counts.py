"""Regression tests for GT-04: /health dashboard "Total Decisions" and
"Total Alerts" tiles must report the TRUE row count, not the request's
``limit`` query parameter.

Root cause: ``GET /portfolio/history/decisions`` and ``GET /alerts/history``
returned ``count: len(rows)`` where ``rows`` was bounded by ``LIMIT ?``.
Once the true row count exceeded ``limit`` (default 500, per
``DatabaseStatsCard.tsx``), the dashboard tile silently showed 500 instead
of the real total (e.g. 11,920 decisions / 3,057 alerts).

Fix: ``DatabaseManager.count_decisions`` / ``count_alert_history`` run a
real ``SELECT COUNT(*)`` (unbounded by ``LIMIT``); the routers now return
a ``total`` field distinct from the limit-bounded ``count``/``decisions``/
``alerts`` array; the frontend reads ``total`` first.

Two layers are covered:
  1. DB-layer: ``count_decisions`` / ``count_alert_history`` against a real
     SQLite fixture DB seeded with more rows than the page limit.
  2. Router-layer: ``/portfolio/history/decisions`` and ``/alerts/history``
     via FastAPI TestClient, asserting the JSON ``total`` field reflects
     the true count while ``count`` stays bounded by ``limit``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.manager import DatabaseManager
from routers import alerts_router, portfolio_router

# ---------------------------------------------------------------------------
# DB-layer: count_decisions / count_alert_history vs a real SQLite fixture
# ---------------------------------------------------------------------------


def _seed_decisions(db: DatabaseManager, n: int) -> None:
    for i in range(n):
        db.insert_decision(
            symbol="MES" if i % 2 == 0 else "MCL",
            action="buy" if i % 3 else "sell",
            confidence=0.5,
        )


def _seed_alerts(db: DatabaseManager, n: int) -> None:
    for i in range(n):
        db.insert_alert_log(
            alert_type="trade_opened" if i % 2 == 0 else "vix_alert",
            message=f"alert {i}",
        )


def test_count_decisions_exceeds_page_limit(tmp_path):
    """DB seeded with MORE rows than the page limit — count_decisions must
    return the true total, not the limit."""
    db = DatabaseManager(str(tmp_path / "gt04_decisions.db"))
    db.initialize()
    _seed_decisions(db, 60)

    page = db.get_decisions(limit=10)
    assert len(page) == 10  # bounded by limit, as before

    total = db.count_decisions()
    assert total == 60  # TRUE total, ignoring limit
    assert total != len(page)


def test_count_decisions_respects_symbol_filter(tmp_path):
    db = DatabaseManager(str(tmp_path / "gt04_decisions_sym.db"))
    db.initialize()
    _seed_decisions(db, 60)  # 30 MES, 30 MCL

    assert db.count_decisions(symbol="MES") == 30
    assert db.count_decisions(symbol="mcl") == 30  # case-insensitive, mirrors get_decisions


def test_count_alert_history_exceeds_page_limit(tmp_path):
    """DB seeded with MORE rows than the page limit — count_alert_history
    must return the true total, not the limit."""
    db = DatabaseManager(str(tmp_path / "gt04_alerts.db"))
    db.initialize()
    _seed_alerts(db, 45)

    page = db.get_alert_history(limit=10)
    assert len(page) == 10  # bounded by limit, as before

    total = db.count_alert_history()
    assert total == 45  # TRUE total, ignoring limit
    assert total != len(page)


def test_count_alert_history_respects_type_filter(tmp_path):
    db = DatabaseManager(str(tmp_path / "gt04_alerts_type.db"))
    db.initialize()
    _seed_alerts(db, 45)  # 23 trade_opened, 22 vix_alert

    assert db.count_alert_history(alert_type="trade_opened") == 23
    assert db.count_alert_history(alert_type="vix_alert") == 22


# ---------------------------------------------------------------------------
# Router-layer: /portfolio/history/decisions and /alerts/history
# ---------------------------------------------------------------------------


def test_decision_history_route_reports_true_total_not_limit(tmp_path):
    db = DatabaseManager(str(tmp_path / "gt04_decisions_route.db"))
    db.initialize()
    _seed_decisions(db, 60)

    app = FastAPI()
    app.include_router(portfolio_router.router, prefix="/portfolio")
    portfolio_router.inject_dependencies(pt=None, dbm=db)
    try:
        client = TestClient(app)
        resp = client.get("/portfolio/history/decisions", params={"limit": 10})
        assert resp.status_code == 200
        body = resp.json()

        assert body["count"] == 10  # page size, bounded by limit
        assert body["total"] == 60  # TRUE row count, NOT the limit
        assert body["total"] != body["count"]
        assert len(body["decisions"]) == 10
    finally:
        portfolio_router.inject_dependencies(pt=None, dbm=None)


def test_alert_history_route_reports_true_total_not_limit(tmp_path):
    db = DatabaseManager(str(tmp_path / "gt04_alerts_route.db"))
    db.initialize()
    _seed_alerts(db, 45)

    app = FastAPI()
    app.include_router(alerts_router.router)
    alerts_router.inject_dependencies(db_manager=db)
    try:
        client = TestClient(app)
        resp = client.get("/alerts/history", params={"limit": 10})
        assert resp.status_code == 200
        body = resp.json()

        assert body["count"] == 10  # page size, bounded by limit
        assert body["total"] == 45  # TRUE row count, NOT the limit
        assert body["total"] != body["count"]
        assert len(body["alerts"]) == 10
    finally:
        alerts_router._db_manager = None  # type: ignore[attr-defined]


def test_decision_history_route_total_falls_back_when_db_lacks_count_method(tmp_path):
    """A DB fixture without count_decisions() (older fakes in other test
    files) must not 500 — the router falls back to len(rows) so total ==
    count in that degraded case, rather than crashing."""

    class _LegacyFakeDB:
        def get_decisions(self, symbol=None, action=None, limit=100):
            return [{"id": i, "symbol": "MES", "action": "buy"} for i in range(min(limit, 3))]

    app = FastAPI()
    app.include_router(portfolio_router.router, prefix="/portfolio")
    portfolio_router.inject_dependencies(pt=None, dbm=_LegacyFakeDB())
    try:
        client = TestClient(app)
        resp = client.get("/portfolio/history/decisions", params={"limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["total"] == 2  # fallback: no count_decisions() -> total == count
    finally:
        portfolio_router.inject_dependencies(pt=None, dbm=None)


def test_alert_history_route_total_falls_back_when_db_lacks_count_method():
    """Mirrors the decisions fallback test above for /alerts/history."""

    class _LegacyFakeDB:
        def get_alert_history(self, limit=100, alert_type=None):
            return [{"id": i, "alert_type": "trade_opened"} for i in range(min(limit, 3))]

    app = FastAPI()
    app.include_router(alerts_router.router)
    alerts_router.inject_dependencies(db_manager=_LegacyFakeDB())
    try:
        client = TestClient(app)
        resp = client.get("/alerts/history", params={"limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["total"] == 2  # fallback: no count_alert_history() -> total == count
    finally:
        alerts_router._db_manager = None  # type: ignore[attr-defined]
