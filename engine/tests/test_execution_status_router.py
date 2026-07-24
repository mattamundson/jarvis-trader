"""
Tests for engine/routers/execution_status_router.py (GET /execution/fidelity-status).

Mounts ONLY the router on a minimal app. Mocks the reused proactive-validation
endpoints (get_execution_fidelity / get_slippage_analytics) and points the
module's SQLite path at an isolated tmp DB so the aggregator's own read-only
DB logic is exercised without touching the real jarvis_trader.db.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.execution_status_router as mod
from routers.execution_status_router import router
from routers.proactive_validation_router import (
    ExecutionFidelityReport,
    SlippageAnalyticsReport,
    ValidationCheck,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _client() -> TestClient:
    return TestClient(_app())


def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE pending_trade_approvals (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)"
    )
    con.execute(
        "INSERT INTO pending_trade_approvals (status, created_at) "
        "VALUES ('pending', '2026-01-01T00:00:00+00:00')"
    )
    con.execute(
        "CREATE TABLE ibkr_fills (symbol TEXT, side TEXT, quantity INTEGER, price REAL, "
        "fill_time TEXT, order_ref TEXT)"
    )
    con.execute(
        "INSERT INTO ibkr_fills VALUES ('MES', 'BUY', 1, 5300.0, '2026-07-01T00:00:00Z', 'JARVIS-1')"
    )
    con.execute(
        "CREATE TABLE paper_trades (symbol TEXT, side TEXT, quantity INTEGER, entry_price REAL, "
        "entry_time TEXT, slippage_ticks REAL, status TEXT)"
    )
    con.execute(
        "INSERT INTO paper_trades VALUES "
        "('MES', 'BUY', 1, 5300.0, '2026-07-01T00:00:00Z', 0.5, 'open')"
    )
    con.commit()
    con.close()


def _fidelity_report(symbol: str) -> ExecutionFidelityReport:
    return ExecutionFidelityReport(
        symbol=symbol,
        generated_at="2026-07-09T00:00:00+00:00",
        overall="APPROVED",
        measuring_real_fills=True,
        checks=[
            ValidationCheck(
                name="Fill Sample",
                status="pass",
                value="60 fills",
                threshold=">=60",
                message="ok",
            )
        ],
        summary="ok",
        advisory_note="advisory",
    )


def _slippage_report(symbol: str) -> SlippageAnalyticsReport:
    return SlippageAnalyticsReport(
        symbol=symbol,
        generated_at="2026-07-09T00:00:00+00:00",
        measuring_real_fills=True,
        n=10,
        mean_abs_slippage_ticks=0.4,
        p95_abs_slippage_ticks=1.1,
        max_abs_slippage_ticks=2.0,
        note="advisory",
    )


def test_fidelity_status_success_aggregates_db_and_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "jarvis_trader.db"
    _make_db(db_path)
    monkeypatch.setattr(mod, "_DB_PATH", db_path)

    with (
        patch(
            "routers.proactive_validation_router.get_execution_fidelity",
            new=AsyncMock(side_effect=lambda sym: _fidelity_report(sym)),
        ),
        patch(
            "routers.proactive_validation_router.get_slippage_analytics",
            new=AsyncMock(side_effect=lambda sym: _slippage_report(sym)),
        ),
    ):
        r = _client().get("/execution/fidelity-status", params={"symbols": "MES,MGC"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["symbols"]) == 2
    assert body["symbols"][0]["symbol"] == "MES"
    assert body["symbols"][0]["fidelity_overall"] == "APPROVED"
    assert body["symbols"][0]["checks_passing"] == 1
    assert body["symbols"][0]["checks_total"] == 1
    assert body["symbols"][0]["slippage_n"] == 10
    assert body["pending_approvals"]["count"] == 1
    assert body["pending_approvals"]["oldest_age_min"] is not None
    assert len(body["recent_fills"]) == 1
    assert body["recent_fills"][0]["order_ref"] == "JARVIS-1"
    assert len(body["open_trades"]) == 1
    assert body["open_trades"][0]["symbol"] == "MES"


def test_fidelity_status_missing_db_degrades_gracefully(tmp_path, monkeypatch):
    """No DB on disk yet (fresh install) -> safe defaults, not a 500."""
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "does_not_exist.db")

    with (
        patch(
            "routers.proactive_validation_router.get_execution_fidelity",
            new=AsyncMock(side_effect=lambda sym: _fidelity_report(sym)),
        ),
        patch(
            "routers.proactive_validation_router.get_slippage_analytics",
            new=AsyncMock(side_effect=lambda sym: _slippage_report(sym)),
        ),
    ):
        r = _client().get("/execution/fidelity-status", params={"symbols": "MES"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending_approvals"] == {"count": 0, "oldest_age_min": None}
    assert body["recent_fills"] == []
    assert body["open_trades"] == []
    # Validation aggregation is independent of the DB and still succeeds.
    assert len(body["symbols"]) == 1


def test_fidelity_status_per_symbol_failure_is_swallowed_not_500(tmp_path, monkeypatch):
    """One symbol's fidelity lookup raising must not fail the whole aggregate
    call -- this endpoint is advisory/best-effort and should omit the failed
    symbol rather than 500 the whole cockpit widget."""
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "does_not_exist.db")

    async def _boom(_sym):
        raise RuntimeError("db locked")

    with (
        patch("routers.proactive_validation_router.get_execution_fidelity", new=_boom),
        patch(
            "routers.proactive_validation_router.get_slippage_analytics",
            new=AsyncMock(side_effect=lambda sym: _slippage_report(sym)),
        ),
    ):
        r = _client().get("/execution/fidelity-status", params={"symbols": "MES"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbols"] == []


def test_fidelity_status_defaults_to_MES_MGC_when_symbols_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "does_not_exist.db")

    with (
        patch(
            "routers.proactive_validation_router.get_execution_fidelity",
            new=AsyncMock(side_effect=lambda sym: _fidelity_report(sym)),
        ),
        patch(
            "routers.proactive_validation_router.get_slippage_analytics",
            new=AsyncMock(side_effect=lambda sym: _slippage_report(sym)),
        ),
    ):
        r = _client().get("/execution/fidelity-status", params={"symbols": ""})

    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["symbol"] for s in body["symbols"]] == ["MES", "MGC"]
