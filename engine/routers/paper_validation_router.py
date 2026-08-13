"""
Paper Validation Router — expose validation metrics via API (READ-ONLY).

Consolidation note (US-303): This router now reads validation metrics from
ValidationTracker (which reads from PaperTradeTracker's JSON files). All state
writes are managed by PaperTradeTracker directly.

Endpoints:
  GET /paper/validation/progress — current metrics vs thresholds
  GET /paper/validation/trades — list of all paper trades
  GET /paper/validation/status — overall pass/fail + days remaining
  GET /paper/validation/counts — per-symbol closed-trade counts vs Q2 2026 thresholds (session-start display)
  GET /paper/validation/approved-paper-gates — gates for APPROVED_PAPER_SYMBOLS (MES/MGC) vs canonical thresholds (SQLite)
  POST /paper/validation/record — DEPRECATED (kept for compatibility, no-op)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from paper.validation_gate_config import APPROVED_PAPER_SYMBOLS, PAPER_VALIDATION_GATES

try:
    from database import get_db
except ImportError:  # pragma: no cover
    get_db = None  # type: ignore[assignment]

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
# Default was retired MCL (DO_NOT_TRADE), which masked the live MES/MGC windows.
async def get_validation_progress(instrument: str = "MES"):
    """Get current validation metrics vs thresholds."""
    try:
        tracker = _get_tracker()
        progress = tracker.get_progress(instrument)
        return {"status": "ok", "data": progress}
    except Exception as exc:
        logger.error(f"Validation progress error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get("/trades")
async def get_validation_trades(instrument: str = "MES"):
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


_Q2_PAPER_TARGETS = {"MES": 30, "MGC": 60, "MCL": 60, "MNQ": 60}
_Q2_BLOCKED_SYMBOLS = {"MCL", "MNQ"}
# MGC (target 60, unblocked — APPROVED/active) was previously absent from this
# counter, hiding progress for one of only two currently paper-active instruments.


@router.get("/counts")
async def get_paper_trade_counts():
    """
    Per-symbol paper-trade counts vs Q2 2026 live-readiness thresholds.

    Surfaces the session-start counter line defined in the Q2 roadmap:
        Paper trades — MES: X/30 | MCL: Y/60 (blocked) | MNQ: 0/60 (blocked)

    Counts only CLOSED paper trades (exit_time IS NOT NULL).
    """
    if get_db is None:
        raise HTTPException(500, "database module unavailable")
    counts: dict[str, int] = {}
    try:
        with get_db() as conn:
            for sym in _Q2_PAPER_TARGETS:
                row = conn.execute(
                    "SELECT COUNT(*) FROM paper_trades "
                    "WHERE symbol = ? AND exit_time IS NOT NULL",
                    (sym,),
                ).fetchone()
                counts[sym] = int(row[0]) if row else 0
    except Exception as exc:
        logger.error(f"Paper counts query error: {exc}")
        raise HTTPException(500, str(exc)) from exc

    parts = []
    for sym, target in _Q2_PAPER_TARGETS.items():
        tag = " (blocked)" if sym in _Q2_BLOCKED_SYMBOLS else ""
        parts.append(f"{sym}: {counts[sym]}/{target}{tag}")
    display = "Paper trades — " + " | ".join(parts)

    return {
        "counts": {
            sym: {
                "closed": counts[sym],
                "target": _Q2_PAPER_TARGETS[sym],
                "blocked": sym in _Q2_BLOCKED_SYMBOLS,
            }
            for sym in _Q2_PAPER_TARGETS
        },
        "display": display,
    }


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


class ApprovedInstrumentGateRow(BaseModel):
    """Validation gates for one approved paper symbol (MES / MGC)."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    trade_count: int
    days_with_trades: int
    gates: list[ValidationGate]
    overall_pass: bool


class ApprovedPaperGatesAPIResponse(BaseModel):
    """GET /paper/validation/approved-paper-gates"""

    model_config = ConfigDict(from_attributes=True)

    status: str = "ok"
    thresholds: dict[str, float | int]
    instruments: list[ApprovedInstrumentGateRow]
    note: str


def _distinct_trade_days(trades: list[dict]) -> int:
    """Count distinct calendar dates with a closed trade (exit_time)."""
    from datetime import datetime

    days: set = set()
    for trade in trades:
        exit_time_str = trade.get("exit_time")
        if not exit_time_str:
            continue
        try:
            dt = datetime.fromisoformat(str(exit_time_str).replace("Z", "+00:00"))
            days.add(dt.date())
        except (ValueError, AttributeError, TypeError):
            continue
    return len(days)


def _build_validation_gate_rows(
    closed_trades: list[dict],
    *,
    days_for_min_days_gate: int,
) -> tuple[list[ValidationGate], float, bool]:
    """
    Build the six validation gates from closed trade rows.

    ``days_for_min_days_gate`` is the value compared to ``min_days`` (global endpoint
    uses ``daily_pnl`` row count; per-symbol uses distinct exit dates).
    """
    cfg = PAPER_VALIDATION_GATES

    def _pnl(t: dict) -> float:
        return float(t.get("pnl") or 0)

    total_trades = len(closed_trades)
    winning_trades = sum(1 for t in closed_trades if _pnl(t) > 0)
    win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    gross_profit = sum(_pnl(t) for t in closed_trades if _pnl(t) > 0)
    gross_loss = sum(abs(_pnl(t)) for t in closed_trades if _pnl(t) < 0)
    profit_factor = (
        (gross_profit / gross_loss) if gross_loss > 0 else (9999.0 if gross_profit > 0 else 0.0)
    )
    sharpe_ratio = _compute_sharpe_ratio(closed_trades)
    max_dd_pct = _compute_max_drawdown_pct(closed_trades)

    pf_t = float(cfg["profit_factor"])
    sharpe_t = float(cfg["sharpe_ratio"])
    wr_t = float(cfg["win_rate_pct"])
    trades_t = int(cfg["min_trades"])
    days_t = int(cfg["min_days"])
    dd_t = float(cfg["max_drawdown_pct"])

    gates = [
        ValidationGate(
            name="profit_factor",
            current=round(profit_factor, 2),
            target=pf_t,
            passes=profit_factor >= pf_t,
            unit="",
        ),
        ValidationGate(
            name="sharpe_ratio",
            current=sharpe_ratio,
            target=sharpe_t,
            passes=sharpe_ratio >= sharpe_t,
            unit="",
        ),
        ValidationGate(
            name="win_rate",
            current=round(win_rate_pct, 2),
            target=wr_t,
            passes=win_rate_pct >= wr_t,
            unit="%",
        ),
        ValidationGate(
            name="total_trades",
            current=total_trades,
            target=float(trades_t),
            passes=total_trades >= trades_t,
            unit="",
        ),
        ValidationGate(
            name="days_active",
            current=float(days_for_min_days_gate),
            target=float(days_t),
            passes=days_for_min_days_gate >= days_t,
            unit="days",
        ),
        ValidationGate(
            name="max_drawdown",
            current=round(max_dd_pct, 2),
            target=dd_t,
            passes=max_dd_pct <= dd_t,
            unit="%",
        ),
    ]
    avg_conviction = _compute_conviction_score(closed_trades)
    overall_pass = all(g.passes for g in gates)
    return gates, avg_conviction, overall_pass


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
            pnl = float(trade.get("pnl") or 0.0)
            daily_pnl[day] += pnl
        except (ValueError, AttributeError, TypeError):
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

    for trade in sorted(trades, key=lambda t: t.get("exit_time") or ""):
        exit_time_str = trade.get("exit_time")
        if not exit_time_str:
            continue
        try:
            dt = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
            day = dt.date()
            pnl = float(trade.get("pnl") or 0.0)
            running_pnl += pnl
            daily_balances[day] = 10000 + running_pnl  # Starting capital $10k
        except (ValueError, AttributeError, TypeError):
            continue

    if not daily_balances:
        return 0.0

    # Canonical guarded drawdown: floors the peak denominator against starting
    # capital ($10k), so a curve that dips below its start is measured honestly
    # (the pre-#272 peak=0 seed silently missed drawdown below starting capital).
    from analytics import metrics

    balances = list(daily_balances.values())
    dd = metrics.max_drawdown_pct(balances, starting_capital=10000)
    return round(dd if dd is not None else 0.0, 2)


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
        from database import get_db

        db = get_db()

        closed_trades = db.get_closed_trades(limit=1000)

        sql = "SELECT COUNT(*) as cnt FROM daily_pnl"
        with db._lock:
            conn = db._connect()
            try:
                row = conn.execute(sql).fetchone()
                days_elapsed = int(row["cnt"]) if row else 0
            finally:
                conn.close()

        gates, avg_conviction, overall_pass = _build_validation_gate_rows(
            closed_trades,
            days_for_min_days_gate=days_elapsed,
        )

        min_days = int(PAPER_VALIDATION_GATES["min_days"])
        days_remaining = max(0, min_days - days_elapsed)

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


@router.get("/approved-paper-gates", response_model=ApprovedPaperGatesAPIResponse)
async def get_approved_paper_gates():
    """
    Validation gates for the currently-approved paper futures (`APPROVED_PAPER_SYMBOLS`).

    Metrics are computed from **SQLite** ``paper_trades`` closed rows per symbol.
    ``days_with_trades`` = distinct ``exit_time`` calendar dates (not ``daily_pnl`` rows).
    """
    try:
        from database import get_db

        db = get_db()
        instruments: list[ApprovedInstrumentGateRow] = []

        for sym in APPROVED_PAPER_SYMBOLS:
            trades = db.get_closed_trades(symbol=sym, limit=5000)
            days_distinct = _distinct_trade_days(trades)
            gates, _, overall_pass = _build_validation_gate_rows(
                trades,
                days_for_min_days_gate=days_distinct,
            )
            instruments.append(
                ApprovedInstrumentGateRow(
                    symbol=sym,
                    trade_count=len(trades),
                    days_with_trades=days_distinct,
                    gates=gates,
                    overall_pass=overall_pass,
                )
            )

        return ApprovedPaperGatesAPIResponse(
            status="ok",
            thresholds=dict(PAPER_VALIDATION_GATES),
            instruments=instruments,
            note=(
                "Per-symbol gates use closed paper_trades (SQLite) for APPROVED_PAPER_SYMBOLS "
                "only; days_active gate uses distinct exit dates. Global /gates uses all "
                "symbols and daily_pnl row count for the days gate."
            ),
        )
    except Exception as exc:
        logger.error(f"Approved paper gates error: {exc}")
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

        from database import get_db

        db = get_db()

        # Fetch all closed trades (for cumulative stats)
        closed_trades = db.get_closed_trades(limit=1000)

        # Get today's date in ISO format
        today_str = datetime.utcnow().date().isoformat()

        # Fetch today's trades: WHERE status='closed' AND date(exit_time) = today
        sql = """
            SELECT symbol, side, quantity, entry_price, exit_price, pnl, exit_time
            FROM paper_trades
            WHERE status = 'closed'
            AND DATE(exit_time) = DATE(?);
        """

        with db._lock:
            conn = db._connect()
            try:
                rows = conn.execute(sql, (today_str,)).fetchall()
                today_trades = [dict(r) for r in rows]
            finally:
                conn.close()

        # Compute today's stats (guard against None pnl)
        def _pnl_today(t: dict) -> float:
            return float(t.get("pnl") or 0)

        trades_today = len(today_trades)
        pnl_today = sum(_pnl_today(t) for t in today_trades)
        wins_today = sum(1 for t in today_trades if _pnl_today(t) > 0)
        losses_today = sum(1 for t in today_trades if _pnl_today(t) < 0)

        win_rate_today = (wins_today / trades_today * 100) if trades_today > 0 else None

        # Compute avg R today (R = pnl / atr / contracts, but simplify to avg pnl per trade)
        avg_r_today = (pnl_today / trades_today) if trades_today > 0 else None

        # Compute cumulative stats (guard against None pnl from seed/legacy trades)
        def _pnl_eod(t: dict) -> float:
            return float(t.get("pnl") or 0)

        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if _pnl_eod(t) > 0)
        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        gross_profit = sum(_pnl_eod(t) for t in closed_trades if _pnl_eod(t) > 0)
        gross_loss = sum(abs(_pnl_eod(t)) for t in closed_trades if _pnl_eod(t) < 0)
        profit_factor = (
            (gross_profit / gross_loss) if gross_loss > 0 else (9999.0 if gross_profit > 0 else 0.0)
        )

        cumulative_pnl = sum(_pnl_eod(t) for t in closed_trades)

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

    symbol: str = Field(..., description="Symbol (MES, MGC)")
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

    # Compute profit factor from closed trades (guard against None pnl)
    def _p(t: dict) -> float:
        return float(t.get("pnl") or 0.0)

    gross_profit = sum(_p(t) for t in closed_trades if _p(t) > 0)
    gross_loss = sum(abs(_p(t)) for t in closed_trades if _p(t) < 0)
    current_pf = (
        (gross_profit / gross_loss) if gross_loss > 0 else (9999.0 if gross_profit > 0 else 0.0)
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

        from backtest.paper_config import (
            ACTIVE_INSTRUMENTS,
            PAPER_CONFIGS,
        )
        from database import get_db

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


class ClosedTrade(BaseModel):
    """A closed paper trade from the database."""

    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    symbol: str
    direction: str  # normalized from 'side' (buy, sell, buy_to_open, sell_to_open)
    entry_price: float
    exit_price: float
    entry_time: str
    exit_time: str
    pnl: float
    duration_seconds: int


@router.get("/trades/closed")
async def get_closed_trades():
    """Get all closed paper trades from SQLite, ordered by exit_time DESC."""
    try:
        from database.schema import get_db

        db = get_db()
        conn = db._connect()

        # Query all closed trades ordered by exit_time DESC
        try:
            rows = conn.execute(
                """
                SELECT
                    trade_id,
                    symbol,
                    side,
                    entry_price,
                    exit_price,
                    entry_time,
                    exit_time,
                    pnl
                FROM paper_trades
                WHERE status = 'closed'
                ORDER BY exit_time DESC
                """
            ).fetchall()
        finally:
            conn.close()

        from datetime import datetime

        trades: list[ClosedTrade] = []
        for row in rows:
            trade_id, symbol, side, entry_price, exit_price, entry_time, exit_time, pnl = row

            # Normalize direction from side (buy/sell/buy_to_open/sell_to_open -> LONG/SHORT)
            direction = "LONG" if side in ("buy", "buy_to_open") else "SHORT"

            # Compute duration in seconds
            try:
                entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                exit_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                duration_seconds = int((exit_dt - entry_dt).total_seconds())
            except (ValueError, AttributeError, TypeError):
                duration_seconds = 0

            trades.append(
                ClosedTrade(
                    trade_id=trade_id,
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    pnl=pnl or 0.0,
                    duration_seconds=duration_seconds,
                )
            )

        return {"status": "ok", "trades": trades}

    except Exception as exc:
        logger.error(f"Get closed trades error: {exc}")
        raise HTTPException(500, str(exc)) from exc


STARTING_CAPITAL = 10000.0


class GateResult(BaseModel):
    """Single validation gate result."""

    model_config = ConfigDict(from_attributes=True)

    status: str  # PASS | FAIL | INSUFFICIENT_DATA
    current_value: float | None
    target_value: float


class ValidationCheckpointResponse(BaseModel):
    """Validation checkpoint response."""

    model_config = ConfigDict(from_attributes=True)

    overall_status: str
    trade_count: int
    trading_days: int
    win_rate: float | None
    profit_factor: float | None
    sharpe_ratio: float | None
    max_drawdown_pct: float | None
    gates: dict[str, GateResult]
    validation_start: str | None
    days_elapsed: int
    days_remaining: int


@router.get("/checkpoint")
async def get_validation_checkpoint():
    """
    Get validation checkpoint: overall status, trade count, metrics, and gate evaluation.

    Returns ValidationCheckpointResponse with all 6 gates and overall status:
    - ACCUMULATING if < 5 trades
    - APPROVED if all gates pass
    - FAILING if any gate fails
    - ON_TRACK otherwise
    """
    try:
        from datetime import datetime

        db = get_db()

        closed_trades = db.get_closed_trades(limit=500)
        trade_count = len(closed_trades)

        # Compute trading days
        trading_days = _distinct_trade_days(closed_trades)

        # Win rate computation
        def _pnl(t: dict) -> float:
            return float(t.get("pnl") or 0.0)

        win_count = sum(1 for t in closed_trades if _pnl(t) > 0)
        win_rate = (win_count / trade_count) if trade_count > 0 else None

        # Profit factor computation
        gross_profit = sum(_pnl(t) for t in closed_trades if _pnl(t) > 0)
        gross_loss = sum(abs(_pnl(t)) for t in closed_trades if _pnl(t) < 0)
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else (None if gross_profit == 0 else 9999.0)
        )

        # Sharpe ratio from daily P&L
        sharpe_ratio = _compute_sharpe_ratio(closed_trades)

        # Max drawdown
        max_drawdown_pct = _compute_max_drawdown_pct(closed_trades)

        # Validation start time (min entry_time)
        validation_start = None
        if closed_trades:
            min_entry = min(
                t.get("entry_time") for t in closed_trades if t.get("entry_time")
            )
            if min_entry:
                validation_start = str(min_entry)
                try:
                    entry_dt = datetime.fromisoformat(
                        str(min_entry).replace("Z", "+00:00")
                    )
                    today = datetime.utcnow().date()
                    days_elapsed = (today - entry_dt.date()).days
                except (ValueError, TypeError):
                    days_elapsed = 0
            else:
                days_elapsed = 0
        else:
            days_elapsed = 0

        days_remaining = max(0, 30 - days_elapsed)

        # Gate evaluation
        cfg = PAPER_VALIDATION_GATES
        pf_target = float(cfg["profit_factor"])
        sharpe_target = float(cfg["sharpe_ratio"])
        wr_target = float(cfg["win_rate_pct"]) / 100.0
        trades_target = int(cfg["min_trades"])
        days_target = int(cfg["min_days"])
        # max_drawdown_pct is percent-scale (e.g. 12.06 == 12.06%), matching
        # _compute_max_drawdown_pct()'s return value -- do not divide by 100 here.
        # See _build_validation_gate_rows() above for the same (correct) convention.
        dd_target = float(cfg["max_drawdown_pct"])

        gates = {}

        # PF gate
        if trade_count < 5:
            gates["profit_factor"] = GateResult(
                status="INSUFFICIENT_DATA", current_value=profit_factor, target_value=pf_target
            )
        else:
            pf_passes = (profit_factor or 0.0) >= pf_target
            gates["profit_factor"] = GateResult(
                status="PASS" if pf_passes else "FAIL",
                current_value=profit_factor,
                target_value=pf_target,
            )

        # Sharpe gate
        if trade_count < 5:
            gates["sharpe_ratio"] = GateResult(
                status="INSUFFICIENT_DATA",
                current_value=sharpe_ratio,
                target_value=sharpe_target,
            )
        else:
            sharpe_passes = (sharpe_ratio or 0.0) >= sharpe_target
            gates["sharpe_ratio"] = GateResult(
                status="PASS" if sharpe_passes else "FAIL",
                current_value=sharpe_ratio,
                target_value=sharpe_target,
            )

        # Win rate gate
        if trade_count < 5:
            gates["win_rate"] = GateResult(
                status="INSUFFICIENT_DATA",
                current_value=win_rate,
                target_value=wr_target,
            )
        else:
            wr_passes = (win_rate or 0.0) >= wr_target
            gates["win_rate"] = GateResult(
                status="PASS" if wr_passes else "FAIL",
                current_value=win_rate,
                target_value=wr_target,
            )

        # Trades gate
        trades_passes = trade_count >= trades_target
        gates["trades"] = GateResult(
            status="PASS" if trades_passes else "FAIL",
            current_value=float(trade_count),
            target_value=float(trades_target),
        )

        # Days gate
        days_passes = days_elapsed >= days_target
        gates["days"] = GateResult(
            status="PASS" if days_passes else "FAIL",
            current_value=float(days_elapsed),
            target_value=float(days_target),
        )

        # Drawdown gate
        if trade_count < 5:
            gates["max_drawdown"] = GateResult(
                status="INSUFFICIENT_DATA",
                current_value=max_drawdown_pct,
                target_value=dd_target,
            )
        else:
            dd_passes = (max_drawdown_pct or 0.0) <= dd_target
            gates["max_drawdown"] = GateResult(
                status="PASS" if dd_passes else "FAIL",
                current_value=max_drawdown_pct,
                target_value=dd_target,
            )

        # Overall status determination
        if trade_count < 5:
            overall_status = "ACCUMULATING"
        else:
            # Check if all gates pass
            gate_statuses = [g.status for g in gates.values()]
            if all(s == "PASS" for s in gate_statuses):
                overall_status = "APPROVED"
            elif any(s == "FAIL" for s in gate_statuses):
                overall_status = "FAILING"
            else:
                overall_status = "ON_TRACK"

        return ValidationCheckpointResponse(
            overall_status=overall_status,
            trade_count=trade_count,
            trading_days=trading_days,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            gates=gates,
            validation_start=validation_start,
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
        )

    except Exception as exc:
        logger.error(f"Validation checkpoint error: {exc}")
        raise HTTPException(500, str(exc)) from exc
