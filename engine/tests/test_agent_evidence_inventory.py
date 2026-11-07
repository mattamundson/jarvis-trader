"""Offline clock inventory: actual SQLite schema shape, no service calls."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.agent_evidence_inventory import inventory, main

T0 = datetime(2026, 10, 1, 14, tzinfo=UTC)


def _pipeline(*, clock: datetime | None = T0) -> str:
    value = clock.isoformat() if clock is not None else None
    return json.dumps({
        "debate_result": {
            "timestamp": value,
            "bull_report": {"symbol": "MES", "timestamp": value},
            "bear_report": {"symbol": "MES", "timestamp": value},
        }
    })


def _db(path: Path, rows: list[tuple[str, str, str | None]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE decisions (id INTEGER PRIMARY KEY, symbol TEXT, "
            "timestamp TEXT, full_pipeline_json TEXT)"
        )
        conn.executemany(
            "INSERT INTO decisions (symbol, timestamp, full_pipeline_json) VALUES (?, ?, ?)",
            rows,
        )


def test_inventory_counts_every_scoped_row_once_and_never_certifies(tmp_path):
    db = tmp_path / "decisions.db"
    naive = T0.replace(tzinfo=None)
    _db(db, [
        ("MES", naive.isoformat(), _pipeline(clock=naive)),
        ("MES", T0.isoformat(), _pipeline(clock=naive)),
        ("MES", T0.isoformat(), _pipeline()),
        ("MES", T0.isoformat(), None),
        ("ES", T0.isoformat(), _pipeline()),
    ])
    before = db.read_bytes()
    result = inventory(db)
    assert db.read_bytes() == before
    assert result["total_decisions_all_symbols"] == 5
    assert result["scoped_decisions"] == 4
    assert result["first_blocker_counts"] == {
        "bull_report.timestamp must have timezone": 1,
        "clocks_structurally_ready_not_certified": 1,
        "decision.timestamp must have timezone": 1,
        "missing_or_invalid_pipeline_json": 1,
    }
    assert result["comparison_eligible_certified"] == 0


def test_inventory_rejects_future_reports_and_missing_debate(tmp_path):
    db = tmp_path / "decisions.db"
    future = T0 + timedelta(seconds=1)
    _db(db, [
        ("MES", T0.isoformat(), _pipeline(clock=future)),
        ("SPY", T0.isoformat(), json.dumps({"debate_result": None})),
    ])
    assert inventory(db)["first_blocker_counts"] == {
        "missing_debate_result": 1,
        "report_after_decision": 1,
    }


def test_cli_returns_not_evaluated_on_missing_database(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "missing.db")]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_EVALUATED"


def test_empty_database_never_becomes_zero_edge(tmp_path):
    db = tmp_path / "decisions.db"
    _db(db, [])
    result = inventory(db)
    assert result["scoped_decisions"] == 0
    assert result["first_blocker_counts"] == {}
    assert result["status"] == "CLOCK_INVENTORY_ONLY_NOT_CERTIFIED"
    assert result["comparison_eligible_certified"] == 0


def test_standalone_cli_avoids_engine_imports_and_preserves_db(tmp_path):
    db = tmp_path / "decisions.db"
    _db(db, [("MES", T0.replace(tzinfo=None).isoformat(), _pipeline())])
    before = db.read_bytes()
    script = Path(__file__).resolve().parents[1] / "agents" / "agent_evidence_inventory.py"
    run = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(script), "--db", str(db)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert run.stderr == ""
    result = json.loads(run.stdout)
    assert result["first_blocker_counts"] == {"decision.timestamp must have timezone": 1}
    assert db.read_bytes() == before


def test_missing_table_fails_closed(tmp_path):
    db = tmp_path / "empty.db"
    with sqlite3.connect(db):
        pass
    with pytest.raises(ValueError, match="decisions table"):
        inventory(db)
