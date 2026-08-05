"""SQLite persistence for DOM/order-flow snapshots.

Writes one row every 10 seconds (not every tick — raw L2 updates arrive
multiple times/sec, which is noise for the forward-grading use case, not a
scalping signal). Lives in its own DB file (``domflow.db``) so the feature is
cleanly separable/droppable if Phase 2 decides the signal isn't worth keeping.

Schema mirrors the Phase-1 spec exactly.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("domflow.storage")

# DB lives next to this module (engine/domflow/domflow.db), NOT jarvis_trader.db.
_DB_PATH = Path(os.environ.get("DOMFLOW_DB_PATH", Path(__file__).resolve().parent / "domflow.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS domflow_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    best_bid REAL, best_ask REAL, mid_price REAL, spread REAL,
    bid_volume_top5 INTEGER, ask_volume_top5 INTEGER,
    imbalance_ratio REAL,
    raw_book_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_domflow_symbol_ts ON domflow_snapshots(symbol, ts_utc);
"""


class DomflowStorage:
    """Thread-safe-enough SQLite writer/reader (single writer in practice)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── write ─────────────────────────────────────────────────────────────────

    def insert_snapshot(
        self,
        symbol: str,
        ts_utc: str,
        best_bid: Optional[float],
        best_ask: Optional[float],
        mid_price: Optional[float],
        spread: Optional[float],
        bid_volume_top5: float,
        ask_volume_top5: float,
        imbalance_ratio: float,
        raw_book_json: str,
    ) -> None:
        if self._conn is None:
            raise RuntimeError("DomflowStorage.connect() must be called first")
        self._conn.execute(
            """
            INSERT INTO domflow_snapshots (
                symbol, ts_utc, best_bid, best_ask, mid_price, spread,
                bid_volume_top5, ask_volume_top5, imbalance_ratio, raw_book_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                ts_utc,
                best_bid,
                best_ask,
                mid_price,
                spread,
                int(round(bid_volume_top5)),
                int(round(ask_volume_top5)),
                round(imbalance_ratio, 6),
                raw_book_json,
            ),
        )
        self._conn.commit()

    # ── read ──────────────────────────────────────────────────────────────────

    def latest(self, symbol: str = "MES") -> Optional[dict[str, Any]]:
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT symbol, ts_utc, best_bid, best_ask, mid_price, spread, "
            "bid_volume_top5, ask_volume_top5, imbalance_ratio, raw_book_json "
            "FROM domflow_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def history(self, symbol: str = "MES", minutes: int = 60) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        rows = self._conn.execute(
            "SELECT symbol, ts_utc, best_bid, best_ask, mid_price, spread, "
            "bid_volume_top5, ask_volume_top5, imbalance_ratio, raw_book_json "
            "FROM domflow_snapshots WHERE symbol=? AND ts_utc>=? ORDER BY id",
            (symbol, since),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        if row is None:
            return {}
        return {
            "symbol": row[0],
            "ts_utc": row[1],
            "best_bid": row[2],
            "best_ask": row[3],
            "mid_price": row[4],
            "spread": row[5],
            "bid_volume_top5": row[6],
            "ask_volume_top5": row[7],
            "imbalance_ratio": row[8],
            "raw_book_json": row[9],
        }

    # ── housekeeping ──────────────────────────────────────────────────────────

    def prune(self, keep_days: int = 30) -> int:
        """Delete rows older than ``keep_days``; return count removed.

        Called periodically so a 10s-cadence feed doesn't grow unbounded.
        """
        if self._conn is None:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        cur = self._conn.execute("DELETE FROM domflow_snapshots WHERE ts_utc < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount
