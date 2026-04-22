#!/usr/bin/env python3
"""
P0-2 — Reconcile optional paper_runner JSON vs engine SQLite paper ledger.

Canonical SoT: engine SQLite (see docs/runbooks/PAPER_SOURCE_OF_TRUTH.md).

Usage (repo root):
  python scripts/reconcile_paper_sources.py

Env:
  JARVIS_SQLITE_DB — path to jarvis_trader.db (default: engine/data/jarvis_trader.db under repo root)
  PAPER_JSON_DIR   — directory with paper_trades_live.json / paper_positions.json (default: engine/backtest/results)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json_list(path: Path) -> list:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        print(f"warn: could not read {path}: {e}", file=sys.stderr)
        return []


def _sqlite_paper_stats(db_path: Path) -> dict:
    if not db_path.is_file():
        return {"ok": False, "error": f"database not found: {db_path}"}
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM paper_trades")
        (total,) = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE status = 'open'"
        )
        (open_n,) = cur.fetchone()
        cur.execute(
            "SELECT MAX(id) FROM paper_trades"
        )
        (max_id,) = cur.fetchone()
        con.close()
        return {
            "ok": True,
            "paper_trades_total": int(total),
            "paper_trades_open": int(open_n),
            "paper_trades_max_id": max_id,
        }
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}


def main() -> int:
    root = _repo_root()
    db = Path(
        os.environ.get("JARVIS_SQLITE_DB", str(root / "engine" / "data" / "jarvis_trader.db"))
    )
    jdir = Path(os.environ.get("PAPER_JSON_DIR", str(root / "engine" / "backtest" / "results")))

    live = jdir / "paper_trades_live.json"
    pos = jdir / "paper_positions.json"

    json_trades = _load_json_list(live)
    json_positions = _load_json_list(pos)

    stats = _sqlite_paper_stats(db)

    out = {
        "sqlite_path": str(db),
        "json_dir": str(jdir),
        "engine": stats,
        "paper_runner": {
            "paper_trades_live.json_count": len(json_trades),
            "paper_positions.json_count": len(json_positions),
        },
    }

    if stats.get("ok"):
        jn = len(json_trades)
        sn = stats["paper_trades_total"]
        out["reconciliation"] = {
            "json_live_trades_vs_sqlite_total": {"json": jn, "sqlite": sn},
            "note": "If both are used with sync, counts should track after each POST to /portfolio/paper/trade. "
            "Large drift without explanation → investigate RISK-006.",
        }

    print(json.dumps(out, indent=2))
    return 0 if stats.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
