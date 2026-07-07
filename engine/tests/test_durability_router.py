"""Tests for GET /ops/durability (engine/routers/durability_router.py).

Mounts ONLY the router on a minimal app. Confirms it computes clean-run
durability from the down-alert outage ledger and -- the key property -- returns
an honest empty state (has_data: false) instead of a fabricated streak when no
ledger exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.durability_router import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _write(events: Path, state: Path, outages: list[dict], state_obj: dict) -> None:
    events.write_text("\n".join(json.dumps(o) for o in outages) + "\n", encoding="utf-8")
    state.write_text(json.dumps(state_obj), encoding="utf-8")


def test_durability_empty_state_not_fabricated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOWN_ALERT_EVENTS", str(tmp_path / "none.jsonl"))
    monkeypatch.setenv("DOWN_ALERT_STATE", str(tmp_path / "none.json"))
    r = TestClient(_app()).get("/ops/durability")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_data"] is False
    assert body["outage_count"] == 0
    assert body["current_streak_days"] is None  # no fabricated streak


def test_durability_counts_outage_and_streak(tmp_path, monkeypatch) -> None:
    events = tmp_path / "ev.jsonl"
    state = tmp_path / "st.json"
    # One completed outage: down 2 min, recovered; monitoring began a day earlier.
    _write(
        events,
        state,
        [
            {
                "downSince": "2026-06-30T00:00:00+00:00",
                "recoveredAt": "2026-06-30T00:02:00+00:00",
                "durationMs": 120_000,
                "alerted": True,
            }
        ],
        {
            "consecutiveFailures": 0,
            "alerted": False,
            "downSince": None,
            "monitoringSince": "2026-06-29T00:00:00+00:00",
        },
    )
    monkeypatch.setenv("DOWN_ALERT_EVENTS", str(events))
    monkeypatch.setenv("DOWN_ALERT_STATE", str(state))
    body = TestClient(_app()).get("/ops/durability").json()
    assert body["has_data"] is True
    assert body["currently_down"] is False
    assert body["outage_count"] == 1
    assert body["total_downtime_ms"] == 120_000
    # A clean streak has accrued since the recovery (positive, non-fabricated).
    assert body["current_streak_days"] is not None and body["current_streak_days"] >= 0
    assert body["last_outage"]["durationMs"] == 120_000


def test_durability_reports_active_outage(tmp_path, monkeypatch) -> None:
    events = tmp_path / "ev2.jsonl"
    state = tmp_path / "st2.json"
    events.write_text("", encoding="utf-8")
    state.write_text(
        json.dumps(
            {
                "consecutiveFailures": 3,
                "alerted": True,
                "downSince": "2026-06-30T12:00:00+00:00",
                "monitoringSince": "2026-06-29T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOWN_ALERT_EVENTS", str(events))
    monkeypatch.setenv("DOWN_ALERT_STATE", str(state))
    body = TestClient(_app()).get("/ops/durability").json()
    assert body["currently_down"] is True
    assert body["down_since"] == "2026-06-30T12:00:00+00:00"
