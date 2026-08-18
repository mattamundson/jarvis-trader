"""
MR-0.3 — Reconcile the two historical paper-trade ledgers (JSONL vs SQLite).

Context: US-1703 (commit 10c4f1b, 2026-06-17) already made SQLite
(``paper_trades``) the sole source of truth going forward — ``PortfolioTracker``
skips the JSONL write+replay entirely whenever a ``db_manager`` is active (see
``portfolio/tracker.py:_append_record``/``_load_history``). The pre-cutover
JSONL file (``portfolio/trades.jsonl``) is deliberately left on disk, frozen,
as a historical audit artifact — see ``docs/runbooks/PAPER_LEDGER_BOUNDARIES.md``.

This script is the ongoing, read-only verification that the freeze is
actually holding:

  1. Every trade_id in the frozen JSONL file is either present in
     ``paper_trades`` (migrated) or predates the cutover with no expectation
     of migration (pre-US-1702 open-only rows that never closed) — reported,
     never auto-fixed.
  2. The JSONL file's mtime has NOT advanced past the cutover commit date —
     if it has, something wrote to it after retirement, which should be
     structurally impossible today and is worth investigating immediately.

Exit code 0 + "zero divergent rows" = clean (the proof line this script
exists to satisfy). Exit code 1 = drift found — this is a read-only report,
it never modifies either ledger.

Usage:
    cd engine
    .venv/Scripts/python scripts/reconcile_paper_sources.py
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPT_DIR.parent
_JSONL_PATH = _ENGINE_DIR / "portfolio" / "trades.jsonl"
_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"

# US-1703 cutover: commit 10c4f1b, 2026-06-17T00:40:30-05:00 (05:40:30 UTC).
# The JSONL file must never be written to after this instant again.
_CUTOVER_UTC = datetime(2026, 6, 17, 5, 40, 30, tzinfo=timezone.utc)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reconcile_paper_sources")


def _load_jsonl_trade_ids(path: Path) -> set[str]:
    if not path.exists():
        log.warning("JSONL file not found: %s (nothing to reconcile)", path)
        return set()

    trade_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("Line %d: JSON parse error — skipped (%s)", line_num, exc)
                continue
            trade_id = record.get("trade_id")
            if trade_id:
                trade_ids.add(trade_id)
    return trade_ids


def _load_sqlite_trade_ids(db_path: Path) -> set[str]:
    if not db_path.exists():
        log.error("SQLite database not found: %s", db_path)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT trade_id FROM paper_trades").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _check_jsonl_frozen(path: Path) -> tuple[bool, str]:
    """Returns (is_frozen, detail). is_frozen=False means the file was
    modified after the US-1703 cutover — a structural regression."""
    if not path.exists():
        return True, "JSONL file absent (trivially frozen)"
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if mtime > _CUTOVER_UTC:
        return False, f"JSONL mtime {mtime.isoformat()} is AFTER cutover {_CUTOVER_UTC.isoformat()}"
    return True, f"JSONL mtime {mtime.isoformat()} predates cutover (frozen, as expected)"


def reconcile() -> dict:
    jsonl_ids = _load_jsonl_trade_ids(_JSONL_PATH)
    sqlite_ids = _load_sqlite_trade_ids(_DB_PATH)

    missing_from_sqlite = sorted(jsonl_ids - sqlite_ids)
    frozen, freeze_detail = _check_jsonl_frozen(_JSONL_PATH)

    result = {
        "ok": (len(missing_from_sqlite) == 0) and frozen,
        "jsonl_trade_id_count": len(jsonl_ids),
        "sqlite_trade_id_count": len(sqlite_ids),
        "divergent_count": len(missing_from_sqlite),
        "divergent_trade_ids": missing_from_sqlite,
        "jsonl_frozen": frozen,
        "jsonl_freeze_detail": freeze_detail,
        "canonical_source": "sqlite:paper_trades",
    }
    return result


def main() -> int:
    log.info("=== MR-0.3 paper-ledger reconciliation ===")
    log.info("JSONL  (frozen, historical) : %s", _JSONL_PATH)
    log.info("SQLite (canonical, live)    : %s", _DB_PATH)

    result = reconcile()

    log.info("JSONL unique trade_ids  : %d", result["jsonl_trade_id_count"])
    log.info("SQLite unique trade_ids : %d", result["sqlite_trade_id_count"])
    log.info("Freeze check            : %s", result["jsonl_freeze_detail"])

    if result["ok"]:
        log.info("CLEAN — zero divergent rows. SQLite (paper_trades) is confirmed canonical.")
    else:
        log.error(
            "DRIFT — %d JSONL trade_id(s) not present in SQLite: %s",
            result["divergent_count"],
            result["divergent_trade_ids"][:10],
        )
        if not result["jsonl_frozen"]:
            log.error("ALSO: %s", result["jsonl_freeze_detail"])

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
