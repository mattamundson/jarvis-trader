"""
A9 — kill-switch activation timestamp observability.

Before this change the activation time was persisted to system_state.updated_at
but never exposed, so an API consumer could not tell a just-recovered-from-halt
system from one running clean for hours. These tests pin:

  1. activate_kill_switch stamps last_kill_switch_ts + reason on get_status().
  2. The stamp SURVIVES a deactivate (post-mortem can still see a recent trip).
  3. The stamp PERSISTS across a restart (hydrated from system_state).
  4. /safety/status exposes last_kill_switch_ts + a computed
     time_since_kill_switch_sec.

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_safety_kill_switch_timestamp.py -q
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

os.environ.setdefault("API_KEY", "test-key")

from risk.safety_layer import KillSwitchReason, SafetyLayer  # noqa: E402


def _db_with_system_state(tmp_path) -> str:
    db = str(tmp_path / "safety.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    )
    conn.commit()
    conn.close()
    return db


def test_activation_stamps_timestamp(mock_settings, tmp_path):
    sl = SafetyLayer(mock_settings, db_path=_db_with_system_state(tmp_path))
    sl.activate_kill_switch(KillSwitchReason.MANUAL, "unit test")

    st = sl.get_status()
    assert st["last_kill_switch_ts"] is not None
    datetime.fromisoformat(st["last_kill_switch_ts"])  # ISO-parseable
    assert st["last_kill_switch_reason_value"] == KillSwitchReason.MANUAL.value


def test_timestamp_survives_deactivate(mock_settings, tmp_path):
    sl = SafetyLayer(mock_settings, db_path=_db_with_system_state(tmp_path))
    sl.activate_kill_switch(KillSwitchReason.DAILY_LOSS_LIMIT, "halt")
    ts = sl.get_status()["last_kill_switch_ts"]
    assert ts is not None

    sl.deactivate_kill_switch(authorized_by="human")
    st = sl.get_status()
    assert st["is_killed"] is False  # halt cleared
    assert st["last_kill_switch_ts"] == ts  # but history preserved
    assert st["last_kill_switch_reason_value"] == KillSwitchReason.DAILY_LOSS_LIMIT.value


def test_timestamp_persists_across_restart(mock_settings, tmp_path):
    db = _db_with_system_state(tmp_path)
    sl1 = SafetyLayer(mock_settings, db_path=db)
    sl1.activate_kill_switch(KillSwitchReason.MAX_DRAWDOWN, "drawdown halt")
    ts = sl1.get_status()["last_kill_switch_ts"]
    assert ts is not None

    # Fresh instance on the same DB hydrates the history on construction.
    sl2 = SafetyLayer(mock_settings, db_path=db)
    st = sl2.get_status()
    assert st["last_kill_switch_ts"] == ts
    assert st["last_kill_switch_reason_value"] == KillSwitchReason.MAX_DRAWDOWN.value


def test_never_fired_reports_none(mock_settings, tmp_path):
    sl = SafetyLayer(mock_settings, db_path=_db_with_system_state(tmp_path))
    st = sl.get_status()
    assert st["last_kill_switch_ts"] is None
    assert st["last_kill_switch_reason_value"] is None


def test_safety_status_endpoint_exposes_time_since(mock_settings, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi.errors import RateLimitExceeded

    import routers.safety_router as sr
    from middleware.rate_limit import limiter

    sl = SafetyLayer(mock_settings, db_path=_db_with_system_state(tmp_path))
    sl.activate_kill_switch(KillSwitchReason.MANUAL, "endpoint test")
    sr._safety_layer = sl
    sr._loss_tracker = None

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, lambda r, e: None)  # type: ignore[arg-type]
    app.include_router(sr.router)
    client = TestClient(app)

    resp = client.get("/safety/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_kill_switch_ts"] is not None
    assert body["last_kill_switch_reason_value"] == KillSwitchReason.MANUAL.value
    assert isinstance(body["time_since_kill_switch_sec"], (int, float))
    assert body["time_since_kill_switch_sec"] >= 0
