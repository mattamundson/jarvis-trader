"""Reports and analytics router."""

import logging
from datetime import datetime, timedelta
from datetime import timezone as _tz
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

router = APIRouter(prefix="/reports", tags=["reports"])
logger = logging.getLogger(__name__)


def get_db_path() -> str:
    """Return the SQLite database path (mirrors discord_router pattern)."""
    import os

    return os.environ.get("DB_PATH", "data/jarvis_trader.db")


# Global references (injected from main.py)
_db_manager = None


def inject_dependencies(db_manager):
    """Inject global dependencies from main.py"""
    global _db_manager
    _db_manager = db_manager


@router.get("/performance/7d")
async def get_7d_performance() -> dict[str, Any]:
    """Get 7-day performance summary."""
    try:
        from database.schema import get_db

        db = get_db()

        # Get all closed trades and filter to 7-day window
        cutoff = (datetime.now(_tz.utc) - timedelta(days=7)).isoformat()
        all_rows = db.get_closed_trades(limit=500)
        rows = [r for r in all_rows if r.get("exit_time", "") >= cutoff]

        if not rows or len(rows) == 0:
            return {
                "period": "7d",
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "trading_days": 0,
            }

        # Aggregate
        total = len(rows)
        wins = sum(1 for r in rows if r.get("pnl", 0) > 0)
        losses = total - wins
        total_pnl = sum(r.get("pnl", 0) for r in rows)
        pnls = [r.get("pnl", 0) for r in rows if r.get("pnl", 0)]

        return {
            "period": "7d",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total > 0 else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / total if total > 0 else 0.0,
            "best_trade": max(pnls) if pnls else 0.0,
            "worst_trade": min(pnls) if pnls else 0.0,
            "trading_days": 0,
        }
    except Exception as e:
        logger.error(f"[REPORTS] 7d performance error: {e}")
        raise HTTPException(500, f"Failed to get 7d performance: {e}") from e


@router.get("/quantstats")
async def get_quantstats(
    run_id: str | None = Query(
        None, description="Optional run identifier to filter paper_trades by notes field"
    ),
    days: int = Query(90, ge=7, le=365, description="Look-back window in calendar days"),
    db_path: str = Depends(get_db_path),
) -> dict[str, Any]:
    """Return a QuantStats metrics blob for the paper trading window.

    Prefers ``pnl_snapshots`` (equity-curve based); falls back to aggregating
    ``paper_trades.pnl`` by exit date.  Returns the shell with nulls (200) when
    no trades exist in the window — never raises on empty data.
    """
    try:
        from reports.quantstats_metrics import _load_pnl_series, compute_quantstats_metrics

        series, source, n_trades, start, end = _load_pnl_series(db_path, run_id, days)
        metrics = compute_quantstats_metrics(series, source=source)
        metrics.update(
            {"n_trades": n_trades, "start_date": start, "end_date": end, "source": source}
        )
        return metrics
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[REPORTS] quantstats error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
