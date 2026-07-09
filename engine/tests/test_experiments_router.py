"""Endpoint tests for /experiments/* — MES session forward-recorder summary/rows.

Uses a throwaway SQLite file (via the `DB_PATH` env override that
`experiments_router._db_path()` honors) to exercise:
  * the populated-table success/aggregation path,
  * the not-yet-migrated empty-state path (table missing => `no such table`
    OperationalError => empty-state shape per the router's explicit
    fallback -- never a 500), and
  * a genuine DB failure (corrupt file) surfacing as a real 500.

No migration is added here -- the empty-state tests intentionally exercise
the router against a DB file that has never had the table created, matching
today's production reality.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import experiments_router as mod


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


def _create_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE mes_session_hypothesis (
            date TEXT,
            symbol TEXT,
            recorded_at TEXT,
            corey_bias TEXT,
            corey_conviction TEXT,
            corey_session_type TEXT,
            corey_ib_bias TEXT,
            corey_data_quality TEXT,
            entry_hypothesis_side TEXT,
            entry_hypothesis_reason TEXT,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL,
            outcome_delta REAL,
            outcome_recorded_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_row(db_path: str, **over) -> None:
    base = dict(
        date="2026-07-01",
        symbol="MES",
        recorded_at="2026-07-01T09:30:00",
        corey_bias="bullish",
        corey_conviction="high",
        corey_session_type="trend",
        corey_ib_bias="bullish",
        corey_data_quality="fresh",
        entry_hypothesis_side="long",
        entry_hypothesis_reason="IB breakout",
        open_price=5000.0,
        high_price=5020.0,
        low_price=4995.0,
        close_price=5015.0,
        outcome_delta=15.0,
        outcome_recorded_at="2026-07-01T16:00:00",
    )
    base.update(over)
    conn = sqlite3.connect(db_path)
    cols = ", ".join(base.keys())
    placeholders = ", ".join("?" for _ in base)
    conn.execute(
        f"INSERT INTO mes_session_hypothesis ({cols}) VALUES ({placeholders})",
        tuple(base.values()),
    )
    conn.commit()
    conn.close()


# ── empty-state: table not yet migrated in ──────────────────────────────────


def test_summary_returns_empty_state_when_table_missing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "no_table.db")
    monkeypatch.setenv("DB_PATH", db_path)
    client = _client()
    r = client.get("/experiments/mes-forward/summary")
    assert r.status_code == 200
    assert r.json() == {
        "n_rows": 0,
        "n_with_outcome": 0,
        "n_pending_outcome": 0,
        "first_date": None,
        "last_date": None,
        "by_side": {},
        "overall_non_skip": {"n": 0, "wins": 0, "hit_rate": 0.0, "avg_delta": 0.0},
    }


def test_rows_returns_empty_state_when_table_missing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "no_table2.db")
    monkeypatch.setenv("DB_PATH", db_path)
    client = _client()
    r = client.get("/experiments/mes-forward/rows")
    assert r.status_code == 200
    assert r.json() == {"rows": [], "count": 0}


# ── success path: populated table ───────────────────────────────────────────


def test_summary_aggregates_by_side(tmp_path, monkeypatch):
    db_path = str(tmp_path / "pop.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _create_table(db_path)
    _insert_row(db_path, date="2026-07-01", entry_hypothesis_side="long", outcome_delta=10.0)
    _insert_row(db_path, date="2026-07-02", entry_hypothesis_side="long", outcome_delta=-5.0)
    _insert_row(db_path, date="2026-07-03", entry_hypothesis_side="short", outcome_delta=8.0)
    _insert_row(db_path, date="2026-07-04", entry_hypothesis_side="skip", outcome_delta=0.0)
    # one still-pending row (no outcome recorded yet) -- must count toward
    # n_pending_outcome and NOT toward any by_side bucket.
    _insert_row(
        db_path,
        date="2026-07-05",
        entry_hypothesis_side="long",
        outcome_delta=None,
        outcome_recorded_at=None,
    )

    client = _client()
    r = client.get("/experiments/mes-forward/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["n_rows"] == 5
    assert body["n_with_outcome"] == 4
    assert body["n_pending_outcome"] == 1
    assert body["first_date"] == "2026-07-01"
    assert body["last_date"] == "2026-07-05"

    assert body["by_side"]["long"]["n"] == 2
    assert body["by_side"]["long"]["wins"] == 1
    assert body["by_side"]["long"]["losses"] == 1
    assert body["by_side"]["long"]["hit_rate"] == pytest.approx(0.5)
    assert body["by_side"]["short"]["n"] == 1
    assert body["by_side"]["short"]["wins"] == 1
    assert body["by_side"]["short"]["hit_rate"] == pytest.approx(1.0)

    # overall_non_skip excludes the "skip" side entirely.
    assert body["overall_non_skip"]["n"] == 3
    assert body["overall_non_skip"]["wins"] == 2
    assert body["overall_non_skip"]["hit_rate"] == pytest.approx(2 / 3)


def test_rows_returns_newest_first_and_respects_limit(tmp_path, monkeypatch):
    db_path = str(tmp_path / "rows.db")
    monkeypatch.setenv("DB_PATH", db_path)
    _create_table(db_path)
    for i in range(1, 6):
        _insert_row(db_path, date=f"2026-07-0{i}")

    client = _client()
    r = client.get("/experiments/mes-forward/rows", params={"limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert [row["date"] for row in body["rows"]] == ["2026-07-05", "2026-07-04"]


def test_rows_limit_query_validation_rejects_out_of_range(tmp_path, monkeypatch):
    db_path = str(tmp_path / "rows2.db")
    monkeypatch.setenv("DB_PATH", db_path)
    client = _client()
    assert client.get("/experiments/mes-forward/rows", params={"limit": 0}).status_code == 422
    assert client.get("/experiments/mes-forward/rows", params={"limit": 501}).status_code == 422


# ── real DB failure: corrupt file, not "no such table" ──────────────────────


def test_summary_returns_500_on_corrupt_db(tmp_path, monkeypatch):
    db_file = tmp_path / "corrupt.db"
    db_file.write_bytes(b"this is not a valid sqlite database file")
    monkeypatch.setenv("DB_PATH", str(db_file))
    client = _client()
    r = client.get("/experiments/mes-forward/summary")
    assert r.status_code == 500


def test_rows_returns_500_on_corrupt_db(tmp_path, monkeypatch):
    db_file = tmp_path / "corrupt2.db"
    db_file.write_bytes(b"this is not a valid sqlite database file")
    monkeypatch.setenv("DB_PATH", str(db_file))
    client = _client()
    r = client.get("/experiments/mes-forward/rows")
    assert r.status_code == 500
