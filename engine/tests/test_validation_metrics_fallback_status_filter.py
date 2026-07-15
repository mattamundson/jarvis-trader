"""
Regression test for D1-02: ValidationMetrics' fallback query (used when the
primary status-filtered query raises) must not leak non-terminal-status rows
(pending/cancelled_duplicate/cancelled_contaminated) into the live-trading
go/no-go readiness gate.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.validation_metrics import ValidationMetrics  # noqa: E402


def _make_db(tmp_path, rows, name="fallback_test.db"):
    db_path = tmp_path / name
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE paper_trades (
            trade_id TEXT,
            status TEXT,
            entry_time TEXT,
            exit_time TEXT,
            pnl REAL,
            symbol TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO paper_trades (trade_id, status, entry_time, exit_time, pnl, symbol) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


CLOSED_ROWS = [
    ("t1", "closed", "2026-07-01T00:00:00", "2026-07-01T01:00:00", 100.0, "MES"),
    ("t2", "filled", "2026-07-02T00:00:00", "2026-07-02T01:00:00", -50.0, "MES"),
]
CONTAMINATED_ROWS = [
    ("t3", "cancelled_duplicate", "2026-07-03T00:00:00", None, 9999.0, "MES"),
    ("t4", "cancelled_contaminated", "2026-07-04T00:00:00", None, 9999.0, "MES"),
    ("t5", "pending", "2026-07-05T00:00:00", None, 9999.0, "MES"),
]


class _FlakyConnProxy:
    """Wraps a real sqlite3.Connection and raises once on the primary
    status-filtered query, forcing ValidationMetrics down its fallback path
    -- sqlite3.Connection is a C type and can't be monkeypatched directly."""

    def __init__(self, real_conn):
        object.__setattr__(self, "_real", real_conn)
        object.__setattr__(self, "_raised", False)

    def execute(self, sql, *args, **kwargs):
        if "WHERE LOWER(status)" in sql and not self._raised:
            object.__setattr__(self, "_raised", True)
            raise sqlite3.OperationalError("simulated primary-query failure")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


def test_fallback_excludes_non_terminal_status_rows(tmp_path, monkeypatch):
    """When the primary query raises, the fallback must still exclude
    non-terminal-status rows -- not silently count every row."""
    db_path = _make_db(tmp_path, CLOSED_ROWS + CONTAMINATED_ROWS)
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **kw: _FlakyConnProxy(real_connect(*a, **kw))
    )

    result = ValidationMetrics(db_path=db_path).compute()

    assert result.get("metrics", {}).get("total_trades") == len(CLOSED_ROWS), (
        f"fallback leaked non-terminal-status rows into the readiness gate: {result}"
    )


def test_fallback_keeps_all_rows_when_status_column_absent(tmp_path):
    """If the table genuinely has no status column, the fallback can't filter
    on it -- confirm it degrades to counting everything (documented, not a
    silent surprise) rather than raising."""
    db_path = tmp_path / "no_status.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE paper_trades (trade_id TEXT, entry_time TEXT, pnl REAL, symbol TEXT)"
    )
    conn.executemany(
        "INSERT INTO paper_trades (trade_id, entry_time, pnl, symbol) VALUES (?, ?, ?, ?)",
        [("t1", "2026-07-01T00:00:00", 100.0, "MES"), ("t2", "2026-07-02T00:00:00", -50.0, "MES")],
    )
    conn.commit()
    conn.close()

    result = ValidationMetrics(db_path=db_path).compute()

    assert result.get("metrics", {}).get("total_trades") == 2
