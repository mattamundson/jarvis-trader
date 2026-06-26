"""SQLite results store + global trial counter for the discovery factory.

Every candidate ever screened is logged here. The global trial counter is the
denominator that makes multiple-testing honest: the Deflated Sharpe ratio for
any survivor must be deflated by the TOTAL number of candidates the factory
screened (across all cards/instruments/timeframes), not just one sub-sweep.
Persisting every candidate also forecloses the "quietly tested a tiny subset"
failure mode -- the DB is the audit trail.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    config     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    card_name    TEXT NOT NULL,
    instrument   TEXT NOT NULL,
    timeframe    TEXT NOT NULL,
    params       TEXT NOT NULL,
    stage        TEXT NOT NULL,          -- enumerated | smoke | robustness | combo
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS results (
    result_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    stage        TEXT NOT NULL,
    metrics      TEXT NOT NULL,          -- json
    verdict      TEXT,                   -- PASS | FAIL | KILL | NULL
    kill_reason  TEXT,
    FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);
"""


class ResultsDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def new_run(self, created_at: str, config: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (created_at, config) VALUES (?, ?)",
            (created_at, json.dumps(config)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_candidate(
        self,
        run_id: int,
        card_name: str,
        instrument: str,
        timeframe: str,
        params: dict,
        stage: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO candidates (run_id, card_name, instrument, timeframe, params, stage)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, card_name, instrument, timeframe, json.dumps(params), stage),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_result(
        self,
        candidate_id: int,
        stage: str,
        metrics: dict,
        verdict: str | None = None,
        kill_reason: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO results (candidate_id, stage, metrics, verdict, kill_reason)"
            " VALUES (?, ?, ?, ?, ?)",
            (candidate_id, stage, json.dumps(metrics), verdict, kill_reason),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def global_trial_count(self) -> int:
        """Total candidates ever screened -- the DSR n_trials denominator."""
        row = self.conn.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()
        return int(row["n"])

    def survivors(self, run_id: int, stage: str, verdict: str = "PASS") -> list[dict]:
        """Candidates with a given verdict at a given stage."""
        rows = self.conn.execute(
            "SELECT c.*, r.metrics, r.verdict, r.kill_reason "
            "FROM candidates c JOIN results r ON r.candidate_id = c.candidate_id "
            "WHERE c.run_id = ? AND r.stage = ? AND r.verdict = ?",
            (run_id, stage, verdict),
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["params"] = json.loads(d["params"])
            d["metrics"] = json.loads(d["metrics"])
            out.append(d)
        return out

    def close(self) -> None:
        self.conn.close()
