"""
JARVIS TRADER — Forward-Test Status Router
==========================================
Surfaces the LATEST forward-test (paper-validation) status for a symbol as a
single read-only endpoint, so the north-star scorecard / dashboard can read it
instead of a human running a manual snapshot (closes the C1 "forward-test"
scorecard point's automation gap).

"Forward test" = the live paper-trading phase that confirms a backtest gate-v2
verdict holds in real market conditions. This router RECOMPUTES NOTHING — it
reads the output of two EXISTING writers:
  - portfolio/trades.jsonl  — written by the live PortfolioTracker / trade logger
  - data/gate_v2_verdicts/  — written by the gate-v2 sweep
via the canonical helpers ``_query_paper_trade_stats()`` (forward PF / trade
counts / elapsed days) and ``find_verdict()`` (the gate verdict being
forward-tested). All thresholds are imported from ``backtest.live_readiness`` —
there is NO new strategy logic here.

Provides:
  GET /forward-test/status?symbol=MES  - latest forward-test status + as_of + staleness

Read-only. Missing data => explicit status ``not_run``.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.routers.forward_test")

router = APIRouter(prefix="/forward-test", tags=["forward-test"])

DEFAULT_SYMBOL = "MES"


class ForwardTestStatus(BaseModel):
    """Latest forward-test (paper-validation) status for one symbol."""

    symbol: str
    status: str  # not_run | in_progress | pass | fail
    forward_pf: Optional[float] = None  # None when n_closed==0 OR PF is infinite
    forward_pf_infinite: bool = False  # True when there are no losing trades
    n_closed: int = 0
    n_open: int = 0
    days_elapsed: Optional[int] = None
    total_pnl: float = 0.0
    # the gate verdict being forward-tested (None when no verdict file on disk)
    gate_verdict: Optional[str] = None
    gate_family: Optional[str] = None
    gate_created_at: Optional[str] = None
    # honest staleness — as_of is the most recent of (gate verdict, last paper entry)
    as_of: Optional[str] = None
    as_of_age_days: Optional[int] = None
    stale: bool = False
    # the canonical thresholds this status was judged against (provenance, not new logic)
    thresholds: dict[str, Any]
    detail: str
    generated_at: str


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _live_gate_family(symbol: str) -> Optional[str]:
    """Resolve the gate-verdict ``family`` for the strategy ACTUALLY routed live
    for ``symbol`` (from paper_config), so the forward-test surfaces the verdict
    being traded rather than the best-RANKED PASS on disk.

    The attribution bug this fixes: ``find_verdict(symbol)`` with no family picked
    the lowest-rank PASS, so MGC surfaced ``trend_rv_filter`` (rank1) while the
    engine trades plain ``trend`` (rank4). Returns ``None`` when the live family
    can't be determined — preserving find_verdict's best-verdict default for
    symbols/strategies without a clean mapping. Forward-compatible: if MGC is later
    switched to the RV-filter variant (``min_rv_annualized`` set in paper_config),
    this resolves to ``trend_rv_filter`` automatically.
    """
    try:
        from backtest.paper_config import PAPER_CONFIGS

        cfg = PAPER_CONFIGS.get(symbol)
        if not cfg:
            return None
        if cfg.get("strategy") == "sma_trend":
            rv = (cfg.get("sma_params") or {}).get("min_rv_annualized") or 0.0
            return "trend_rv_filter" if rv > 0 else "trend"
        return None
    except Exception:  # defensive — attribution must never 500 the endpoint
        return None


@router.get(
    "/status",
    response_model=ForwardTestStatus,
    summary="Latest forward-test (paper-validation) status for a symbol",
)
def get_forward_test_status(
    symbol: str = Query(DEFAULT_SYMBOL, description="Instrument symbol, e.g. MES"),
) -> ForwardTestStatus:
    # Late imports so the module loads even if the heavy backtest package is
    # mid-refactor; also keeps the import graph at call time, not module load.
    from backtest.live_readiness import (
        PAPER_MIN_DAYS,
        PAPER_MIN_PF,
        PAPER_MIN_TRADES,
        VERDICT_TTL_DAYS,
        _parse_iso,
        _query_paper_trade_stats,
    )
    from routers.strategy_ledger_router import find_verdict

    symbol = (symbol or DEFAULT_SYMBOL).upper()
    now = datetime.now(tz=timezone.utc)
    thresholds = {
        "min_days": PAPER_MIN_DAYS,
        "min_trades": PAPER_MIN_TRADES,
        "min_pf": PAPER_MIN_PF,
        "verdict_ttl_days": VERDICT_TTL_DAYS,
    }

    # --- read the two existing stores (no recompute) ----------------------
    try:
        stats = _query_paper_trade_stats(symbol)
    except Exception as exc:  # defensive — a bad JSONL must not 500 the endpoint
        logger.warning("forward-test: paper-trade read failed for %s: %s", symbol, exc)
        stats = {
            "n_closed": 0, "n_open": 0, "days_elapsed": None,
            "forward_pf": None, "total_pnl": 0.0, "available": False,
            "last_entry": None,
        }
    try:
        # Surface the verdict for the strategy ACTUALLY traded live (not the
        # best-ranked PASS on disk) — see _live_gate_family.
        verdict = find_verdict(symbol, family=_live_gate_family(symbol))
    except Exception as exc:
        logger.warning("forward-test: verdict read failed for %s: %s", symbol, exc)
        verdict = None

    n_closed = int(stats.get("n_closed") or 0)
    n_open = int(stats.get("n_open") or 0)
    days = stats.get("days_elapsed")
    pf = stats.get("forward_pf")  # float | inf | None
    available = bool(stats.get("available"))
    has_paper = n_closed > 0 or n_open > 0

    gate_verdict = verdict.get("verdict") if verdict else None
    gate_family = verdict.get("family") if verdict else None
    gate_created_at = verdict.get("created_at") if verdict else None

    # --- as_of + staleness ------------------------------------------------
    candidates = []
    v_dt = _parse_iso(gate_created_at) if gate_created_at else None
    if v_dt is not None:
        candidates.append(v_dt)
    last_entry = stats.get("last_entry")
    if isinstance(last_entry, datetime):
        candidates.append(last_entry if last_entry.tzinfo else last_entry.replace(tzinfo=timezone.utc))
    as_of_dt = max(candidates) if candidates else None
    as_of_age_days = (now - as_of_dt).days if as_of_dt is not None else None
    stale = as_of_age_days is not None and as_of_age_days > VERDICT_TTL_DAYS

    # --- status (canonical thresholds, no new logic) ----------------------
    pf_infinite = pf is not None and isinstance(pf, float) and math.isinf(pf)
    if not available or not has_paper:
        status = "not_run"
        detail = (
            f"No paper trades recorded for {symbol}; "
            + (f"gate verdict on disk = {gate_verdict}." if gate_verdict else "no gate verdict on disk.")
        )
    elif n_closed < PAPER_MIN_TRADES or (days or 0) < PAPER_MIN_DAYS:
        status = "in_progress"
        detail = (
            f"{n_closed}/{PAPER_MIN_TRADES} closed trades, "
            f"{days or 0}/{PAPER_MIN_DAYS} days elapsed."
        )
    else:
        pf_ok = pf is not None and pf >= PAPER_MIN_PF
        status = "pass" if pf_ok else "fail"
        pf_label = "inf (no losing trades)" if pf_infinite else f"{pf:.3f}"
        detail = (
            f"forward PF {pf_label} vs >= {PAPER_MIN_PF} "
            f"over {n_closed} closed trades / {days}d."
        )

    # Sanitize PF for JSON (Infinity is non-standard JSON).
    out_pf = None if (pf is None or pf_infinite) else round(float(pf), 4)

    return ForwardTestStatus(
        symbol=symbol,
        status=status,
        forward_pf=out_pf,
        forward_pf_infinite=pf_infinite,
        n_closed=n_closed,
        n_open=n_open,
        days_elapsed=days,
        total_pnl=round(float(stats.get("total_pnl") or 0.0), 2),
        gate_verdict=gate_verdict,
        gate_family=gate_family,
        gate_created_at=gate_created_at,
        as_of=_iso(as_of_dt),
        as_of_age_days=as_of_age_days,
        stale=stale,
        thresholds=thresholds,
        detail=detail,
        generated_at=now.isoformat(),
    )
