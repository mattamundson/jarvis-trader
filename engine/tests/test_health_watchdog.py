"""
Tests for engine.scripts.health_watchdog and engine.scripts.health_uptime.

Covers:
  - test_record_reachable_response
  - test_record_timeout
  - test_transition_detection_down
  - test_transition_detection_recovery
  - test_compute_uptime
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.health_uptime import compute_uptime
from scripts.health_watchdog import (
    _ensure_table,
    _insert_snapshot,
    _last_n_rows,
    _open_db,
    detect_transitions,
    run,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    db_path = tmp_path / "test_jarvis.db"
    conn = _open_db(db_path)
    conn.close()
    return db_path


def _insert_row(conn, ts_utc, reachable, llm=1, tv=1, ks=0):
    conn.execute(
        """
        INSERT OR IGNORE INTO health_snapshots
            (ts_utc, status, reachable, llm_healthy, tv_mcp_healthy,
             ibkr_data, ibkr_exec, kill_switch, uptime_seconds, raw_json, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            "ok" if reachable else "unreachable",
            1 if reachable else 0,
            llm,
            tv,
            1,
            1,
            ks,
            120.0,
            None,
            ts_utc,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# test_record_reachable_response
# ---------------------------------------------------------------------------


def test_record_reachable_response(tmp_db):
    payload = {
        "status": "ok",
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
        "kill_switch_active": False,
        "uptime_seconds": 999.0,
    }
    conn = sqlite3.connect(str(tmp_db))
    _ensure_table(conn)
    ts = "2026-05-07T14:00:00Z"
    _insert_snapshot(conn, ts, reachable=True, payload=payload, fetched_at=ts)

    row = conn.execute(
        "SELECT reachable, status, llm_healthy, tv_mcp_healthy, kill_switch, uptime_seconds "
        "FROM health_snapshots WHERE ts_utc = ?",
        (ts,),
    ).fetchone()
    conn.close()

    assert row is not None
    reachable, status, llm, tv, ks, uptime = row
    assert reachable == 1
    assert status == "ok"
    assert llm == 1
    assert tv == 1
    assert ks == 0
    assert uptime == pytest.approx(999.0)


# ---------------------------------------------------------------------------
# test_record_timeout
# ---------------------------------------------------------------------------


def test_record_timeout(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    _ensure_table(conn)
    ts = "2026-05-07T14:05:00Z"
    _insert_snapshot(conn, ts, reachable=False, payload=None, fetched_at=ts)

    row = conn.execute(
        "SELECT reachable, status, llm_healthy, tv_mcp_healthy, raw_json "
        "FROM health_snapshots WHERE ts_utc = ?",
        (ts,),
    ).fetchone()
    conn.close()

    assert row is not None
    reachable, status, llm, tv, raw = row
    assert reachable == 0
    assert status == "unreachable"
    assert llm is None
    assert tv is None
    assert raw is None


# ---------------------------------------------------------------------------
# test_transition_detection_down
# ---------------------------------------------------------------------------


def test_transition_detection_down():
    rows = [
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 1, "kill_switch": 0},
        {"reachable": 0, "llm_healthy": None, "tv_mcp_healthy": None, "kill_switch": None},
    ]
    alerts = detect_transitions(rows)
    assert len(alerts) == 1
    assert "ENGINE DOWN" in alerts[0]


# ---------------------------------------------------------------------------
# test_transition_detection_recovery
# ---------------------------------------------------------------------------


def test_transition_detection_recovery():
    rows = [
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 1, "kill_switch": 0},
        {"reachable": 0, "llm_healthy": None, "tv_mcp_healthy": None, "kill_switch": None},
        {"reachable": 0, "llm_healthy": None, "tv_mcp_healthy": None, "kill_switch": None},
        {"reachable": 0, "llm_healthy": None, "tv_mcp_healthy": None, "kill_switch": None},
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 1, "kill_switch": 0},
    ]
    alerts = detect_transitions(rows)
    assert len(alerts) == 1
    assert "BACK UP" in alerts[0]
    assert "15m" in alerts[0]


# ---------------------------------------------------------------------------
# test_compute_uptime
# ---------------------------------------------------------------------------


def test_compute_uptime(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    _ensure_table(conn)

    rows_data = [
        ("2026-05-07T13:00:00Z", 1),
        ("2026-05-07T13:05:00Z", 1),
        ("2026-05-07T13:10:00Z", 0),
        ("2026-05-07T13:15:00Z", 1),
        ("2026-05-07T13:20:00Z", 1),
    ]
    for ts, reach in rows_data:
        _insert_row(conn, ts, reach)
    conn.close()

    start = datetime(2026, 5, 7, 13, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 7, 13, 25, 0, tzinfo=timezone.utc)
    result = compute_uptime(start, end, db_path=tmp_db)

    assert result["polls_total"] == 5
    assert result["polls_reachable"] == 4
    assert result["uptime_pct"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# test_run_smoke_reachable
# ---------------------------------------------------------------------------


def test_run_smoke_reachable(tmp_db):
    fake_payload = {
        "status": "ok",
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
        "kill_switch_active": False,
        "uptime_seconds": 50.0,
    }
    with (
        patch("scripts.health_watchdog._poll_health", return_value=(True, fake_payload)),
        patch("scripts.health_watchdog._get_pm2_restart_count", return_value=None),
    ):
        result = run(db_path=tmp_db, no_discord=True, force=True)

    assert result["reachable"] is True
    assert result["status"] == "ok"
    assert result["alerts"] == []

    conn = sqlite3.connect(str(tmp_db))
    count = conn.execute("SELECT COUNT(*) FROM health_snapshots").fetchone()[0]
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# test_run_smoke_down_then_up
# ---------------------------------------------------------------------------


def test_run_smoke_down_then_up(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    _ensure_table(conn)
    _insert_row(conn, "2026-05-07T09:25:00Z", reachable=1)
    conn.close()

    fake_ok = {
        "status": "ok",
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
        "kill_switch_active": False,
        "uptime_seconds": 10.0,
    }

    ts_down = "2026-05-07T09:30:00Z"
    ts_up = "2026-05-07T09:35:00Z"
    ts_up2 = "2026-05-07T09:40:00Z"

    with (
        patch("scripts.health_watchdog._poll_health", return_value=(False, None)),
        patch("scripts.health_watchdog._get_pm2_restart_count", return_value=None),
        patch(
            "scripts.health_watchdog.datetime",
            wraps=datetime,
        ) as mock_dt,
    ):
        mock_dt.now.return_value = datetime(2026, 5, 7, 13, 30, 0, tzinfo=timezone.utc)
        result = run(db_path=tmp_db, no_discord=True, force=True)

    assert result["reachable"] is False
    assert any("ENGINE DOWN" in a for a in result["alerts"])

    conn2 = sqlite3.connect(str(tmp_db))
    conn2.execute(
        "UPDATE health_snapshots SET ts_utc = ?, fetched_at = ? WHERE reachable = 0",
        (ts_down, ts_down),
    )
    conn2.commit()
    conn2.close()

    with (
        patch("scripts.health_watchdog._poll_health", return_value=(True, fake_ok)),
        patch("scripts.health_watchdog._get_pm2_restart_count", return_value=None),
        patch(
            "scripts.health_watchdog.datetime",
            wraps=datetime,
        ) as mock_dt2,
    ):
        mock_dt2.now.return_value = datetime(2026, 5, 7, 13, 35, 0, tzinfo=timezone.utc)
        result2 = run(db_path=tmp_db, no_discord=True, force=True)

    assert result2["reachable"] is True
    assert any("BACK UP" in a for a in result2["alerts"])


# ---------------------------------------------------------------------------
# test_kill_switch_transition
# ---------------------------------------------------------------------------


def test_kill_switch_transition():
    rows = [
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 1, "kill_switch": 0},
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 1, "kill_switch": 1},
    ]
    alerts = detect_transitions(rows)
    assert any("KILL SWITCH" in a for a in alerts)


# ---------------------------------------------------------------------------
# test_sustained_tv_mcp_alert
# ---------------------------------------------------------------------------


def test_sustained_tv_mcp_alert():
    rows = [
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 1, "kill_switch": 0},
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 0, "kill_switch": 0},
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 0, "kill_switch": 0},
        {"reachable": 1, "llm_healthy": 1, "tv_mcp_healthy": 0, "kill_switch": 0},
    ]
    alerts = detect_transitions(rows)
    assert any("TV MCP" in a for a in alerts)
