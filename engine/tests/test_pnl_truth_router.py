"""Tests for GET /pnl/truth (engine/routers/pnl_truth_router.py).

Mounts ONLY the router on a minimal app so the test is fast and isolated from the
full engine wiring. Confirms the endpoint exposes the honest verdict and -- the
key property -- DEGRADES (realized_pnl: null) instead of fabricating a number when
the ledger is absent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.pnl_truth_router import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _make_db(path: Path, rows: list[tuple[str, float | None]]) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE paper_trades (status TEXT, pnl REAL)")
    con.executemany("INSERT INTO paper_trades (status, pnl) VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_pnl_truth_trusted(tmp_path, monkeypatch) -> None:
    db = tmp_path / "jarvis_trader.db"
    _make_db(db, [("closed", 12.5), ("closed", -2.5), ("phantom", 4982.5), ("open", None)])
    monkeypatch.setenv("JARVIS_SQLITE_DB", str(db))
    r = TestClient(_app()).get("/pnl/truth")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "TRUSTED" and body["trusted"] is True
    assert body["realized_pnl"] == 10.0  # phantom 4982.5 excluded
    assert body["closed_trades"] == 2 and body["excluded_trades"] == 1


def test_pnl_truth_missing_db_degrades_not_zero(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_SQLITE_DB", str(tmp_path / "does_not_exist.db"))
    r = TestClient(_app()).get("/pnl/truth")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DEGRADED" and body["trusted"] is False
    assert body["realized_pnl"] is None  # never a fabricated 0
    assert "db_not_found" in body["reasons"]
