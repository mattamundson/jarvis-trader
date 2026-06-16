"""
Router-level tests for the readiness edge-mode wiring (GET /readiness/phase3).

Verifies the router honors the OPT-IN ?edge_mode= query param and surfaces an
``edge_mode`` key in the payload, WITHOUT changing the default behavior:

- no param        -> evaluate_with_edge_mode(db, mode=None) -> env-honored default
                     (paper_accrual unless READINESS_EDGE_MODE says otherwise)
- ?edge_mode=...  -> passed straight through (read-only inspection; never persisted)

The route stays informational: it never reads/writes LIVE_TRADING_ENABLED,
safety_layer, or engine/.env.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def readiness_client():
    """Bare FastAPI app mounting only the readiness router (auth overridden)."""
    from middleware.auth import verify_api_key
    from routers.readiness_router import router

    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def _canned_report(edge_mode):
    """Minimal report with the shape _render_markdown / JSON callers expect."""
    return {
        "summary": {
            "pass": 1,
            "fail": 0,
            "total": 1,
            "severity_breakdown": {
                "blocker": {"pass": 1, "fail": 0},
                "warning": {"pass": 0, "fail": 0},
                "info": {"pass": 0, "fail": 0},
            },
            "overall": "GO",
        },
        "criteria": [
            {
                "name": "x",
                "description": "d",
                "status": "PASS",
                "evidence": "e",
                "severity": "blocker",
            }
        ],
        "evaluated_at": "2026-06-16T00:00:00+00:00",
        "edge_mode": edge_mode,
    }


def test_route_default_passes_mode_none(readiness_client):
    """No ?edge_mode= -> the route calls evaluate_with_edge_mode(db, mode=None)."""
    captured = {}

    def _spy(db_path, mode=None):
        captured["mode"] = mode
        return _canned_report(mode or "paper_accrual")

    with (
        patch("readiness.phase3_criteria.evaluate_with_edge_mode", _spy),
        patch("routers.readiness_router._default_db_path", return_value="unused.db"),
    ):
        resp = readiness_client.get("/readiness/phase3")

    assert resp.status_code == 200
    # mode=None lets the evaluator honor READINESS_EDGE_MODE (default unchanged).
    assert captured["mode"] is None
    assert resp.json()["edge_mode"] == "paper_accrual"


def test_route_passes_explicit_edge_mode(readiness_client):
    """?edge_mode=wfo_plus_fidelity is passed straight through to the evaluator."""
    captured = {}

    def _spy(db_path, mode=None):
        captured["mode"] = mode
        return _canned_report(mode)

    with (
        patch("readiness.phase3_criteria.evaluate_with_edge_mode", _spy),
        patch("routers.readiness_router._default_db_path", return_value="unused.db"),
    ):
        resp = readiness_client.get("/readiness/phase3?edge_mode=wfo_plus_fidelity")

    assert resp.status_code == 200
    assert captured["mode"] == "wfo_plus_fidelity"
    assert resp.json()["edge_mode"] == "wfo_plus_fidelity"


def test_route_markdown_still_renders_with_edge_mode(readiness_client):
    """?format=markdown still returns the Markdown report after the wiring switch."""
    with (
        patch(
            "readiness.phase3_criteria.evaluate_with_edge_mode",
            lambda db_path, mode=None: _canned_report(mode or "paper_accrual"),
        ),
        patch("routers.readiness_router._default_db_path", return_value="unused.db"),
    ):
        resp = readiness_client.get("/readiness/phase3?format=markdown")

    assert resp.status_code == 200
    assert "Phase 3" in resp.text


def test_route_real_default_payload_includes_edge_mode(readiness_client, tmp_path, monkeypatch):
    """Integration: the real default evaluator now surfaces edge_mode=paper_accrual.

    Confirms the consumer switch from evaluate_all_criteria to
    evaluate_with_edge_mode is byte-compatible — still 10 criteria — and only
    ADDS the edge_mode key.
    """
    monkeypatch.delenv("READINESS_EDGE_MODE", raising=False)

    fake_db = str(tmp_path / "test.db")
    conn = sqlite3.connect(fake_db)
    conn.executescript(
        "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, trade_id TEXT, "
        "symbol TEXT NOT NULL DEFAULT 'MES', side TEXT NOT NULL DEFAULT 'LONG', "
        "quantity REAL NOT NULL DEFAULT 1, entry_price REAL NOT NULL DEFAULT 100, "
        "entry_time TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z', "
        "status TEXT NOT NULL DEFAULT 'open', notes TEXT DEFAULT ''); "
        "CREATE TABLE pnl_snapshots (date TEXT PRIMARY KEY, daily_pnl REAL "
        "NOT NULL DEFAULT 0.0, portfolio_equity REAL NOT NULL DEFAULT 0.0, "
        "peak_equity REAL NOT NULL DEFAULT 0.0, consecutive_losses INTEGER "
        "NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now'))); "
        "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')));"
    )
    conn.commit()
    conn.close()

    _cov = Mock(stdout="risk/safety_layer.py   1735   103   97%\n", stderr="", returncode=0)
    with (
        patch("readiness.phase3_criteria.subprocess.run", return_value=_cov),
        patch("routers.readiness_router._default_db_path", return_value=fake_db),
    ):
        resp = readiness_client.get("/readiness/phase3")

    assert resp.status_code == 200
    data = resp.json()
    assert data["edge_mode"] == "paper_accrual"
    assert data["summary"]["total"] == 10
    assert len(data["criteria"]) == 10
