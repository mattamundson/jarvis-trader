"""
Paper Validation Router — expose validation metrics via API (READ-ONLY).

Consolidation note (US-303): This router now reads validation metrics from
ValidationTracker (which reads from PaperTradeTracker's JSON files). All state
writes are managed by PaperTradeTracker directly.

Endpoints:
  GET /paper/validation/progress — current metrics vs thresholds
  GET /paper/validation/trades — list of all paper trades
  GET /paper/validation/status — overall pass/fail + days remaining
  POST /paper/validation/record — DEPRECATED (kept for compatibility, no-op)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper/validation", tags=["paper_validation"])


class RecordTradeRequest(BaseModel):
    """Request to record a paper trade."""

    model_config = ConfigDict(from_attributes=True)

    instrument: str = Field(..., description="Symbol (MCL, MNQ, etc)")
    entry_price: float = Field(..., description="Entry price")
    exit_price: float = Field(..., description="Exit price")
    pnl: float = Field(..., description="Profit/loss")
    setup_grade: str = Field("unknown", description="Setup grade (A, B, C, etc)")


class ValidationProgressResponse(BaseModel):
    """Validation progress response."""

    model_config = ConfigDict(from_attributes=True)

    instrument: str
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    days_active: int
    is_validated: bool
    pass_fail: dict
    thresholds: dict


def _get_tracker():
    """Lazy-load tracker singleton."""
    from paper.validation_tracker import ValidationTracker

    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    return ValidationTracker(data_dir=data_dir)


@router.get("/progress")
async def get_validation_progress(instrument: str = "MCL"):
    """Get current validation metrics vs thresholds."""
    try:
        tracker = _get_tracker()
        progress = tracker.get_progress(instrument)
        return {"status": "ok", "data": progress}
    except Exception as exc:
        logger.error(f"Validation progress error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get("/trades")
async def get_validation_trades(instrument: str = "MCL"):
    """Get all recorded trades for an instrument."""
    try:
        tracker = _get_tracker()
        trades = tracker.get_all_trades(instrument)
        return {"status": "ok", "instrument": instrument, "trades": trades}
    except Exception as exc:
        logger.error(f"Validation trades query error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.post("/record")
async def record_validation_trade(request: RecordTradeRequest):
    """
    DEPRECATED (US-303): This endpoint is deprecated.

    Paper trades are now recorded directly by paper_runner.py via
    PaperTradeTracker.add_trade(). ValidationTracker reads the tracker's
    JSON files in read-only mode.

    This endpoint is kept for backward compatibility and returns current
    metrics without persisting new trades.
    """
    try:
        tracker = _get_tracker()
        logger.warning(
            f"POST /paper/validation/record deprecated. Use PaperTradeTracker directly. "
            f"Request ignored: {request.instrument}"
        )
        progress = tracker.get_progress(request.instrument)
        return {
            "status": "deprecated",
            "message": "POST /record is deprecated. Trades are managed by PaperTradeTracker.",
            "data": progress,
        }
    except Exception as exc:
        logger.error(f"Trade recording error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get("/status")
async def get_validation_status():
    """Get overall validation status."""
    try:
        tracker = _get_tracker()
        data = tracker.get_dashboard_data()
        return {"status": "ok", "data": data}
    except Exception as exc:
        logger.error(f"Validation status error: {exc}")
        raise HTTPException(500, str(exc)) from exc


class ValidationGate(BaseModel):
    """Single validation gate (target metric)."""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., description="Gate name (profit_factor, etc)")
    current: float = Field(..., description="Current value")
    target: float = Field(..., description="Target value")
    passes: bool = Field(..., description="Whether gate passes")
    unit: str = Field(default="", description="Unit for display (%, days, etc)")


class ValidationGatesResponse(BaseModel):
    """Validation gates progress response."""

    model_config = ConfigDict(from_attributes=True)

    gates: list[ValidationGate]
    days_elapsed: int = Field(..., description="Days since paper trading started")
    days_remaining: int = Field(..., description="Days until 30-day validation window closes")
    overall_pass: bool = Field(
        ..., description="True if all gates pass or are met"
    )


def _compute_sharpe_ratio(trades: list[dict], risk_free_rate: float = 0.04) -> float:
    """
    Compute Sharpe ratio from closed trades.
    Uses daily P&L for more accurate annualized Sharpe.
    """
    if not trades:
        return 0.0

    # Group trades by day and sum daily P&L
    from collections import defaultdict
    from datetime import datetime

    daily_pnl = defaultdict(float)
    for trade in trades:
        exit_time_str = trade.get("exit_time")
        if not exit_time_str:
            continue
        try:
            dt = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
            day = dt.date()
            pnl = float(trade.get("pnl", 0.0))
            daily_pnl[day] += pnl
        except (ValueError, AttributeError):
            continue

    if not daily_pnl:
        return 0.0

    returns = list(daily_pnl.values())
    if len(returns) < 2:
        return 0.0

    import statistics

    avg_return = statistics.mean(returns)
    std_dev = statistics.stdev(returns) if len(returns) > 1 else 0.0

    if std_dev == 0:
        return 0.0

    # Annualize (252 trading days per year)
    annual_return = avg_return * 252
    annual_std = std_dev * (252 ** 0.5)
    daily_rf = risk_free_rate / 252

    sharpe = (annual_return - risk_free_rate) / annual_std if annual_std > 0 else 0.0
    return round(max(0.0, sharpe), 2)


def _compute_max_drawdown_pct(trades: list[dict]) -> float:
    """Compute max drawdown percentage from trades."""
    if not trades:
        return 0.0

    from datetime import datetime
    from collections import defaultdict

    # Rebuild equity curve from trades
    daily_balances = defaultdict(float)
    running_pnl = 0.0

    for trade in sorted(trades, key=lambda t: t.get("exit_time", "")):
        exit_time_str = trade.get("exit_time")
        if not exit_time_str:
            continue
        try:
            dt = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
            day = dt.date()
            pnl = float(trade.get("pnl", 0.0))
            running_pnl += pnl
            daily_balances[day] = 10000 + running_pnl  # Starting capital $10k
        except (ValueError, AttributeError):
            continue

    if not daily_balances:
        return 0.0

    balances = list(daily_balances.values())
    peak = 0.0
    max_dd = 0.0

    for balance in balances:
        if balance > peak:
            peak = balance
        dd = peak - balance
        if dd > max_dd:
            max_dd = dd

    if peak <= 0:
        return 0.0

    return round((max_dd / peak) * 100, 2)


@router.get("/gates")
async def get_validation_gates():
    """
    Get validation gates progress.

    Returns all 6 validation gates with current/target values and pass status.
    """
    try:
        from datetime import datetime, timedelta
        from engine.database import get_db

        db = get_db()

        # Fetch all closed trades
        closed_trades = db.get_closed_trades(limit=1000)

        # Fetch daily_pnl for days tracking
        sql = "SELECT COUNT(*) as cnt FROM daily_pnl"
        with db._lock:
            conn = db._connect()
            try:
                row = conn.execute(sql).fetchone()
                days_elapsed = int(row["cnt"]) if row else 0
            finally:
                conn.close()

        # Compute metrics
        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if t.get("pnl", 0) > 0)
        total_pnl = sum(t.get("pnl", 0) for t in closed_trades)

        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # Profit factor: gross_profit / abs(gross_loss)
        gross_profit = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) > 0)
        gross_loss = sum(abs(t.get("pnl", 0)) for t in closed_trades if t.get("pnl", 0) < 0)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        # Sharpe ratio
        sharpe_ratio = _compute_sharpe_ratio(closed_trades)

        # Max drawdown
        max_dd_pct = _compute_max_drawdown_pct(closed_trades)

        # Days remaining (target 30 days)
        days_remaining = max(0, 30 - days_elapsed)

        # Define validation targets
        targets = {
            "profit_factor": 2.0,
            "sharpe_ratio": 1.5,
            "win_rate": 55.0,
            "total_trades": 60,
            "days_active": 30,
            "max_drawdown": 15.0,
        }

        # Build gates
        gates = [
            ValidationGate(
                name="profit_factor",
                current=round(profit_factor, 2),
                target=targets["profit_factor"],
                passes=profit_factor >= targets["profit_factor"],
                unit="",
            ),
            ValidationGate(
                name="sharpe_ratio",
                current=sharpe_ratio,
                target=targets["sharpe_ratio"],
                passes=sharpe_ratio >= targets["sharpe_ratio"],
                unit="",
            ),
            ValidationGate(
                name="win_rate",
                current=round(win_rate_pct, 2),
                target=targets["win_rate"],
                passes=win_rate_pct >= targets["win_rate"],
                unit="%",
            ),
            ValidationGate(
                name="total_trades",
                current=total_trades,
                target=targets["total_trades"],
                passes=total_trades >= targets["total_trades"],
                unit="",
            ),
            ValidationGate(
                name="days_active",
                current=days_elapsed,
                target=targets["days_active"],
                passes=days_elapsed >= targets["days_active"],
                unit="days",
            ),
            ValidationGate(
                name="max_drawdown",
                current=round(max_dd_pct, 2),
                target=targets["max_drawdown"],
                passes=max_dd_pct <= targets["max_drawdown"],
                unit="%",
            ),
        ]

        # Overall pass: all gates must pass
        overall_pass = all(g.passes for g in gates)

        return ValidationGatesResponse(
            gates=gates,
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            overall_pass=overall_pass,
        )
    except Exception as exc:
        logger.error(f"Validation gates error: {exc}")
        raise HTTPException(500, str(exc)) from exc
