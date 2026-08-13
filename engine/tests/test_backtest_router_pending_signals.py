"""
Tests for the pending-signals endpoints in engine/routers/backtest_router.py
(GET /paper/pending-signals, POST /paper/reset-pending-signals).

Goal
----
Verify the wiring for GT-40: the dashboard's paper page reset control calls
POST /paper/reset-pending-signals, which previously had no route at all
(404). This confirms the route exists, clears the MGC-daily-scanner queue
file, and reports how many signals were cleared.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from routers import backtest_router  # noqa: E402

PENDING_FILE = ENGINE_DIR / "backtest" / "results" / "pending_signals.json"


@pytest.fixture
def clean_pending_file():
    """Ensure the pending-signals file starts and ends absent for each test."""
    original = PENDING_FILE.read_text(encoding="utf-8") if PENDING_FILE.exists() else None
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()
    yield
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()
    if original is not None:
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_FILE.write_text(original, encoding="utf-8")


@pytest.fixture
def client(clean_pending_file):
    app = FastAPI()
    app.include_router(backtest_router.router)
    return TestClient(app)


def _write_pending(signals):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(signals), encoding="utf-8")


# ── Tests ────────────────────────────────────────────────────────────────────


def test_get_pending_signals_missing_file_returns_empty_list(client):
    resp = client.get("/paper/pending-signals")
    assert resp.status_code == 200
    assert resp.json() == []


def test_reset_pending_signals_missing_file_returns_zero(client):
    resp = client.post("/paper/reset-pending-signals")
    assert resp.status_code == 200
    assert resp.json() == {"cleared": 0}
    # A reset should leave the file present and empty, not error later reads.
    follow_up = client.get("/paper/pending-signals")
    assert follow_up.status_code == 200
    assert follow_up.json() == []


def test_reset_pending_signals_clears_existing_queue(client):
    _write_pending(
        [
            {"date": "2026-07-27", "symbol": "MGC", "signal": "ENTRY_NOW", "status": "pending"},
            {"date": "2026-07-28", "symbol": "MGC", "signal": "ENTRY_NOW", "status": "pending"},
        ]
    )

    resp = client.post("/paper/reset-pending-signals")
    assert resp.status_code == 200
    assert resp.json() == {"cleared": 2}

    follow_up = client.get("/paper/pending-signals")
    assert follow_up.status_code == 200
    assert follow_up.json() == []


def test_reset_pending_signals_handles_corrupt_file(client):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text("not json", encoding="utf-8")

    resp = client.post("/paper/reset-pending-signals")
    assert resp.status_code == 200
    assert resp.json() == {"cleared": 0}

    follow_up = client.get("/paper/pending-signals")
    assert follow_up.status_code == 200
    assert follow_up.json() == []
