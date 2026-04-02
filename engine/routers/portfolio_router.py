"""
Portfolio router - unified multi-market portfolio summary.

GET /portfolio/summary - total P&L, all markets, daily target progress
GET /portfolio/health - health status of all market modules
GET /portfolio/halt - emergency halt all markets (POST)
GET /portfolio/resume - resume after halt (POST)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger("jarvis_trader.routers.portfolio")

router = APIRouter(prefix="", tags=["portfolio", "multi-market"])

TARGET_TRADING_DAYS = 30

# Global references (injected from main.py)
paper_tracker = None
db_manager = None


def inject_dependencies(pt, dbm):
    """Inject dependencies from main.py"""
    global paper_tracker, db_manager
    paper_tracker = pt
    db_manager = dbm


def _get_orchestrator():
    try:
        from orchestrator import get_orchestrator

        return get_orchestrator()
    except Exception:
        return None


def _parse_trade_day(row: Any) -> date | None:
    """Best-effort calendar day (UTC) from a closed-trade row (dict or object)."""
    ts = None
    if isinstance(row, dict):
        ts = row.get("exit_time") or row.get("entry_time")
    else:
        ts = getattr(row, "exit_time", None) or getattr(row, "entry_time", None)
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).date()
    s = str(ts).strip()
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _row_is_closed(row: Any) -> bool:
    """True if the row represents a completed exit (SQLite dict or PaperTrade dict)."""
    if isinstance(row, dict):
        if row.get("is_open") is True:
            return False
        st = str(row.get("status") or "").strip().lower()
        if st == "open":
            return False
        if row.get("exit_time") is not None:
            return True
        if st == "closed":
            return True
        if row.get("exit_price") is not None and row.get("is_open") is False:
            return True
        return False
    if getattr(row, "is_open", None) is True:
        return False
    return getattr(row, "exit_time", None) is not None


def _row_pnl(row: Any) -> float:
    if isinstance(row, dict):
        p = row.get("pnl")
    else:
        p = getattr(row, "pnl", None)
    if p is None:
        return 0.0
    try:
        return float(p)
    except (TypeError, ValueError):
        return 0.0


@router.get("")
@router.get("/summary")
async def portfolio_summary():
    """Unified multi-market P&L summary."""
    orch = _get_orchestrator()
    if not orch:
        return {
            "total_daily_pnl": 0.0,
            "daily_target": 500.0,
            "target_progress_pct": 0.0,
            "markets": {},
            "message": "Orchestrator not initialized",
        }
    summary = await orch.get_portfolio_summary()
    return summary


@router.get("/health")
async def portfolio_health():
    """Health status of all registered market modules."""
    orch = _get_orchestrator()
    if not orch:
        return {"modules": [], "message": "Orchestrator not initialized"}

    statuses = orch.get_all_health()
    return {
        "modules": [
            {
                "market": h.market,
                "status": h.status.value,
                "message": h.message,
                "daily_pnl": h.daily_pnl,
                "open_positions": h.open_positions,
            }
            for h in statuses
        ],
        "count": len(statuses),
    }


@router.post("/halt")
async def halt(reason: str = "Manual halt via API"):
    """Emergency halt all market modules."""
    orch = _get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    orch.halt_all(reason=reason)
    return {"status": "halted", "reason": reason}


@router.post("/resume")
async def resume():
    """Resume trading after a halt (requires investigation first)."""
    orch = _get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    orch.resume()
    return {"status": "resumed"}


# GET /portfolio/stats/streaks - canonical handler is on the FastAPI app in main.py (StreakBadge).


@router.get("/stats/paper-phase-summary")
async def paper_phase_summary():
    """
    Paper validation phase rollup: balance, return, distinct trading days, status.
    Uses PortfolioTracker closed-trade history and settings.INITIAL_CAPITAL.
    """
    starting = float(settings.INITIAL_CAPITAL)
    base = {
        "phase": "paper",
        "start_date": "",
        "starting_balance": starting,
        "current_balance": starting,
        "total_return_pct": 0.0,
        "total_pnl": 0.0,
        "trading_days": 0,
        "target_trading_days": TARGET_TRADING_DAYS,
        "trades_completed": 0,
        "validation_status": "no_tracker",
    }
    if not paper_tracker:
        return base

    rows: list[Any] = []
    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("paper_phase_summary: get_trade_history failed: %s", exc)
        rows = []

    closed_rows = [r for r in rows if _row_is_closed(r)]
    days_set: set[date] = set()
    for r in closed_rows:
        d = _parse_trade_day(r)
        if d is not None:
            days_set.add(d)

    total_pnl = sum(_row_pnl(r) for r in closed_rows)
    if not closed_rows:
        try:
            perf = paper_tracker.get_performance()
            total_pnl = float(perf.get("total_pnl") or 0.0)
        except Exception as exc:
            logger.warning("paper_phase_summary: get_performance fallback failed: %s", exc)

    current_balance = starting + total_pnl
    total_return_pct = (total_pnl / starting * 100.0) if starting else 0.0

    start_date = ""
    if days_set:
        start_date = min(days_set).isoformat()

    trades_completed = len(closed_rows)
    trading_days = len(days_set)

    if trades_completed == 0 and total_pnl == 0.0:
        validation_status = "no_trades"
    else:
        try:
            perf = paper_tracker.get_performance()
            pf = perf.get("profit_factor")
        except Exception:
            pf = None
        if trading_days >= TARGET_TRADING_DAYS:
            if pf is not None and float(pf) >= 2.0:
                validation_status = "passed"
            else:
                validation_status = "review_ready"
        else:
            validation_status = "in_progress"

    return {
        "phase": "paper",
        "start_date": start_date,
        "starting_balance": starting,
        "current_balance": round(current_balance, 4),
        "total_return_pct": round(total_return_pct, 4),
        "total_pnl": round(total_pnl, 4),
        "trading_days": trading_days,
        "target_trading_days": TARGET_TRADING_DAYS,
        "trades_completed": trades_completed,
        "validation_status": validation_status,
    }


class PaperTradeSyncRequest(BaseModel):
    """Paper runner / external sync -> engine PortfolioTracker."""

    action: str = Field(..., description="open | close")
    symbol: str = Field(..., min_length=1)
    side: str | None = Field(None, description="long | short (for open)")
    quantity: float = Field(1.0, gt=0)
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    trade_id: str | None = Field(None, description="PortfolioTracker id - required for close")
    notes: str = ""


@router.get("/paper/positions")
async def paper_positions():
    """Open paper positions (SQLite + in-memory tracker)."""
    if not paper_tracker:
        return {"positions": [], "count": 0}
    raw = paper_tracker.get_open_positions()
    return {"positions": raw, "count": len(raw)}


@router.get("/paper/performance")
async def paper_performance():
    """Closed-trade performance summary."""
    if not paper_tracker:
        return {"performance": {}}
    return {"performance": paper_tracker.get_performance()}


@router.post("/paper/trade")
async def paper_trade(req: PaperTradeSyncRequest):
    """Record paper open/close from `paper_runner` or external scripts."""
    if not paper_tracker:
        raise HTTPException(status_code=503, detail="Paper portfolio tracker not initialized")

    sym = req.symbol.upper()
    act = req.action.lower().strip()

    if act == "open":
        if req.entry_price is None:
            raise HTTPException(status_code=422, detail="entry_price required for open")
        side = (req.side or "long").lower()
        if side not in ("long", "short"):
            raise HTTPException(status_code=422, detail="side must be long or short")
        action = "buy" if side == "long" else "sell"
        tid = paper_tracker.open_trade(
            sym,
            action,
            req.quantity,
            float(req.entry_price),
            notes=req.notes or "paper_runner_sync",
        )
        return {
            "status": "open",
            "trade_id": tid,
            "symbol": sym,
            "action": action,
            "quantity": req.quantity,
            "entry_price": req.entry_price,
        }

    if act == "close":
        if not req.trade_id:
            raise HTTPException(status_code=422, detail="trade_id required for close")
        if req.exit_price is None:
            raise HTTPException(status_code=422, detail="exit_price required for close")
        try:
            closed = paper_tracker.close_trade(req.trade_id, float(req.exit_price))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "status": "closed",
            "trade_id": closed.trade_id,
            "symbol": closed.symbol,
            "action": closed.action,
            "quantity": closed.quantity,
            "entry_price": closed.entry_price,
            "pnl": closed.pnl,
        }

    raise HTTPException(status_code=422, detail="action must be open or close")


@router.get("/history/trades")
async def portfolio_history_trades(limit: int = 50):
    """Recent closed paper trades for dashboards."""
    if not paper_tracker or not hasattr(paper_tracker, "get_trade_history"):
        return []
    rows = paper_tracker.get_trade_history(limit=min(max(limit, 1), 500))
    out: list[dict] = []
    for t in rows:
        d = t if isinstance(t, dict) else t.to_dict()
        ts = d.get("exit_time") or d.get("entry_time") or ""
        price = d.get("exit_price")
        if price is None:
            price = d.get("entry_price")
        side = str(d.get("action", "hold")).upper()
        if "BUY" in side or side == "BUY":
            action = "BUY"
        elif "SELL" in side or side == "SELL":
            action = "SELL"
        else:
            action = "HOLD"
        out.append(
            {
                "timestamp": ts,
                "symbol": d.get("symbol", ""),
                "action": action,
                "quantity": float(d.get("quantity") or 0),
                "price": float(price or 0),
                "pnl": d.get("pnl"),
                "trade_id": d.get("trade_id"),
            }
        )
    return out
