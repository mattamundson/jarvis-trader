"""
Portfolio router — unified multi-market portfolio summary.
GET /portfolio/summary — total P&L, all markets, daily target progress
GET /portfolio/health — health status of all market modules
GET /portfolio/risk — cross-market risk state
GET /portfolio/halt — emergency halt all markets (POST)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("jarvis_trader.routers.portfolio")

router = APIRouter(prefix="", tags=["portfolio", "multi-market"])

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
async def halt_all_markets(reason: str = "Manual halt via API"):
    """Emergency halt all market modules."""
    orch = _get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    orch.halt_all(reason=reason)
    return {"status": "halted", "reason": reason}


@router.post("/resume")
async def resume_trading():
    """Resume trading after a halt (requires investigation first)."""
    orch = _get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    orch.resume()
    return {"status": "resumed"}


@router.get("/stats/streaks")
async def streak_stats():
    """Return win/loss streak statistics from trade history."""
    if not paper_tracker:
        return {"current_win_streak": 0, "current_loss_streak": 0, "max_win_streak": 0, "max_loss_streak": 0}
    try:
        trades = paper_tracker.get_closed_trades() if hasattr(paper_tracker, "get_closed_trades") else []
        max_wins = 0
        cur_wins = 0
        cur_losses = 0
        for t in trades:
            pnl = getattr(t, "pnl", None) or (t.get("pnl") if isinstance(t, dict) else 0) or 0
            if pnl > 0:
                cur_wins += 1
                cur_losses = 0
                if cur_wins > max_wins:
                    max_wins = cur_wins
            else:
                cur_losses += 1
                pass

    except Exception:
        return {"max_consecutive_wins": 0, "max_consecutive_losses": 0}


class PaperTradeSyncRequest(BaseModel):
    """Paper runner / external sync → engine PortfolioTracker."""

    action: str = Field(..., description="open | close")
    symbol: str = Field(..., min_length=1)
    side: str | None = Field(None, description="long | short (for open)")
    quantity: float = Field(1.0, gt=0)
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    trade_id: str | None = Field(None, description="PortfolioTracker id — required for close")
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
