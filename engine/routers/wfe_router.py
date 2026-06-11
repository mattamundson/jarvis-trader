"""
JARVIS TRADER — Walk-Forward Efficiency Router
================================================
US-2141: WFE live tracking — weekly snapshots.

Endpoints:
  POST /wfe/snapshot  — compute current period stats from paper_trades, write to wfe_snapshots
  GET /wfe/snapshots  — return all snapshots with divergence flag (MCL baseline=0.82, MNQ baseline=0.57)
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wfe", tags=["wfe"])

# WFE baselines for each symbol (from Sprint 21 PRD)
WFE_BASELINES = {
    "MCL": 0.82,
    "MNQ": 0.57,
}

# Divergence threshold: if live PF < (WFE_baseline * 0.5) after >= 10 trades
DIVERGENCE_MULTIPLIER = 0.5
DIVERGENCE_MIN_TRADES = 10


class WFESnapshot(BaseModel):
    """Weekly WFE snapshot response."""

    symbol: str
    week_start: str = Field(description="ISO-8601 date of week start (Monday)")
    trades: int = Field(ge=0, description="Number of closed trades in the week")
    win_rate: Optional[float] = Field(None, description="Win rate as decimal 0-1")
    profit_factor: Optional[float] = Field(None, description="Profit factor (wins / abs(losses))")
    sharpe: Optional[float] = Field(None, description="Sharpe ratio")
    max_dd: Optional[float] = Field(None, description="Max drawdown as percentage")
    wfe_baseline: Optional[float] = Field(None, description="Historical WFE baseline for symbol")
    divergence_warning: bool = Field(
        False,
        description="True if PF < (baseline * 0.5) after >= 10 trades",
    )
    created_at: str = Field(description="ISO-8601 UTC timestamp when snapshot was created")


class WFESnapshotResponse(BaseModel):
    """Response containing list of WFE snapshots."""

    snapshots: list[WFESnapshot]
    total_count: int


async def get_db_connection():
    """Dependency to get database connection."""
    db_path = settings.SQLITE_DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _get_week_start(date: Optional[datetime] = None) -> str:
    """
    Get the ISO-8601 date string of the Monday (week start) for the given date.

    Args:
        date: datetime object (default: today UTC)

    Returns:
        ISO-8601 date string (YYYY-MM-DD) of the Monday of that week
    """
    if date is None:
        date = datetime.utcnow()
    # weekday() returns 0=Monday, 6=Sunday
    monday = date - timedelta(days=date.weekday())
    return monday.strftime("%Y-%m-%d")


def _compute_snapshot_stats(symbol: str, week_start: str, conn: sqlite3.Connection) -> dict:
    """
    Compute WFE metrics for closed trades in the given week.

    Args:
        symbol: Trading symbol (e.g., 'MCL', 'MNQ')
        week_start: ISO-8601 date string of week Monday
        conn: SQLite connection

    Returns:
        dict with keys: trades, win_rate, profit_factor, sharpe, max_dd
    """
    week_end_dt = datetime.fromisoformat(week_start) + timedelta(days=6, hours=23, minutes=59)
    week_end = week_end_dt.isoformat()

    # Get all closed trades for the symbol in the week
    cursor = conn.execute(
        """
        SELECT pnl, status
        FROM paper_trades
        WHERE symbol = ?
          AND exit_time IS NOT NULL
          AND exit_time >= ?
          AND exit_time <= ?
          AND status = 'closed'
        ORDER BY exit_time ASC
        """,
        (symbol, week_start, week_end),
    )
    rows = cursor.fetchall()

    if not rows:
        return {
            "trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "sharpe": None,
            "max_dd": None,
        }

    pnls = [row["pnl"] for row in rows]
    trades_count = len(pnls)

    # Win rate
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / trades_count if trades_count > 0 else 0.0

    # Profit factor
    winning_pnl = sum(p for p in pnls if p > 0)
    losing_pnl = abs(sum(p for p in pnls if p < 0))
    profit_factor = (
        winning_pnl / losing_pnl if losing_pnl > 0 else (winning_pnl if winning_pnl > 0 else 0.0)
    )

    # Max drawdown (simple: cumulative max / current equity)
    cumulative_pnl = 0.0
    peak_equity = 0.0
    max_dd_amount = 0.0
    for p in pnls:
        cumulative_pnl += p
        peak_equity = max(peak_equity, cumulative_pnl)
        drawdown = peak_equity - cumulative_pnl
        max_dd_amount = max(max_dd_amount, drawdown)

    max_dd_pct = (
        (max_dd_amount / (settings.INITIAL_CAPITAL + peak_equity))
        if (settings.INITIAL_CAPITAL + peak_equity) > 0
        else 0.0
    )

    # Sharpe ratio (simplified: mean / std of returns)
    if len(pnls) > 1:
        import statistics

        mean_pnl = statistics.mean(pnls)
        std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0.0
        sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "trades": trades_count,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "max_dd": round(max_dd_pct, 4),
    }


@router.post("/snapshot", response_model=dict)
async def post_wfe_snapshot(
    conn: Annotated[sqlite3.Connection, Depends(get_db_connection)],
    symbol: Optional[str] = None,
):
    """
    Compute current period stats from paper_trades and write to wfe_snapshots.

    If symbol is not provided, compute for all symbols in FUTURES_WATCHLIST.

    Returns:
        dict with snapshots created
    """
    try:
        symbols = []
        if symbol:
            symbols = [symbol]
        else:
            # Snapshot the full watchlist PLUS the autonomously traded symbols.
            # Audit F-6 (2026-06-11): the old watchlist[:2] slice pinned this to
            # MCL+MNQ — both DO_NOT_TRADE — so the WFE monitor was vacuously
            # green while the actively traded symbols (MES, MGC) went untracked.
            watchlist = settings.FUTURES_WATCHLIST
            if isinstance(watchlist, str):
                watchlist = [s.strip() for s in watchlist.split(",")]
            active = os.environ.get("AUTONOMOUS_ACTIVE_SYMBOLS", "")
            active_symbols = [s.strip().upper() for s in active.split(",") if s.strip()]
            seen: set[str] = set()
            symbols = [
                s for s in list(watchlist) + active_symbols
                if not (s in seen or seen.add(s))
            ]

        week_start = _get_week_start()
        created_snapshots = []

        for sym in symbols:
            stats = _compute_snapshot_stats(sym, week_start, conn)

            # Insert into wfe_snapshots
            cursor = conn.execute(
                """
                INSERT INTO wfe_snapshots (symbol, week_start, trades, win_rate, profit_factor, sharpe, max_dd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sym,
                    week_start,
                    stats["trades"],
                    stats["win_rate"],
                    stats["profit_factor"],
                    stats["sharpe"],
                    stats["max_dd"],
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

            created_snapshots.append(
                {
                    "symbol": sym,
                    "week_start": week_start,
                    "trades": stats["trades"],
                    "snapshot_id": cursor.lastrowid,
                }
            )
            logger.info(
                f"[WFE] Snapshot created for {sym}: {stats['trades']} trades, PF={stats['profit_factor']}"
            )

        return {
            "status": "ok",
            "snapshots_created": created_snapshots,
            "week_start": week_start,
        }

    except Exception as e:
        logger.error(f"[WFE] POST /snapshot failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create WFE snapshot: {e}") from e


@router.get("/snapshots", response_model=WFESnapshotResponse)
async def get_wfe_snapshots(
    conn: Annotated[sqlite3.Connection, Depends(get_db_connection)],
    symbol: Optional[str] = None,
    limit: int = 100,
):
    """
    Get all WFE snapshots with divergence flag.

    Args:
        symbol: Optional symbol filter (e.g., 'MCL')
        limit: Max snapshots to return

    Returns:
        WFESnapshotResponse with snapshots list and divergence warnings
    """
    try:
        query = "SELECT * FROM wfe_snapshots"
        params = []

        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        snapshots = []
        for row in rows:
            sym = row["symbol"]
            baseline = WFE_BASELINES.get(sym)

            # Divergence warning logic
            divergence_warning = False
            if (
                baseline
                and row["profit_factor"] is not None
                and row["trades"] >= DIVERGENCE_MIN_TRADES
            ):
                threshold = baseline * DIVERGENCE_MULTIPLIER
                if row["profit_factor"] < threshold:
                    divergence_warning = True
                    logger.warning(
                        f"[WFE] DIVERGENCE WARNING: {sym} PF={row['profit_factor']} < threshold={threshold}"
                    )

            snapshot = WFESnapshot(
                symbol=sym,
                week_start=row["week_start"],
                trades=row["trades"],
                win_rate=row["win_rate"],
                profit_factor=row["profit_factor"],
                sharpe=row["sharpe"],
                max_dd=row["max_dd"],
                wfe_baseline=baseline,
                divergence_warning=divergence_warning,
                created_at=row["created_at"],
            )
            snapshots.append(snapshot)

        return WFESnapshotResponse(
            snapshots=snapshots,
            total_count=len(snapshots),
        )

    except Exception as e:
        logger.error(f"[WFE] GET /snapshots failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch WFE snapshots: {e}") from e


# ── Bayesian Optimizer endpoint ───────────────────────────────────────────────


class BayesianOptimizeRequest(BaseModel):
    """Request body for Bayesian optimization run."""

    symbol: str = Field(default="MCL", description="Trading symbol (e.g. MCL, MNQ)")
    interval: str = Field(default="1h", description="Bar interval (e.g. 1h, 1d)")
    start_date: str = Field(default="2024-01-01", description="Backtest start date YYYY-MM-DD")
    end_date: str = Field(default="2026-04-01", description="Backtest end date YYYY-MM-DD")
    n_calls: int = Field(default=50, ge=10, le=200, description="Number of objective evaluations")


class BayesianOptimizeResponse(BaseModel):
    """Response from Bayesian optimization run."""

    best_params: Optional[dict] = Field(None, description="Optimal parameter values found")
    best_score: float = Field(description="Best sharpe * profit_factor score achieved")
    best_metrics: Optional[dict] = Field(None, description="Full backtest metrics at best params")
    n_calls: int = Field(description="Number of evaluations performed")
    method: str = Field(description="'bayesian' | 'random_fallback' | 'none'")
    error: Optional[str] = Field(None, description="Error message if optimization failed")


@router.post("/optimize-bayesian", response_model=BayesianOptimizeResponse)
async def post_optimize_bayesian(body: BayesianOptimizeRequest):
    """
    Run Bayesian parameter optimization for a symbol.

    Uses Gaussian Process surrogate (scikit-optimize) when available; falls
    back to random search otherwise. Evaluates at most n_calls backtests —
    3x fewer than a full 162-combination grid search.

    Returns the best (stc_os, stc_ob, stop_mult, t1_mult) combination
    and associated backtest metrics.
    """
    try:
        from backtest.bayesian_optimizer import BayesianOptimizer

        opt = BayesianOptimizer(
            symbol=body.symbol,
            interval=body.interval,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        result = await opt.optimize(n_calls=body.n_calls)

        logger.info(
            "[WFE] Bayesian optimize complete: symbol=%s method=%s score=%.4f",
            body.symbol,
            result.get("method"),
            result.get("best_score", 0.0),
        )

        return BayesianOptimizeResponse(**result)

    except Exception as e:
        logger.error("[WFE] POST /optimize-bayesian failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Bayesian optimization failed: {e}"
        ) from e
