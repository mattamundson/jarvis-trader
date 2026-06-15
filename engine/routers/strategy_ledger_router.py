"""
JARVIS TRADER — Strategy Ledger Router
======================================
Surfaces the gate-v2 backtest verdict ledger to the dashboard.

The gate-v2 sweep persists one JSON verdict per strategy/symbol/family under
``engine/data/gate_v2_verdicts/`` (top level only — ``archive/`` holds retired
verdicts). Those files are the source of truth for "has this strategy been
validated and is its edge real." Until now they lived only on disk; this router
reads them (no recompute) so the dashboard can render the PASS/FAIL ledger and
so the per-trade review surface can join a trade's strategy to its verdict.

Provides:
  GET /strategy/ledger              - All gate-v2 verdicts as a flat ledger
  GET /strategy/ledger/{symbol}/{family} - One verdict (used by full-review)

Read-only. No DB, no recompute — pure verdict-file reads.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.routers.strategy_ledger")

router = APIRouter(prefix="/strategy", tags=["strategy"])


def _verdicts_dir() -> Path:
    """Canonical gate_v2_verdicts directory, relative to the engine package.

    Router lives in engine/routers/, so parent.parent is the engine root.
    Mirrors analytics.gate_v2_calibrator and discord.digest_generator.
    """
    return Path(__file__).resolve().parent.parent / "data" / "gate_v2_verdicts"


# ── Models ─────────────────────────────────────────────────────────────────────


class LedgerEntry(BaseModel):
    """One gate-v2 verdict, flattened for the dashboard table."""

    symbol: Optional[str] = None
    family: Optional[str] = None
    rank: Optional[int] = None
    verdict: Optional[str] = None  # PASS | FAIL
    passed_via: Optional[str] = None  # core | alt | None
    core_verdict: Optional[str] = None
    alt_verdict: Optional[str] = None
    created_at: Optional[str] = None
    # metrics (gate_v2_metrics)
    pf_ci_lower: Optional[float] = None
    p_edge: Optional[float] = None
    mc_95th_dd_pct: Optional[float] = None
    dsr: Optional[float] = None
    wfo_consistency: Optional[str] = None
    fixed_params_min_pf: Optional[float] = None
    cost_survives_through: Optional[str] = None
    oos_trades: Optional[int] = None
    # provenance
    source_file: Optional[str] = None


class LedgerResponse(BaseModel):
    entries: List[LedgerEntry]
    total: int
    n_pass: int
    n_fail: int
    generated_at: str


# ── Parsing ────────────────────────────────────────────────────────────────────


def _parse_verdict(path: Path) -> Optional[Dict[str, Any]]:
    """Parse one verdict JSON into a flat ledger row. Returns None if malformed
    (never raise — a bad file must not take down the whole ledger)."""
    try:
        body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return None

    metrics = body.get("gate_v2_metrics", {}) or {}
    windows = body.get("windows", []) or []
    # oos_trades is not stored at metrics level — sum it from the WFO windows.
    oos_trades = metrics.get("n_oos_trades")
    if oos_trades is None:
        try:
            oos_trades = sum(int(w.get("oos_trades", 0) or 0) for w in windows)
        except (TypeError, ValueError):
            oos_trades = None

    return {
        "symbol": body.get("symbol"),
        "family": body.get("family"),
        "rank": body.get("rank"),
        "verdict": body.get("verdict"),
        "passed_via": body.get("passed_via"),
        "core_verdict": body.get("core_verdict"),
        "alt_verdict": body.get("alt_verdict"),
        "created_at": body.get("created_at"),
        "pf_ci_lower": metrics.get("pf_ci_lower"),
        "p_edge": metrics.get("p_edge"),
        "mc_95th_dd_pct": metrics.get("mc_95th_dd_pct"),
        "dsr": metrics.get("dsr"),
        "wfo_consistency": metrics.get("wfo_consistency"),
        "fixed_params_min_pf": metrics.get("fixed_params_min_pf"),
        "cost_survives_through": metrics.get("cost_survives_through"),
        "oos_trades": oos_trades,
        "source_file": path.name,
    }


def load_ledger(verdict_dir: "Path | None" = None) -> List[Dict[str, Any]]:
    """Read all top-level verdict JSONs into flat ledger rows.

    Exposed as a module function so the trades full-review endpoint can reuse it
    to look up a strategy's verdict without going back through HTTP.
    """
    vd = verdict_dir or _verdicts_dir()
    rows: List[Dict[str, Any]] = []
    if not vd.exists():
        return rows
    for path in sorted(vd.glob("*.json")):
        row = _parse_verdict(path)
        if row is not None:
            rows.append(row)
    return rows


def find_verdict(symbol: str, family: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Best-effort lookup of a verdict for a (symbol, family). When family is
    unknown or absent, returns the highest-rank (rank==1 preferred) PASS for the
    symbol if one exists, else the most recently created verdict for the symbol.
    Used by the per-trade full-review join where a trade only knows its symbol
    and (sometimes) its strategy family.
    """
    rows = [r for r in load_ledger() if r.get("symbol") == symbol]
    if not rows:
        return None
    if family:
        fam_rows = [r for r in rows if (r.get("family") or "") == family]
        if fam_rows:
            rows = fam_rows

    def _rank_key(r: Dict[str, Any]) -> Any:
        rank = r.get("rank")
        rank = rank if isinstance(rank, (int, float)) else 9999
        is_pass = 0 if r.get("verdict") == "PASS" else 1
        return (is_pass, rank, str(r.get("created_at") or ""))

    return sorted(rows, key=_rank_key)[0]


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/ledger",
    response_model=LedgerResponse,
    summary="Gate-v2 backtest verdict ledger (all strategies/symbols)",
)
def get_strategy_ledger(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. MES"),
    verdict: Optional[str] = Query(None, description="Filter: PASS | FAIL"),
) -> LedgerResponse:
    rows = load_ledger()
    if symbol:
        rows = [r for r in rows if r.get("symbol") == symbol]
    if verdict:
        rows = [r for r in rows if (r.get("verdict") or "").upper() == verdict.upper()]

    entries = [LedgerEntry(**r) for r in rows]
    n_pass = sum(1 for r in rows if r.get("verdict") == "PASS")
    return LedgerResponse(
        entries=entries,
        total=len(entries),
        n_pass=n_pass,
        n_fail=len(entries) - n_pass,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/ledger/{symbol}/{family}",
    response_model=LedgerEntry,
    summary="Single gate-v2 verdict for a symbol/family",
)
def get_strategy_verdict(symbol: str, family: str) -> LedgerEntry:
    row = find_verdict(symbol, family)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No verdict for {symbol}/{family}")
    return LedgerEntry(**row)
