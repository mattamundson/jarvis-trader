"""
JARVIS TRADER — Execution Cockpit
GET /execution/fidelity-status?symbols=MES,MGC

Single-pane, read-only aggregator for the dashboard's live execution cockpit.
Combines, in one call so the widget polls a single source:
  - measuring_real_fills (ALLOW_PAPER_SIMULATED_ORDERS) — live vs simulated
  - per-symbol execution-fidelity (overall + checks passing) and slippage
    (n / mean / p95 |ticks|), reusing the /validate endpoints
  - pending_approvals {count, oldest_age_min} — a stuck queue stalls fills
  - recent JARVIS-tagged real fills and open paper trades

Advisory only — gates nothing. All reads are read-only and resilient.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execution", tags=["Execution Status"])

_DB_PATH = Path(__file__).parent.parent / "data" / "jarvis_trader.db"
_DEFAULT_SYMBOLS = ["MES", "MGC"]


def _ro_conn() -> Optional[sqlite3.Connection]:
    if _DB_PATH.exists():
        try:
            conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as exc:
            logger.warning("execution-status: DB open failed: %s", exc)
    return None


class SymbolFidelity(BaseModel):
    symbol: str
    fidelity_overall: str
    checks_passing: int
    checks_total: int
    slippage_n: int
    mean_abs_slippage_ticks: Optional[float]
    p95_abs_slippage_ticks: Optional[float]


class ExecutionCockpit(BaseModel):
    generated_at: str
    measuring_real_fills: bool
    pending_approvals: dict
    recent_fills: list[dict]
    open_trades: list[dict]
    symbols: list[SymbolFidelity]
    note: str


@router.get("/fidelity-status", response_model=ExecutionCockpit)
async def get_fidelity_status(
    symbols: str = Query(default="MES,MGC", description="Comma-separated symbols"),
) -> ExecutionCockpit:
    """Aggregated live-execution snapshot for the dashboard cockpit."""
    try:
        from config import settings

        measuring = bool(getattr(settings, "ALLOW_PAPER_SIMULATED_ORDERS", False))
    except Exception:
        measuring = False

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or _DEFAULT_SYMBOLS

    # Reuse the /validate fidelity + slippage endpoints (Task 1).
    sym_reports: list[SymbolFidelity] = []
    try:
        from routers.proactive_validation_router import (
            get_execution_fidelity,
            get_slippage_analytics,
        )

        for sym in syms:
            try:
                fid = await get_execution_fidelity(sym)
                slip = await get_slippage_analytics(sym)
                passing = sum(1 for c in fid.checks if c.status == "pass")
                sym_reports.append(
                    SymbolFidelity(
                        symbol=sym,
                        fidelity_overall=fid.overall,
                        checks_passing=passing,
                        checks_total=len(fid.checks),
                        slippage_n=slip.n,
                        mean_abs_slippage_ticks=slip.mean_abs_slippage_ticks,
                        p95_abs_slippage_ticks=slip.p95_abs_slippage_ticks,
                    )
                )
            except Exception as exc:
                logger.warning("execution-status: per-symbol %s failed: %s", sym, exc)
    except Exception as exc:
        logger.warning("execution-status: validation endpoints unavailable: %s", exc)

    pending: dict[str, Any] = {"count": 0, "oldest_age_min": None}
    recent_fills: list[dict] = []
    open_trades: list[dict] = []
    conn = _ro_conn()
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT COUNT(*), MIN(created_at) FROM pending_trade_approvals "
                "WHERE status = 'pending'"
            ).fetchone()
            if row:
                oldest = row[1]
                age_min = None
                if oldest:
                    try:
                        ots = datetime.fromisoformat(str(oldest).replace("Z", "+00:00"))
                        if ots.tzinfo is None:
                            ots = ots.replace(tzinfo=timezone.utc)
                        age_min = round(
                            (datetime.now(timezone.utc) - ots).total_seconds() / 60.0, 1
                        )
                    except Exception:
                        age_min = None
                pending = {"count": int(row[0] or 0), "oldest_age_min": age_min}

            recent_fills = [
                dict(r)
                for r in conn.execute(
                    "SELECT symbol, side, quantity, price, fill_time, order_ref "
                    "FROM ibkr_fills WHERE order_ref LIKE 'JARVIS-%' "
                    "ORDER BY fill_time DESC LIMIT 10"
                ).fetchall()
            ]
            open_trades = [
                dict(r)
                for r in conn.execute(
                    "SELECT symbol, side, quantity, entry_price, entry_time, slippage_ticks "
                    "FROM paper_trades WHERE status = 'open' "
                    "ORDER BY entry_time DESC LIMIT 10"
                ).fetchall()
            ]
        except Exception as exc:
            logger.warning("execution-status: DB read failed: %s", exc)
        finally:
            conn.close()

    note = (
        "Measuring real IBKR paper fills."
        if measuring
        else "SIMULATED MODE (ALLOW_PAPER_SIMULATED_ORDERS=False) — fills are "
        "self-referential, not a true execution-fidelity signal yet."
    )

    return ExecutionCockpit(
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        measuring_real_fills=measuring,
        pending_approvals=pending,
        recent_fills=recent_fills,
        open_trades=open_trades,
        symbols=sym_reports,
        note=note,
    )
