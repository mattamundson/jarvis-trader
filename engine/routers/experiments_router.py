"""
FastAPI router for the `/experiments/*` surface — forward-recording
experiments (MES session hypothesis, and any future additions).

The MES forward-recorder table `mes_session_hypothesis` accumulates one
row per (date, symbol) pair. V1 exposes two read-only endpoints:

  GET /experiments/mes-forward/summary  — aggregate metrics (hit-rate by
                                           side, avg outcome_delta, row
                                           count, last-seen date)
  GET /experiments/mes-forward/rows     — N most recent rows for tables /
                                           charts, newest first

Both are intentionally unauth'd read-only (same API-key gating as rest
of the engine). Writes to the table come from the scheduler jobs in
`experiments/mes_session_{recorder,outcome}.py`, never from HTTP.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("jarvis_trader.experiments")

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _db_path() -> str:
    """Resolve the canonical jarvis_trader.db path.

    Matches `experiments/mes_session_recorder.DEFAULT_DB_PATH` so read +
    write halves always agree. DB_PATH env var takes precedence for tests.
    """
    env = os.environ.get("DB_PATH")
    if env:
        return env
    return str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


@router.get(
    "/mes-forward/summary",
    description=(
        "Aggregate metrics for the MES session forward-recorder — hit-rate "
        "and avg outcome_delta grouped by hypothesis side, plus totals."
    ),
)
async def get_mes_forward_summary() -> dict[str, Any]:
    """Aggregate summary of the mes_session_hypothesis table."""
    try:
        with _connect() as conn:
            totals = conn.execute(
                "SELECT COUNT(*) AS n_rows, "
                "       COUNT(outcome_recorded_at) AS n_with_outcome, "
                "       MIN(date) AS first_date, "
                "       MAX(date) AS last_date "
                "FROM mes_session_hypothesis"
            ).fetchone()

            by_side = conn.execute(
                "SELECT entry_hypothesis_side AS side, "
                "       COUNT(*) AS n, "
                "       SUM(CASE WHEN outcome_delta > 0 THEN 1 ELSE 0 END) AS wins, "
                "       SUM(CASE WHEN outcome_delta < 0 THEN 1 ELSE 0 END) AS losses, "
                "       AVG(outcome_delta) AS avg_delta "
                "FROM mes_session_hypothesis "
                "WHERE outcome_recorded_at IS NOT NULL "
                "GROUP BY entry_hypothesis_side"
            ).fetchall()

            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM mes_session_hypothesis "
                "WHERE outcome_recorded_at IS NULL"
            ).fetchone()

        # Normalise to a compact, dashboard-friendly shape. We emit zeros
        # rather than None where possible so frontend charts can skip the
        # null-check branch.
        sides: dict[str, dict[str, Any]] = {}
        for row in by_side:
            n = row["n"] or 0
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            sides[row["side"] or "unknown"] = {
                "n": n,
                "wins": wins,
                "losses": losses,
                "hit_rate": (wins / n) if n > 0 else 0.0,
                "avg_delta": float(row["avg_delta"]) if row["avg_delta"] is not None else 0.0,
            }

        # All-sides aggregate (only among non-skip rows — skip is always delta=0)
        non_skip_rows = [s for name, s in sides.items() if name in ("long", "short")]
        total_n = sum(s["n"] for s in non_skip_rows)
        total_wins = sum(s["wins"] for s in non_skip_rows)
        overall = {
            "n": total_n,
            "wins": total_wins,
            "hit_rate": (total_wins / total_n) if total_n > 0 else 0.0,
            "avg_delta": (
                sum(s["avg_delta"] * s["n"] for s in non_skip_rows) / total_n
                if total_n > 0
                else 0.0
            ),
        }

        return {
            "n_rows": totals["n_rows"] or 0,
            "n_with_outcome": totals["n_with_outcome"] or 0,
            "n_pending_outcome": pending["n"] or 0,
            "first_date": totals["first_date"],
            "last_date": totals["last_date"],
            "by_side": sides,
            "overall_non_skip": overall,
        }
    except sqlite3.OperationalError as exc:
        # Table not yet migrated in — return empty-state shape instead of 500
        if "no such table" in str(exc).lower():
            logger.warning("[EXPERIMENTS] mes_session_hypothesis table missing: %s", exc)
            return {
                "n_rows": 0,
                "n_with_outcome": 0,
                "n_pending_outcome": 0,
                "first_date": None,
                "last_date": None,
                "by_side": {},
                "overall_non_skip": {"n": 0, "wins": 0, "hit_rate": 0.0, "avg_delta": 0.0},
            }
        raise HTTPException(500, f"Summary query failed: {exc}") from exc
    except Exception as exc:
        logger.error("[EXPERIMENTS] summary failed: %s", exc)
        raise HTTPException(500, f"Summary query failed: {exc}") from exc


@router.get(
    "/mes-forward/rows",
    description=(
        "Return the N most recent mes_session_hypothesis rows, newest first. "
        "Intended for dashboard tables and mini-charts."
    ),
)
async def get_mes_forward_rows(
    limit: int = Query(60, ge=1, le=500, description="Max rows to return"),
) -> dict[str, Any]:
    """Return recent rows for dashboard consumption."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT date, symbol, recorded_at,
                       corey_bias, corey_conviction, corey_session_type,
                       corey_ib_bias, corey_data_quality,
                       entry_hypothesis_side, entry_hypothesis_reason,
                       open_price, high_price, low_price, close_price,
                       outcome_delta, outcome_recorded_at
                FROM mes_session_hypothesis
                ORDER BY date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {"rows": [dict(r) for r in rows], "count": len(rows)}
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {"rows": [], "count": 0}
        raise HTTPException(500, f"Rows query failed: {exc}") from exc
    except Exception as exc:
        logger.error("[EXPERIMENTS] rows query failed: %s", exc)
        raise HTTPException(500, f"Rows query failed: {exc}") from exc
