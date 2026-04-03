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


class ValidationGatesSummary(BaseModel):
    """Validation gates summary for EOD endpoint."""

    model_config = ConfigDict(from_attributes=True)

    pf: float | None = None
    sharpe: float | None = None
    win_rate: float | None = None
    trades_count: int = 0
    days_trading: int = 0
    max_drawdown: float | None = None


class EODSummaryResponse(BaseModel):
    """End-of-day summary response."""

    model_config = ConfigDict(from_attributes=True)

    date: str  # YYYY-MM-DD
    trades_today: int
    pnl_today_usd: float
    wins_today: int
    losses_today: int
    win_rate_today: float | None = None
    avg_r_today: float | None = None
    cumulative_trades: int
    cumulative_pnl_usd: float
    validation_gates: ValidationGatesSummary
    status: str  # 'on_track' | 'at_risk' | 'insufficient_data'


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
    avg_conviction_score: float = Field(
        ..., description="Average conviction score (0-1) from Layer 5 position sizing"
    )
    overall_pass: bool = Field(..., description="True if all gates pass or are met")


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
    annual_std = std_dev * (252**0.5)

    sharpe = (annual_return - risk_free_rate) / annual_std if annual_std > 0 else 0.0
    return round(max(0.0, sharpe), 2)


def _compute_max_drawdown_pct(trades: list[dict]) -> float:
    """Compute max drawdown percentage from trades."""
    if not trades:
        return 0.0

    from collections import defaultdict
    from datetime import datetime

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


def _compute_conviction_score(trades: list[dict], base_risk_pct: float = 0.02) -> float:
    """
    Compute average conviction score from Layer 5 position sizing.
    Returns average risk_pct_used / base_risk_pct across all trades with conviction data.
    Score ranges 0.0-1.0 where 1.0 means full size (maximum conviction).
    """
    if not trades:
        return 0.0

    conviction_trades = [t for t in trades if t.get("risk_pct_used") is not None]
    if not conviction_trades:
        return 0.0

    conviction_scores = []
    for trade in conviction_trades:
        risk_used = float(trade.get("risk_pct_used", 0.0))
        if base_risk_pct > 0:
            score = risk_used / base_risk_pct
            conviction_scores.append(min(score, 1.0))

    if not conviction_scores:
        return 0.0

    return round(sum(conviction_scores) / len(conviction_scores), 2)


@router.get("/gates")
async def get_validation_gates():
    """
    Get validation gates progress.

    Returns all 6 validation gates with current/target values and pass status.
    """
    try:
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

        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # Profit factor: gross_profit / abs(gross_loss)
        gross_profit = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) > 0)
        gross_loss = sum(abs(t.get("pnl", 0)) for t in closed_trades if t.get("pnl", 0) < 0)
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else (gross_profit if gross_profit > 0 else 0.0)
        )

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

        # Compute average conviction score from Layer 5 position sizing
        base_risk = 0.02  # 2% base risk per trade (per spec US-1403)
        avg_conviction = _compute_conviction_score(closed_trades, base_risk)

        # Overall pass: all gates must pass
        overall_pass = all(g.passes for g in gates)

        return ValidationGatesResponse(
            gates=gates,
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            avg_conviction_score=avg_conviction,
            overall_pass=overall_pass,
        )
    except Exception as exc:
        logger.error(f"Validation gates error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get("/summary/eod")
async def get_eod_summary():
    """
    Get end-of-day summary: today's P&L, trades, and validation gates progress.

    Returns status: 'insufficient_data' if < 5 trades, 'on_track' if gates passing,
    'at_risk' otherwise.
    """
    try:
        from datetime import datetime

        from engine.database import get_db

        db = get_db()

        # Fetch all closed trades (for cumulative stats)
        closed_trades = db.get_closed_trades(limit=1000)

        # Get today's date in ISO format
        today_str = datetime.utcnow().date().isoformat()

        # Fetch today's trades: WHERE status='closed' AND date(closed_at) = today
        sql = """
            SELECT symbol, side, quantity, entry_price, exit_price, pnl, closed_at
            FROM trades
            WHERE status = 'CLOSED'
            AND DATE(closed_at) = DATE(?);
        """

        with db._lock:
            conn = db._connect()
            try:
                rows = conn.execute(sql, (today_str,)).fetchall()
                today_trades = [dict(r) for r in rows]
            finally:
                conn.close()

        # Compute today's stats
        trades_today = len(today_trades)
        pnl_today = sum(float(t.get("pnl", 0)) for t in today_trades)
        wins_today = sum(1 for t in today_trades if float(t.get("pnl", 0)) > 0)
        losses_today = sum(1 for t in today_trades if float(t.get("pnl", 0)) < 0)

        win_rate_today = (wins_today / trades_today * 100) if trades_today > 0 else None

        # Compute avg R today (R = pnl / atr / contracts, but simplify to avg pnl per trade)
        avg_r_today = (pnl_today / trades_today) if trades_today > 0 else None

        # Compute cumulative stats
        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if float(t.get("pnl", 0)) > 0)
        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        gross_profit = sum(t.get("pnl", 0) for t in closed_trades if float(t.get("pnl", 0)) > 0)
        gross_loss = sum(abs(t.get("pnl", 0)) for t in closed_trades if float(t.get("pnl", 0)) < 0)
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else (gross_profit if gross_profit > 0 else 0.0)
        )

        cumulative_pnl = sum(float(t.get("pnl", 0)) for t in closed_trades)

        # Sharpe ratio
        sharpe_ratio = _compute_sharpe_ratio(closed_trades)

        # Max drawdown
        max_dd_pct = _compute_max_drawdown_pct(closed_trades)

        # Days elapsed (from daily_pnl table)
        sql_days = "SELECT COUNT(*) as cnt FROM daily_pnl"
        with db._lock:
            conn = db._connect()
            try:
                row = conn.execute(sql_days).fetchone()
                days_elapsed = int(row["cnt"]) if row else 0
            finally:
                conn.close()

        # Status logic
        if total_trades < 5:
            status = "insufficient_data"
        elif profit_factor >= 1.5 and win_rate_pct >= 50.0 and total_trades >= 10:
            status = "on_track"
        else:
            status = "at_risk"

        # Response
        return EODSummaryResponse(
            date=today_str,
            trades_today=trades_today,
            pnl_today_usd=round(pnl_today, 2),
            wins_today=wins_today,
            losses_today=losses_today,
            win_rate_today=round(win_rate_today, 2) if win_rate_today is not None else None,
            avg_r_today=round(avg_r_today, 2) if avg_r_today is not None else None,
            cumulative_trades=total_trades,
            cumulative_pnl_usd=round(cumulative_pnl, 2),
            validation_gates=ValidationGatesSummary(
                pf=round(profit_factor, 2) if profit_factor > 0 else None,
                sharpe=sharpe_ratio if sharpe_ratio > 0 else None,
                win_rate=round(win_rate_pct, 2) if total_trades > 0 else None,
                trades_count=total_trades,
                days_trading=days_elapsed,
                max_drawdown=round(max_dd_pct, 2) if max_dd_pct > 0 else None,
            ),
            status=status,
        )
    except Exception as exc:
        logger.error(f"EOD summary error: {exc}")
        raise HTTPException(500, str(exc)) from exc


# In-sample Profit Factor references for WFE calculation
IN_SAMPLE_PF: dict[str, float] = {
    "MCL": 5.3,
    "MNQ": 1.51,
}


class WFEInstrument(BaseModel):
    """WFE metrics for a single instrument."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(..., description="Symbol (MCL, MNQ)")
    current_wfe: float | None = Field(..., description="Current WFE (0-1 scale)")
    kill_threshold: float = Field(..., description="Kill threshold for WFE")
    status: str = Field(
        ...,
        description="Status: healthy, warning, critical, or insufficient_data",
    )
    trades_in_window: int = Field(..., description="Number of trades in window")
    window_days: int = Field(..., description="Window size in days")
    current_pf: float | None = Field(..., description="Current profit factor")


class WFEResponse(BaseModel):
    """Rolling WFE monitoring response."""

    model_config = ConfigDict(from_attributes=True)

    instruments: list[WFEInstrument] = Field(..., description="WFE metrics per instrument")
    as_of: str = Field(..., description="ISO datetime when computed")


def _compute_rolling_wfe(
    closed_trades: list[dict],
    symbol: str,
    window_days: int = 30,
    min_trades: int = 10,
) -> tuple[float | None, float, str]:
    """
    Compute rolling WFE for an instrument.

    Returns: (current_wfe, current_pf, status)
    """
    if len(closed_trades) < min_trades:
        return None, 0.0, "insufficient_data"

    # Compute profit factor from closed trades
    gross_profit = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl", 0) > 0)
    gross_loss = sum(abs(t.get("pnl", 0)) for t in closed_trades if t.get("pnl", 0) < 0)
    current_pf = (
        (gross_profit / gross_loss)
        if gross_loss > 0
        else (gross_profit if gross_profit > 0 else 0.0)
    )

    # WFE formula: (current_pf - 1.0) / (in_sample_pf - 1.0), clamped [0, 1]
    in_sample_pf = IN_SAMPLE_PF.get(symbol, 1.0)
    if in_sample_pf <= 1.0:
        wfe = 0.0
    else:
        wfe = (current_pf - 1.0) / (in_sample_pf - 1.0)
        wfe = max(0.0, min(1.0, wfe))

    return wfe, current_pf, "ok"


@router.get("/wfe")
async def get_rolling_wfe():
    """
    Get rolling Walk-Forward Efficiency for each active instrument.

    Returns WFE metrics with status (healthy/warning/critical).
    """
    try:
        from datetime import datetime

        from engine.backtest.paper_config import (
            ACTIVE_INSTRUMENTS,
            PAPER_CONFIGS,
        )
        from engine.database import get_db

        db = get_db()

        # Fetch all closed trades
        closed_trades = db.get_closed_trades(limit=1000)

        # Kill thresholds from paper_config
        kill_thresholds = {}
        for symbol in ACTIVE_INSTRUMENTS:
            cfg = PAPER_CONFIGS.get(symbol, {})
            kt = cfg.get("kill_threshold", {})
            kill_thresholds[symbol] = kt.get("rolling_wfe_minimum", 0.5)

        # Compute WFE per instrument
        window_days = 30
        instruments: list[WFEInstrument] = []

        for symbol in ACTIVE_INSTRUMENTS:
            # Filter trades for this symbol in the window
            symbol_trades = [
                t for t in closed_trades if t.get("symbol", "").upper() == symbol.upper()
            ]

            wfe, pf, status = _compute_rolling_wfe(symbol_trades, symbol, window_days=window_days)

            # Determine overall status based on thresholds
            kill_threshold = kill_thresholds.get(symbol, 0.5)
            if status == "insufficient_data":
                overall_status = "insufficient_data"
            elif wfe is None:
                overall_status = "insufficient_data"
            else:
                # healthy = wfe >= threshold
                # warning = within 20% of threshold
                # critical = below 80% of threshold
                warning_threshold = kill_threshold * 0.80
                if wfe >= kill_threshold:
                    overall_status = "healthy"
                elif wfe >= warning_threshold:
                    overall_status = "warning"
                else:
                    overall_status = "critical"

            instruments.append(
                WFEInstrument(
                    symbol=symbol,
                    current_wfe=wfe,
                    kill_threshold=kill_threshold,
                    status=overall_status,
                    trades_in_window=len(symbol_trades),
                    window_days=window_days,
                    current_pf=pf if status == "ok" else None,
                )
            )

        return WFEResponse(
            instruments=instruments,
            as_of=datetime.utcnow().isoformat() + "Z",
        )

    except Exception as exc:
        logger.error(f"Rolling WFE error: {exc}")
        raise HTTPException(500, str(exc)) from exc
