"""Small DuckDB-compatible shim for environments without the duckdb wheel.

The project is designed for DuckDB; this local shim implements the tiny DB-API subset
used by Phase 1 tests when dependency installation is unavailable.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class DuckDBPyConnection:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self._cursor: sqlite3.Cursor | None = None

    def execute(self, sql: str, params: list[Any] | None = None) -> DuckDBPyConnection:
        sql = (
            sql.replace("JSON", "TEXT")
            .replace("INSERT OR IGNORE", "INSERT OR IGNORE")
            .replace("INSERT OR REPLACE", "INSERT OR REPLACE")
        )
        self._cursor = self._conn.execute(sql, [] if params is None else params)
        self._conn.commit()
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        return None if row is None else tuple(row)

    def __enter__(self) -> DuckDBPyConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._conn.close()


def connect(path: str) -> DuckDBPyConnection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return DuckDBPyConnection(path)
