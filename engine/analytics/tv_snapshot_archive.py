"""
TV Snapshot Archiver
====================
Persists TVIndicatorSnapshot records to SQLite so the structural data
seen at decision time can be replayed during backtests and post-mortems.

Design:
  - One table: tv_snapshots (wide schema for the common fields + a
    `raw_snapshot` JSON blob for forward-compat)
  - Unique index on (symbol, captured_at) — idempotent writes
  - Pure Python sqlite3 (no SQLAlchemy dependency) to match the rest of
    the analytics modules

Usage:
    from analytics.tv_snapshot_archive import TVSnapshotArchive
    from data.tv_indicator_bridge import get_tv_bridge

    archive = TVSnapshotArchive()
    snap = get_tv_bridge().get_snapshot("MES")
    archive.archive_snapshot(snap)

    # Retrieve recent:
    rows = archive.get_recent("MES", hours=24)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Column projection — kept in sync with TVIndicatorSnapshot field names where
# possible. New snapshot fields land in raw_snapshot without requiring
# schema migration.
SCHEMA_COLUMNS: List[str] = [
    "symbol", "captured_at",
    "stc_value", "stc_state",
    "composite_score", "regime",
    "atr_value",
    "ib_high", "ib_low", "ib_range",
    "phase_oscillator", "is_compressed",
    "corey_score", "corey_bias",
    "vwap",
    "pp", "r1", "r2", "r3", "s1", "s2", "s3",
    "kc_1h_upper", "kc_1h_mid", "kc_1h_lower",
    "data_quality",
    "raw_snapshot",
]


def _default_db_path() -> str:
    """Resolve the engine SQLite path without importing config at module load."""
    try:
        from config import settings  # type: ignore
        return settings.SQLITE_DB_PATH
    except Exception:
        # Fallback relative to engine/
        engine_dir = Path(__file__).resolve().parent.parent
        return str(engine_dir / "data" / "jarvis_trader.db")


class TVSnapshotArchive:
    """Archive TVIndicatorSnapshot rows to SQLite."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _default_db_path()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    # ── Connection management ────────────────────────────────────────────
    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ── Schema ───────────────────────────────────────────────────────────
    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tv_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    captured_at TIMESTAMP NOT NULL,
                    stc_value REAL,
                    stc_state TEXT,
                    composite_score REAL,
                    regime TEXT,
                    atr_value REAL,
                    ib_high REAL,
                    ib_low REAL,
                    ib_range REAL,
                    phase_oscillator REAL,
                    is_compressed INTEGER,
                    corey_score REAL,
                    corey_bias TEXT,
                    vwap REAL,
                    pp REAL, r1 REAL, r2 REAL, r3 REAL, s1 REAL, s2 REAL, s3 REAL,
                    kc_1h_upper REAL, kc_1h_mid REAL, kc_1h_lower REAL,
                    data_quality TEXT,
                    raw_snapshot TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_tv_snapshots_sym_time
                ON tv_snapshots(symbol, captured_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_tv_snapshots_captured_at
                ON tv_snapshots(captured_at)
                """
            )
            conn.commit()
        except Exception as exc:
            logger.error("tv_snapshot_archive schema create failed: %s", exc)
            raise

    # ── Writes ───────────────────────────────────────────────────────────
    def archive_snapshot(self, snapshot: Any, symbol_override: Optional[str] = None) -> int:
        """
        Insert a snapshot row. Returns the new row id, or the existing id if
        (symbol, captured_at) already exists (idempotent via INSERT OR IGNORE).

        Accepts either a TVIndicatorSnapshot dataclass or a plain dict.
        """
        if is_dataclass(snapshot):
            data = asdict(snapshot)
        elif isinstance(snapshot, dict):
            data = dict(snapshot)
        else:
            raise TypeError(f"Unsupported snapshot type: {type(snapshot).__name__}")

        symbol = symbol_override or data.get("symbol") or "UNKNOWN"
        captured_at = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
        if isinstance(captured_at, datetime):
            captured_at = captured_at.isoformat()

        row = {
            "symbol": str(symbol).upper(),
            "captured_at": str(captured_at),
            "stc_value": data.get("stc_value"),
            "stc_state": data.get("stc_state"),
            "composite_score": data.get("composite_score"),
            "regime": data.get("regime"),
            "atr_value": data.get("atr_value"),
            "ib_high": data.get("ib_high"),
            "ib_low": data.get("ib_low"),
            "ib_range": data.get("ib_range"),
            "phase_oscillator": data.get("phase_oscillator"),
            "is_compressed": 1 if data.get("is_compressed") else 0,
            "corey_score": data.get("corey_score"),
            "corey_bias": data.get("corey_bias"),
            "vwap": data.get("vwap"),
            "pp": data.get("pp"),
            "r1": data.get("r1"),
            "r2": data.get("r2"),
            "r3": data.get("r3"),
            "s1": data.get("s1"),
            "s2": data.get("s2"),
            "s3": data.get("s3"),
            "kc_1h_upper": data.get("kc_1h_upper"),
            "kc_1h_mid": data.get("kc_1h_mid"),
            "kc_1h_lower": data.get("kc_1h_lower"),
            "data_quality": data.get("data_quality", "unavailable"),
            "raw_snapshot": json.dumps({k: _json_safe(v) for k, v in data.items()}),
        }

        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO tv_snapshots (
                    symbol, captured_at, stc_value, stc_state,
                    composite_score, regime, atr_value,
                    ib_high, ib_low, ib_range,
                    phase_oscillator, is_compressed,
                    corey_score, corey_bias,
                    vwap,
                    pp, r1, r2, r3, s1, s2, s3,
                    kc_1h_upper, kc_1h_mid, kc_1h_lower,
                    data_quality, raw_snapshot
                ) VALUES (
                    :symbol, :captured_at, :stc_value, :stc_state,
                    :composite_score, :regime, :atr_value,
                    :ib_high, :ib_low, :ib_range,
                    :phase_oscillator, :is_compressed,
                    :corey_score, :corey_bias,
                    :vwap,
                    :pp, :r1, :r2, :r3, :s1, :s2, :s3,
                    :kc_1h_upper, :kc_1h_mid, :kc_1h_lower,
                    :data_quality, :raw_snapshot
                )
                """,
                row,
            )
            conn.commit()

            if cur.lastrowid and cur.rowcount > 0:
                return int(cur.lastrowid)

            # Already existed — look up the existing row
            existing = conn.execute(
                "SELECT id FROM tv_snapshots WHERE symbol = ? AND captured_at = ?",
                (row["symbol"], row["captured_at"]),
            ).fetchone()
            return int(existing["id"]) if existing else 0
        except Exception as exc:
            logger.error("archive_snapshot failed for %s: %s", symbol, exc)
            return 0

    # ── Reads ────────────────────────────────────────────────────────────
    def get_recent(self, symbol: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Return snapshots for `symbol` from the last N hours, newest first."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM tv_snapshots
            WHERE symbol = ? AND captured_at >= ?
            ORDER BY captured_at DESC
            """,
            (symbol.upper(), cutoff),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_at(self, symbol: str, timestamp: datetime) -> Optional[Dict[str, Any]]:
        """Return the snapshot closest to `timestamp` for `symbol` (or None)."""
        ts_iso = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT * FROM tv_snapshots
            WHERE symbol = ?
            ORDER BY ABS(strftime('%s', captured_at) - strftime('%s', ?)) ASC
            LIMIT 1
            """,
            (symbol.upper(), ts_iso),
        ).fetchone()
        return dict(row) if row else None

    def count(self, symbol: Optional[str] = None) -> int:
        conn = self._get_conn()
        if symbol:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM tv_snapshots WHERE symbol = ?",
                (symbol.upper(),),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM tv_snapshots").fetchone()
        return int(row["c"]) if row else 0


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


# ──────────────────────────────────────────────────────────────────────────
# Roundtrip smoke test
# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    archive = TVSnapshotArchive(":memory:")

    fake = {
        "symbol": "MES",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stc_value": 18.4,
        "stc_state": "OVERSOLD",
        "composite_score": 0.42,
        "regime": "TRENDING_BULL",
        "atr_value": 24.8,
        "ib_high": 5818.0,
        "ib_low": 5808.25,
        "ib_range": 9.75,
        "phase_oscillator": 23.5,
        "is_compressed": False,
        "corey_score": 0.31,
        "corey_bias": "BULL",
        "vwap": 5815.25,
        "data_quality": "live",
    }

    rid = archive.archive_snapshot(fake)
    print(f"Inserted row id={rid}")

    rows = archive.get_recent("MES", hours=1)
    print(f"get_recent returned {len(rows)} rows")
    if rows:
        first = rows[0]
        print(f"  symbol={first['symbol']} stc={first['stc_value']} regime={first['regime']}")

    # Idempotency
    rid2 = archive.archive_snapshot(fake)
    assert rid == rid2, f"idempotent insert returned different ids: {rid} vs {rid2}"
    print(f"Idempotent re-insert returned same id: {rid2}")

    print(f"Total rows: {archive.count()}")
    print("OK — tv_snapshot_archive roundtrip passed")
