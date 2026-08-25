"""
Analytics Router — exposes trade_analytics and signal_quality endpoints.

Endpoints:
  GET /analytics/trades — calculate_analytics() from paper trades
  GET /analytics/signal-quality — analyze_signal_quality() with optional filters
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from database.schema import DatabaseManager
from middleware.rate_limit import get_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Get limiter instance for rate limiting
limiter = get_limiter()

# ---------------------------------------------------------------------------
# Module-level db_manager reference — injected at startup
# ---------------------------------------------------------------------------

_db: Optional[DatabaseManager] = None
_data_mgr = None  # MarketDataManager, injected at startup


def set_db_manager(db: DatabaseManager) -> None:
    """Inject the application-level DatabaseManager into this router."""
    global _db
    _db = db


def set_data_manager(dm) -> None:
    """Inject the application-level MarketDataManager into this router."""
    global _data_mgr
    _data_mgr = dm


def _get_db() -> DatabaseManager:
    """Return the injected DatabaseManager or raise 503 if not yet set."""
    if _db is None:
        raise HTTPException(
            status_code=503,
            detail="Database manager not initialised.",
        )
    return _db


def _compute_days_from_trades(trades: list[dict]) -> int:
    """
    Compute the calendar-day span of a trade list using exit_time or entry_time.
    Returns (max_date - min_date).days + 1, or 0 when no parseable timestamps exist.
    """
    parsed = []
    for trade in trades:
        raw = trade.get("exit_time") or trade.get("entry_time")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.debug("Could not parse trade timestamp: %s", raw)
            continue
        # Normalize to tz-aware UTC. The DB holds a mix of tz-naive timestamps
        # (older rows, "...T10:00:00") and tz-aware ones ("...+00:00"/"Z");
        # max()/min() over a mixed list raises "can't compare offset-naive and
        # offset-aware datetimes" — the bug that 503'd GET /analytics/performance.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        parsed.append(dt)
    if not parsed:
        return 0
    return (max(parsed) - min(parsed)).days + 1


class PerformanceMetricsResponse(BaseModel):
    """Performance metrics response with timestamp."""

    model_config = ConfigDict(from_attributes=True)

    status: str = "ok"
    sharpe_ratio: float
    profit_factor: float
    win_rate: float
    max_drawdown: float
    total_pnl: float
    total_trades: int
    expectancy: float
    timestamp: str
    days: Optional[int] = None  # rolling window length when applicable
    # C3 metric-honesty pass (2026-08-18): annualization transparency. The
    # sharpe_ratio above is annualized by this observed factor (252 fallback),
    # and cagr is the honest CAGR over the actual window.
    annualization_trades_per_year: Optional[float] = None
    cagr: Optional[float] = None


class TradeAnalyticsResponse(BaseModel):
    """Trade analytics response."""

    model_config = ConfigDict(from_attributes=True)

    sharpe_ratio: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    expectancy: float
    total_trades: int
    total_pnl: float
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float
    # C3 metric-honesty pass (2026-08-18): annualization transparency.
    annualization_trades_per_year: Optional[float] = None
    cagr: Optional[float] = None


class SignalMetricsResponse(BaseModel):
    """Signal metrics for a filtered set of trades."""

    model_config = ConfigDict(from_attributes=True)

    total_signals: int
    profitable_signals: int
    accuracy: float
    avg_signal_to_entry_minutes: float
    avg_entry_to_peak_minutes: float
    avg_pnl_per_signal: float
    best_time_of_day: str
    worst_time_of_day: str


class SignalQualityResponse(BaseModel):
    """Complete signal quality report."""

    model_config = ConfigDict(from_attributes=True)

    overall: SignalMetricsResponse
    by_symbol: dict[str, SignalMetricsResponse]
    by_regime: dict[str, SignalMetricsResponse]
    recommendations: list[str]


class TradesByDayItem(BaseModel):
    """Trade breakdown by date."""

    model_config = ConfigDict(from_attributes=True)

    date: str
    trades: int
    pnl: float
    win_rate: float


class TradesBySymbolItem(BaseModel):
    """Trade breakdown by symbol."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    trades: int
    pnl: float
    win_rate: float
    avg_pnl: float


class TradesByHourItem(BaseModel):
    """Trade breakdown by hour of day."""

    model_config = ConfigDict(from_attributes=True)

    hour: int
    trades: int
    pnl: float
    win_rate: float


def _get_all_trades() -> list[dict]:
    """
    Retrieve all closed trades — SQLite is the single source of truth.

    When the injected DatabaseManager is available, queries ``paper_trades``
    directly (Bug B9 / US-2504).  Falls back to ValidationTracker (JSON) only
    when the DB has not been initialised, so the endpoint stays functional
    during early startup or in test environments that do not wire a DB.
    """
    if _db is not None:
        try:
            rows = _db.get_closed_trades(limit=10000)
            # Normalise field names expected by analytics helpers.
            # ValidationTracker uses "instrument" + "timestamp"; SQLite uses
            # "symbol" + "exit_time".  We expose both so downstream code works
            # regardless of which key it checks.
            normalised: list[dict] = []
            for row in rows:
                trade = dict(row) if hasattr(row, "keys") else row
                trade.setdefault("instrument", trade.get("symbol", ""))
                trade.setdefault("timestamp", trade.get("exit_time") or trade.get("entry_time", ""))
                pnl = trade.get("pnl")
                trade["pnl"] = float(pnl) if pnl is not None else 0.0
                normalised.append(trade)
            return normalised
        except Exception as exc:
            logger.error(
                "_get_all_trades: SQLite query failed, falling back to ValidationTracker: %s", exc
            )

    # Fallback — ValidationTracker reads stale JSON; only used when no DB is wired
    try:
        from paper.validation_tracker import ValidationTracker

        data_dir = Path(os.environ.get("DATA_DIR", "data"))
        tracker = ValidationTracker(data_dir=data_dir)
        all_trades = []
        for instrument in ["MCL", "MNQ"]:
            all_trades.extend(tracker.get_all_trades(instrument))
        return all_trades
    except Exception as exc:
        logger.error("_get_all_trades: ValidationTracker fallback also failed: %s", exc)
        return []


def _metrics_to_response(metrics) -> SignalMetricsResponse:
    """Convert SignalMetrics to response model."""
    return SignalMetricsResponse(
        total_signals=metrics.total_signals,
        profitable_signals=metrics.profitable_signals,
        accuracy=metrics.accuracy,
        avg_signal_to_entry_minutes=metrics.avg_signal_to_entry_minutes,
        avg_entry_to_peak_minutes=metrics.avg_entry_to_peak_minutes,
        avg_pnl_per_signal=metrics.avg_pnl_per_signal,
        best_time_of_day=metrics.best_time_of_day,
        worst_time_of_day=metrics.worst_time_of_day,
    )


@router.get(
    "/trades",
    response_model=TradeAnalyticsResponse,
    description="Calculate and return trade analytics across all closed paper trades with Sharpe, profit factor, win rate, and drawdown metrics.",
)
@limiter.limit("120/minute")
async def get_trade_analytics(request: Request) -> TradeAnalyticsResponse:
    """
    Calculate and return trade analytics across all paper trades.

    Returns TradeAnalytics JSON with performance metrics.
    """
    try:
        from analytics.trade_analytics import calculate_analytics

        trades = _get_all_trades()
        analytics = calculate_analytics(trades)

        return TradeAnalyticsResponse(
            sharpe_ratio=analytics.sharpe_ratio,
            profit_factor=analytics.profit_factor,
            max_drawdown_pct=analytics.max_drawdown_pct,
            win_rate=analytics.win_rate,
            expectancy=analytics.expectancy,
            total_trades=analytics.total_trades,
            total_pnl=analytics.total_pnl,
            avg_win=analytics.avg_win,
            avg_loss=analytics.avg_loss,
            best_trade=analytics.best_trade,
            worst_trade=analytics.worst_trade,
            annualization_trades_per_year=analytics.annualization_trades_per_year,
            cagr=analytics.cagr,
        )
    except Exception as exc:
        logger.error(f"Trade analytics error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get(
    "/pnl-reconciliation",
    description="Recompute realized P&L from closed paper_trades and flag any "
    "date where the stored daily_pnl snapshot disagrees (phantom-P&L detector).",
)
@limiter.limit("60/minute")
async def get_pnl_reconciliation(request: Request, epsilon: float = 0.01) -> dict:
    """Detective control for the phantom-P&L class (2026-06-15).

    Independently re-derives per-date realized P&L from the source of truth
    (``SUM(pnl)`` over ``status='closed'`` paper_trades) and compares it to the
    stored ``daily_pnl.realized_pnl``. ``ok=false`` with a non-empty ``drifts``
    list means a stored figure has drifted from the trades that back it — the
    exact signature of a phantom or mis-written P&L row.
    """
    db = _get_db()
    try:
        report = db.reconcile_daily_pnl(epsilon=float(epsilon))
    except Exception as exc:
        logger.error(f"P&L reconciliation error: {exc}")
        raise HTTPException(500, str(exc)) from exc
    if not report.get("ok"):
        logger.warning(
            "[pnl_reconciliation] %d date(s) drifted from paper_trades: %s",
            report.get("drift_count"),
            [d["date"] for d in report.get("drifts", [])],
        )
    return report


@router.get(
    "/signal-quality",
    response_model=SignalQualityResponse,
    description="Analyze signal quality metrics across filtered trades with optional symbol and date range filters.",
)
@limiter.limit("120/minute")
async def get_signal_quality(
    request: Request,
    symbol: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> SignalQualityResponse:
    """
    Analyze signal quality across trades with optional filters.

    Query parameters:
      - symbol: Filter by symbol (MCL, MNQ, etc)
      - start_date: Filter trades >= start_date (ISO format or YYYY-MM-DD)
      - end_date: Filter trades <= end_date (ISO format or YYYY-MM-DD)

    Returns SignalQualityReport with metrics and recommendations.
    """
    try:
        from analytics.signal_quality import analyze_signal_quality

        trades = _get_all_trades()

        # Apply filters
        if symbol:
            trades = [
                t for t in trades if t.get("instrument") == symbol or t.get("symbol") == symbol
            ]

        if start_date:
            try:
                start = datetime.fromisoformat(start_date).date()
                trades = [
                    t for t in trades if (t.get("timestamp") or "").split("T")[0] >= str(start)
                ]
            except ValueError:
                logger.warning(f"Invalid start_date: {start_date}")

        if end_date:
            try:
                end = datetime.fromisoformat(end_date).date()
                trades = [t for t in trades if (t.get("timestamp") or "").split("T")[0] <= str(end)]
            except ValueError:
                logger.warning(f"Invalid end_date: {end_date}")

        report = analyze_signal_quality(trades)

        return SignalQualityResponse(
            overall=_metrics_to_response(report.overall),
            by_symbol={sym: _metrics_to_response(m) for sym, m in report.by_symbol.items()},
            by_regime={regime: _metrics_to_response(m) for regime, m in report.by_regime.items()},
            recommendations=report.recommendations,
        )
    except Exception as exc:
        logger.error(f"Signal quality error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get(
    "/performance",
    response_model=PerformanceMetricsResponse,
    description="Return overall performance metrics across all closed paper trades with Sharpe ratio, profit factor, win rate, and expectancy.",
)
@limiter.limit("120/minute")
async def get_performance(request: Request) -> PerformanceMetricsResponse:
    """
    Return overall performance metrics across all closed paper trades.

    Returns PerformanceMetrics with sharpe_ratio, profit_factor, win_rate,
    max_drawdown, total_pnl, total_trades, expectancy, and calculation timestamp.

    Returns 503 if database is not ready, 500 on query failure.
    """
    try:
        from analytics.trade_analytics import calculate_analytics

        db = _get_db()
        closed_trades = db.get_closed_trades(limit=10000)

        # Convert db rows to analytics format (ensure pnl is present)
        trades_for_analytics = []
        for trade in closed_trades:
            trade_dict = dict(trade) if hasattr(trade, "keys") else trade
            pnl = trade_dict.get("pnl")
            if pnl is not None:
                pnl = float(pnl)
            else:
                pnl = 0.0
            trade_dict["pnl"] = pnl
            trades_for_analytics.append(trade_dict)

        analytics = calculate_analytics(trades_for_analytics)

        # Compute days from the actual trade date range
        days_computed: int = _compute_days_from_trades(trades_for_analytics)

        return PerformanceMetricsResponse(
            status="ok",
            sharpe_ratio=analytics.sharpe_ratio,
            profit_factor=analytics.profit_factor,
            win_rate=analytics.win_rate,
            max_drawdown=analytics.max_drawdown_pct,
            total_pnl=analytics.total_pnl,
            total_trades=analytics.total_trades,
            expectancy=analytics.expectancy,
            timestamp=datetime.utcnow().isoformat() + "Z",
            days=days_computed,
        )
    except RuntimeError:
        logger.warning("Database not yet initialised")
        raise HTTPException(503, "Database not ready") from None
    except Exception as exc:
        logger.error(f"Performance calculation error: {exc}")
        raise HTTPException(503, str(exc)) from exc


@router.get(
    "/performance/rolling",
    response_model=PerformanceMetricsResponse,
    description="Return rolling performance metrics over the last N days (default 7) with windowed Sharpe, profit factor, and win rate.",
)
@limiter.limit("120/minute")
async def get_rolling_performance(request: Request, days: int = 7) -> PerformanceMetricsResponse:
    """
    Return rolling performance metrics over the last N days (default 7).

    Query parameters:
      - days: Number of past days to include (default 7, must be >= 1)

    Returns PerformanceMetrics with sharpe_ratio, profit_factor, win_rate,
    max_drawdown, total_pnl, total_trades, expectancy for the rolling window,
    and calculation timestamp.

    Returns 503 if database is not ready, 500 on query failure.
    """
    try:
        from analytics.trade_analytics import calculate_analytics

        if days < 1:
            raise HTTPException(400, "days must be >= 1")

        db = _get_db()
        closed_trades = db.get_closed_trades(limit=10000)

        # Filter to only trades from the last N days
        from datetime import timedelta

        cutoff_date = datetime.utcnow() - timedelta(days=days)
        cutoff_iso = cutoff_date.isoformat()

        filtered_trades = []
        for trade in closed_trades:
            trade_dict = dict(trade) if hasattr(trade, "keys") else trade
            exit_time = trade_dict.get("exit_time", "")
            # Compare ISO timestamps
            if exit_time >= cutoff_iso:
                pnl = trade_dict.get("pnl")
                if pnl is not None:
                    pnl = float(pnl)
                else:
                    pnl = 0.0
                trade_dict["pnl"] = pnl
                filtered_trades.append(trade_dict)

        analytics = calculate_analytics(filtered_trades)

        return PerformanceMetricsResponse(
            status="ok",
            sharpe_ratio=analytics.sharpe_ratio,
            profit_factor=analytics.profit_factor,
            win_rate=analytics.win_rate,
            max_drawdown=analytics.max_drawdown_pct,
            total_pnl=analytics.total_pnl,
            total_trades=analytics.total_trades,
            expectancy=analytics.expectancy,
            timestamp=datetime.utcnow().isoformat() + "Z",
            days=days,
        )
    except RuntimeError:
        logger.warning("Database not yet initialised")
        raise HTTPException(503, "Database not ready") from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Rolling performance calculation error: {exc}")
        raise HTTPException(503, str(exc)) from exc


@router.get(
    "/performance/compare",
    response_model=None,
    description="Compare forward-test paper metrics to reference backtest targets.",
)
@limiter.limit("60/minute")
async def get_performance_compare(request: Request) -> dict:
    """
    Forward metrics from SQLite vs reference backtest; returns ``degradation_ok``
    when forward PF/Sharpe still exceed paper thresholds.
    """
    try:
        db = _get_db()
        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(db)
        return calc.compare_to_backtest()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[Analytics] compare_to_backtest failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}") from exc


@router.get(
    "/forward-test",
    response_model=None,
    description=(
        "Forward-test status for the pre-registered candidate set: per-candidate "
        "out-of-sample windows, family-FDR survival, and graduation verdict "
        "(read-only; never mutates execution or scheduler state)."
    ),
)
@limiter.limit("60/minute")
async def get_forward_test(request: Request) -> dict:
    """Read-only forward-test loop result for the cockpit / dashboard.

    Surfaces ``run_forward_test`` over the locked candidate registry so the
    north-star liveness pane can show whether any held candidate is graduating
    on its forward (paper) record. ``persist=False`` -- this endpoint only reads
    closed trades; it writes nothing.
    """
    try:
        db = _get_db()
    except HTTPException:
        return {
            "status": "INSUFFICIENT_DATA",
            "recommendation": "Database not initialized.",
            "n_active_candidates": 0,
            "n_graduated": 0,
            "candidates": [],
        }

    try:
        from backtest.forward_test import run_forward_test

        return run_forward_test(db=db, persist=False)
    except Exception as exc:
        logger.error(f"[Analytics] forward_test failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}") from exc


@router.get(
    "/validation-report",
    response_model=None,
    description=(
        "Paper-phase validation report: PASS / FAIL / INSUFFICIENT_DATA with metrics, "
        "thresholds, and recommendation (PerformanceCalculator.get_validation_report)."
    ),
)
@limiter.limit("60/minute")
async def get_validation_report_endpoint(request: Request) -> dict:
    """Structured validation gate for the dashboard validation page."""
    try:
        db = _get_db()
    except HTTPException:
        return {
            "status": "INSUFFICIENT_DATA",
            "metrics": {},
            "thresholds": {
                "profit_factor": 2.0,
                "sharpe_ratio": 1.5,
                "min_trades_required": 10,
            },
            "recommendation": "Database not initialized.",
        }

    try:
        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(db)
        return calc.get_validation_report()
    except Exception as exc:
        logger.error(f"[Analytics] get_validation_report failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}") from exc


@router.get(
    "/trades/by-day",
    description="Get trade breakdown by date with daily PnL and win rate aggregation. Defaults to 30 days; use ?days=91 for 13-week calendar view.",
    response_model=None,
)
@limiter.limit("120/minute")
async def get_trades_by_day(request: Request, days: int = 30) -> dict:
    """
    Get trade breakdown by date.

    Args:
        days: lookback window in calendar days (default 30, max 365).

    Returns array of {date, trades, pnl, win_rate} grouped by day.
    """
    lookback = max(1, min(days, 365))
    try:
        db = _get_db()
        sql = f"""
            SELECT
                DATE(exit_time) as date,
                COUNT(*) as trades,
                COALESCE(SUM(pnl), 0.0) as pnl,
                ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as win_rate
            FROM paper_trades
            WHERE status = 'closed'
              AND exit_time >= datetime('now', '-{lookback} days')
            GROUP BY DATE(exit_time)
            ORDER BY date DESC
        """
        with db._lock:
            conn = db._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()

        result = []
        for row in rows:
            result.append(
                {
                    "date": row["date"],
                    "trades": int(row["trades"]),
                    "pnl": float(row["pnl"]),
                    "win_rate": float(row["win_rate"]) if row["win_rate"] else 0.0,
                }
            )
        return {"days": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Trades by day error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get(
    "/bar-quality",
    response_model=None,
    description=(
        "Bar-quality gate rejection activity — how many contaminated bars the "
        "write-time gate refused, grouped by reason / symbol / path. "
        "total_rejections=0 with gate_active=true is the healthy steady state "
        "(the gate is wired and the data is clean), not an error."
    ),
)
@limiter.limit("120/minute")
async def get_bar_quality(request: Request, hours: int = 168) -> dict:
    """
    Rejection activity from the write-time bar-quality gate (migration 039).

    Args:
        hours: lookback window in hours (default 168 = 7 days, max 720 = 30 days).

    A missing table (DB predating the migration) or empty result returns
    total_rejections=0 / gate_active=true — the honest "clean data" state.
    """
    window = max(1, min(hours, 720))
    empty: dict = {
        "window_hours": window,
        "total_rejections": 0,
        "by_reason": [],
        "by_symbol": [],
        "by_path": {"sanity": 0, "gate": 0},
        "recent": [],
        "gate_active": True,
    }
    try:
        db = _get_db()
        since = (datetime.now(timezone.utc) - timedelta(hours=window)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        with db._lock:
            conn = db._connect()
            try:
                rows = conn.execute(
                    "SELECT ts_utc, symbol, interval, source, path, reason, detail, count "
                    "FROM bar_quality_rejections WHERE ts_utc >= ? ORDER BY ts_utc DESC",
                    (since,),
                ).fetchall()
            finally:
                conn.close()
    except HTTPException:
        raise
    except Exception as exc:  # table missing (pre-migration) or read error
        logger.debug("bar-quality read skipped: %s", exc)
        return empty

    by_reason: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    by_path = {"sanity": 0, "gate": 0}
    total = 0
    recent: list[dict] = []
    for r in rows:
        cnt = int(r["count"])
        total += cnt
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + cnt
        by_symbol[r["symbol"]] = by_symbol.get(r["symbol"], 0) + cnt
        if r["path"] in by_path:
            by_path[r["path"]] += cnt
        if len(recent) < 25:
            recent.append(
                {
                    "ts_utc": r["ts_utc"],
                    "symbol": r["symbol"],
                    "interval": r["interval"],
                    "source": r["source"],
                    "path": r["path"],
                    "reason": r["reason"],
                    "detail": r["detail"],
                    "count": cnt,
                }
            )
    return {
        "window_hours": window,
        "total_rejections": total,
        "by_reason": sorted(
            [{"reason": k, "count": v} for k, v in by_reason.items()],
            key=lambda x: x["count"],
            reverse=True,
        ),
        "by_symbol": sorted(
            [{"symbol": k, "count": v} for k, v in by_symbol.items()],
            key=lambda x: x["count"],
            reverse=True,
        ),
        "by_path": by_path,
        "recent": recent,
        "gate_active": True,
    }


@router.get(
    "/trades/by-symbol",
    response_model=None,
    description="Get trade breakdown by symbol across all closed trades with aggregate PnL, win rate, and average per-trade metrics.",
)
@limiter.limit("120/minute")
async def get_trades_by_symbol(request: Request) -> dict:
    """
    Get trade breakdown by symbol across all closed trades.

    Returns array of {symbol, trades, pnl, win_rate, avg_pnl}.
    """
    try:
        db = _get_db()
        sql = """
            SELECT
                symbol,
                COUNT(*) as trades,
                COALESCE(SUM(pnl), 0.0) as pnl,
                ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as win_rate,
                ROUND(AVG(pnl), 4) as avg_pnl
            FROM paper_trades
            WHERE status = 'closed'
            GROUP BY symbol
            ORDER BY trades DESC
        """
        with db._lock:
            conn = db._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()

        result = []
        for row in rows:
            result.append(
                {
                    "symbol": row["symbol"],
                    "trades": int(row["trades"]),
                    "pnl": float(row["pnl"]),
                    "win_rate": float(row["win_rate"]) if row["win_rate"] else 0.0,
                    "avg_pnl": float(row["avg_pnl"]),
                }
            )
        return {"symbols": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Trades by symbol error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get(
    "/trades/by-hour",
    response_model=None,
    description="Get trade breakdown by hour of day (0-23 UTC) with hourly PnL and win rate for time-of-day analysis.",
)
@limiter.limit("120/minute")
async def get_trades_by_hour(request: Request) -> dict:
    """
    Get trade breakdown by hour of day (0-23 UTC).

    Returns array of {hour, trades, pnl, win_rate} grouped by hour.
    """
    try:
        db = _get_db()
        sql = """
            SELECT
                CAST(STRFTIME('%H', exit_time) AS INTEGER) as hour,
                COUNT(*) as trades,
                COALESCE(SUM(pnl), 0.0) as pnl,
                ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as win_rate
            FROM paper_trades
            WHERE status = 'closed' AND exit_time IS NOT NULL
            GROUP BY hour
            ORDER BY hour ASC
        """
        rows = db.execute(sql).fetchall()
        return {
            "hours": [{"hour": r[0], "trades": r[1], "pnl": r[2], "win_rate": r[3]} for r in rows]
        }
    except Exception:
        return {"hours": []}


# ---------------------------------------------------------------------------
# Dual-Timeframe STC Status
# ---------------------------------------------------------------------------


@router.get(
    "/dual-tf-status",
    response_model=None,
    description=(
        "Return 1h and 15m STC values plus dual-timeframe confirmation status "
        "for each requested symbol. Confirmed=true when both timeframes agree on "
        "direction (both LONG or both SHORT)."
    ),
)
@limiter.limit("60/minute")
async def get_dual_tf_status(
    request: Request,
    symbols: str = "MCL,MNQ,MES",
) -> dict:
    """
    Fetch latest 1h and 15m STC values for each symbol and determine
    dual-timeframe confirmation status.

    Query parameters:
      - symbols: Comma-separated list of symbols (default: MCL,MNQ,MES)

    Returns per-symbol STC values, signal directions, and a confirmed flag.
    """
    from backtest.signals import INSTRUMENT_PARAMS, generate_instrument_signals

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(400, "symbols must not be empty")

    results = []
    dm = _data_mgr

    for sym in symbol_list:
        params = INSTRUMENT_PARAMS.get(sym, (15, 83, 0.70, 1.00, 1.618, 2.618, True))
        stc_os, stc_ob = int(params[0]), int(params[1])

        row: dict = {
            "symbol": sym,
            "stc_os": stc_os,
            "stc_ob": stc_ob,
            "tf_1h": None,
            "tf_15m": None,
            "confirmed": False,
            "direction": "neutral",
            "error": None,
        }

        if dm is None:
            row["error"] = "data_manager not available"
            results.append(row)
            continue

        try:
            tf_data: dict = {}
            for tf in ("1h", "15m"):
                try:
                    df = await dm.get_bars(sym, lookback_days=5, timeframe=tf, is_futures=True)
                    if df is None or df.empty or len(df) < 20:
                        tf_data[tf] = None
                        continue
                    sig_df = generate_instrument_signals(df.copy(), sym)
                    if "stc_val" not in sig_df.columns:
                        tf_data[tf] = None
                        continue
                    last = sig_df.iloc[-1]
                    stc_val = float(last["stc_val"])
                    signal_raw = str(last.get("signal", "hold")).lower()
                    # Map composite signal → direction label
                    if signal_raw in ("long", "entry_now", "buy"):
                        direction = "long"
                    elif signal_raw in ("short", "sell"):
                        direction = "short"
                    else:
                        direction = "neutral"
                    tf_data[tf] = {
                        "stc_val": round(stc_val, 2),
                        "direction": direction,
                        "signal": signal_raw,
                    }
                except Exception as tf_exc:
                    logger.debug(f"[DualTF] {sym} {tf} error: {tf_exc}")
                    tf_data[tf] = None

            row["tf_1h"] = tf_data.get("1h")
            row["tf_15m"] = tf_data.get("15m")

            d1h = (tf_data.get("1h") or {}).get("direction", "neutral")
            d15m = (tf_data.get("15m") or {}).get("direction", "neutral")
            if d1h != "neutral" and d1h == d15m:
                row["confirmed"] = True
                row["direction"] = d1h
            elif d1h != "neutral":
                row["direction"] = d1h
            elif d15m != "neutral":
                row["direction"] = d15m

        except Exception as exc:
            logger.error(f"[DualTF] {sym} failed: {exc}")
            row["error"] = str(exc)

        results.append(row)

    return {
        "symbols": results,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /analytics/pipeline/confidence-stats (US-2131)
# ─────────────────────────────────────────────────────────────────────────────


class PipelineConfidenceStatsResponse(BaseModel):
    """Pipeline confidence statistics response."""

    model_config = ConfigDict(from_attributes=True)

    total_runs: int
    hold_count: int
    trade_count: int
    avg_confidence: float
    min_confidence: float
    max_confidence: float
    hold_rate: float
    alert: Optional[str] = None
    timestamp: str


@router.get(
    "/pipeline/confidence-stats",
    response_model=PipelineConfidenceStatsResponse,
    summary="Get pipeline confidence statistics for last 24 hours",
)
async def get_pipeline_confidence_stats() -> PipelineConfidenceStatsResponse:
    """
    Get pipeline execution statistics for the last 24 hours.

    Returns:
      - total_runs: Total pipeline executions
      - hold_count: Number of HOLD decisions
      - trade_count: Number of BUY/SELL decisions
      - avg_confidence: Average confidence across all runs (0-1)
      - min_confidence: Minimum confidence observed
      - max_confidence: Maximum confidence observed
      - hold_rate: hold_count / total_runs (0.0 to 1.0)
      - alert: If hold_rate > 0.90 and total_runs >= 5, 'HIGH_HOLD_RATE'

    Flags regressions like the MAX_TOKENS bug (115 HOLDs/day) with high hold rates.
    """
    from datetime import datetime as dt
    from datetime import timedelta

    db = _get_db()

    try:
        with db._lock:  # type: ignore[attr-defined]
            conn = db._connect()  # type: ignore[attr-defined]
            try:
                # Calculate 24 hours ago
                now = dt.utcnow()
                twenty_four_hours_ago = now - timedelta(hours=24)
                cutoff_iso = twenty_four_hours_ago.isoformat() + "Z"

                # Query pipeline_runs for last 24h with confidence statistics
                sql = """
                    SELECT
                        COUNT(*) AS total_runs,
                        SUM(CASE WHEN final_decision = 'hold' OR final_action = 'hold' THEN 1 ELSE 0 END) AS hold_count,
                        SUM(CASE WHEN final_decision IN ('buy', 'sell') OR final_action IN ('buy', 'sell') THEN 1 ELSE 0 END) AS trade_count,
                        COALESCE(AVG(confidence), 0.5) AS avg_confidence,
                        COALESCE(MIN(confidence), 0.5) AS min_confidence,
                        COALESCE(MAX(confidence), 0.5) AS max_confidence
                    FROM pipeline_runs
                    WHERE created_at >= ?
                      AND status = 'completed'
                """

                row = conn.execute(sql, (cutoff_iso,)).fetchone()

                total_runs = int(row[0]) if row and row[0] else 0
                hold_count = int(row[1]) if row and row[1] else 0
                trade_count = int(row[2]) if row and row[2] else 0
                avg_confidence = float(row[3]) if row and row[3] is not None else 0.5
                min_confidence = float(row[4]) if row and row[4] is not None else 0.5
                max_confidence = float(row[5]) if row and row[5] is not None else 0.5

                # Calculate hold_rate
                hold_rate = hold_count / total_runs if total_runs > 0 else 0.0

                # Check for high hold rate alert
                alert = None
                if hold_rate > 0.90 and total_runs >= 5:
                    alert = "HIGH_HOLD_RATE"

                conn.close()

                return PipelineConfidenceStatsResponse(
                    total_runs=total_runs,
                    hold_count=hold_count,
                    trade_count=trade_count,
                    avg_confidence=round(avg_confidence, 4),
                    min_confidence=round(min_confidence, 4),
                    max_confidence=round(max_confidence, 4),
                    hold_rate=round(hold_rate, 4),
                    alert=alert,
                    timestamp=now.isoformat() + "Z",
                )

            finally:
                conn.close()

    except Exception as exc:
        logger.error(f"[PipelineConfidenceStats] Error: {exc}")
        raise HTTPException(status_code=500, detail=f"Pipeline stats error: {exc}") from exc


# ─── Brier / IC calibration diagnostics (Novel #2 observability) ─────────────


class CalibrationAgentEntry(BaseModel):
    """Per-agent calibration state."""

    model_config = ConfigDict(from_attributes=True)

    brier_score: float  # Mean Brier over window; lower is better
    brier_weight: float  # Normalized inverse-Brier weight (sums to 1.0)
    ic_score: float  # Spearman IC over window
    sample_count: int  # Non-zero-signal trade count in window
    ready: bool  # True when sample_count >= min_trades


class CalibrationDiagnosticsResponse(BaseModel):
    """Full calibration snapshot — Brier + IC across all tracked analysts."""

    model_config = ConfigDict(from_attributes=True)

    brier_enabled: bool  # Reflects BRIER_CALIBRATION_ENABLED env var
    brier_blend_alpha: float  # Current blend alpha (debate.BRIER_BLEND_ALPHA)
    min_trades_threshold: int  # Minimum sample size before calibration activates
    window_days: int  # Rolling window length
    agents: list[str]  # Tracked analyst names
    per_agent: dict[str, CalibrationAgentEntry]
    total_outcomes: int  # Total rows in trade_outcomes within window
    ready_to_activate: bool  # True when every signal-emitting agent meets the floor
    active_agents: list[str]  # agents with >=1 non-zero-signal outcome in window
    blocked_by: list[str]  # active agents still below min_trades_threshold
    rows_excluded_corrupt: int  # window rows dropped by the magnitude guard
    rows_excluded_duplicate: int  # window rows dropped as logical duplicates
    neutral_sentinel: float  # Brier value returned when insufficient data
    timestamp: str


@router.get(
    "/calibration",
    response_model=CalibrationDiagnosticsResponse,
    description=(
        "Expose per-agent Brier + IC calibration diagnostics. Useful for deciding "
        "when to flip BRIER_CALIBRATION_ENABLED=true — activate once every agent "
        "has sample_count >= min_trades_threshold."
    ),
)
async def get_calibration_diagnostics() -> CalibrationDiagnosticsResponse:
    """Return the current state of the Brier/IC calibration pipeline.

    Reads from the shared ``trade_outcomes`` table via BrierCalibrationTracker
    and ICWeightedEnsemble. Both trackers degrade gracefully when the table
    is missing or empty — the endpoint never returns 500 on cold-start.
    """
    import sqlite3 as _sqlite

    try:
        # Pull live blend alpha from debate module so the endpoint tracks the
        # constant if it's ever tuned per-regime.
        from agents.debate import BRIER_BLEND_ALPHA, _is_brier_enabled
        from analytics.agent_feedback import AGENT_NAMES
        from analytics.agent_feedback import DB_PATH as FB_DB_PATH
        from analytics.ic_ensemble import (
            BRIER_NEUTRAL,
            DEFAULT_WINDOW_DAYS,
            MIN_TRADES_FOR_IC,
            BrierCalibrationTracker,
            ICWeightedEnsemble,
        )
    except Exception as exc:
        logger.error("[Calibration] import failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"calibration deps unavailable: {exc}") from exc

    agents = list(AGENT_NAMES)
    brier = BrierCalibrationTracker(agents=agents)
    ic = ICWeightedEnsemble(agents=agents)

    # Brier scores + normalized weights (single DB pass per agent per tracker)
    try:
        brier_scores = {a: brier.compute_brier(a) for a in agents}
        brier_weights = brier.get_calibration_weights(agents)
    except Exception as exc:
        logger.warning("[Calibration] Brier compute failed: %s", exc)
        brier_scores = dict.fromkeys(agents, BRIER_NEUTRAL)
        brier_weights = {a: 1.0 / len(agents) for a in agents}

    try:
        ic_scores = {a: ic.compute_ic(a) for a in agents}
    except Exception as exc:
        logger.warning("[Calibration] IC compute failed: %s", exc)
        ic_scores = dict.fromkeys(agents, 0.0)

    # Per-agent sample count — direct SQL so it stays cheap.
    sample_counts: dict[str, int] = dict.fromkeys(agents, 0)
    total_outcomes = 0
    rows_excluded_corrupt = 0
    rows_excluded_duplicate = 0
    try:
        if FB_DB_PATH.exists():
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            from datetime import timezone as _tz

            cutoff = (_dt.now(_tz.utc) - _td(days=DEFAULT_WINDOW_DAYS)).isoformat()
            with _sqlite.connect(str(FB_DB_PATH)) as conn:
                total_outcomes = (
                    conn.execute(
                        "SELECT COUNT(*) FROM trade_outcomes WHERE timestamp >= ?",
                        (cutoff,),
                    ).fetchone()[0]
                    or 0
                )
                for a in agents:
                    sig_col = f"{a}_signal"
                    try:
                        n = (
                            conn.execute(
                                f"SELECT COUNT(*) FROM trade_outcomes "
                                f"WHERE timestamp >= ? AND {sig_col} IS NOT NULL AND {sig_col} != 0",
                                (cutoff,),
                            ).fetchone()[0]
                            or 0
                        )
                        sample_counts[a] = int(n)
                    except _sqlite.DatabaseError:
                        # Column missing on a newly-created DB → leave 0
                        pass

                # W5: agent-independent integrity counts over the window.
                try:
                    try:
                        from engine.analytics.outcome_hygiene import window_integrity
                    except ImportError:  # pragma: no cover
                        from analytics.outcome_hygiene import window_integrity

                    rows_excluded_corrupt, rows_excluded_duplicate = window_integrity(
                        conn, cutoff
                    )
                except Exception as _ig_exc:
                    logger.debug("[Calibration] integrity scan skipped: %s", _ig_exc)
    except Exception as exc:
        logger.warning("[Calibration] sample-count query failed: %s", exc)

    per_agent: dict[str, CalibrationAgentEntry] = {}
    for a in agents:
        ready = sample_counts[a] >= MIN_TRADES_FOR_IC
        per_agent[a] = CalibrationAgentEntry(
            brier_score=round(float(brier_scores[a]), 6),
            brier_weight=round(float(brier_weights.get(a, 0.0)), 6),
            ic_score=round(float(ic_scores[a]), 6),
            sample_count=sample_counts[a],
            ready=ready,
        )

    # W6: readiness over agents that actually emit signals; perennially-silent
    # agents (e.g. breakout/harmonic) no longer block activation forever.
    active_agents = [a for a in agents if sample_counts[a] > 0]
    blocked_by = [a for a in active_agents if sample_counts[a] < MIN_TRADES_FOR_IC]
    ready_to_activate = bool(active_agents) and not blocked_by

    from datetime import timezone as _tz_iso

    return CalibrationDiagnosticsResponse(
        brier_enabled=_is_brier_enabled(),
        brier_blend_alpha=float(BRIER_BLEND_ALPHA),
        min_trades_threshold=int(MIN_TRADES_FOR_IC),
        window_days=int(DEFAULT_WINDOW_DAYS),
        agents=agents,
        per_agent=per_agent,
        total_outcomes=int(total_outcomes),
        ready_to_activate=ready_to_activate,
        active_agents=active_agents,
        blocked_by=blocked_by,
        rows_excluded_corrupt=int(rows_excluded_corrupt),
        rows_excluded_duplicate=int(rows_excluded_duplicate),
        neutral_sentinel=float(BRIER_NEUTRAL),
        timestamp=datetime.now(_tz_iso.utc).isoformat(),
    )


# ─── Per-agent debate weights (AgentFeedbackTracker, distinct from Brier/IC) ──


class AgentWeightEntry(BaseModel):
    """Per-agent P&L-correlation debate weight."""

    model_config = ConfigDict(from_attributes=True)

    live_weight: float  # What debate.py actually applies right now (see weights_source)
    recomputed_weight: float  # Fresh all-regime AgentFeedbackTracker.get_agent_weights() —
    # a diagnostic view, NOT necessarily what's applied live (see weights_source)
    accuracy_30d: float  # Directional accuracy over trailing 30 days
    accuracy_90d: float  # Directional accuracy over trailing 90 days
    sample_count_30d: int  # Signal-emitting trade_outcomes rows in the 30d window
    ready: bool  # True once sample_count_30d >= min_trades_threshold


class AgentWeightsResponse(BaseModel):
    """Full per-agent debate-weight snapshot.

    Distinct from /analytics/calibration, which tracks Brier/IC scores for a
    separate calibration blend.

    debate.py's run_debate() (engine/agents/debate.py:485-491) picks the
    weight source based on whether a regime is known: get_weights_by_regime
    (regime) when it is, load_weights() (reads agent_weights.json) when it
    isn't. It never calls get_agent_weights() directly for the live
    multiplier. live_weight mirrors whichever of those two functions
    debate.py would actually use for the given `regime` query param, so the
    dashboard shows the real applied number instead of a plausible-looking
    but different one.
    """

    model_config = ConfigDict(from_attributes=True)

    min_weight: float
    max_weight: float
    default_weight: float
    min_trades_threshold: int
    agents: list[str]
    per_agent: dict[str, AgentWeightEntry]
    regime: Optional[str]  # regime this response reflects, if one was passed
    weights_source: str  # which AgentFeedbackTracker function produced live_weight
    weights_file_exists: bool  # agent_weights.json — if False, load_weights() (the
    # no-regime live path) always returns DEFAULT_WEIGHT for every agent, because
    # nothing in the codebase currently calls AgentFeedbackTracker.save_weights()
    saved_weights_updated_at: Optional[str]
    timestamp: str


@router.get(
    "/agent-weights",
    response_model=AgentWeightsResponse,
    description=(
        "Expose per-agent P&L-correlation debate weights from AgentFeedbackTracker "
        "(0.70-1.30 multiplier applied to Stage-1 analyst signals in debate.py). "
        "live_weight matches whichever function debate.py actually calls for the "
        "given regime (or no regime); recomputed_weight is a separate, freshly "
        "computed all-regime diagnostic that may differ from what's live."
    ),
)
async def get_agent_weights_diagnostics(
    regime: Optional[str] = Query(
        None,
        description=(
            "If provided, live_weight uses get_weights_by_regime(regime) — matches "
            "debate.py's regime-conditional path. Omit to use load_weights() — "
            "matches debate.py's no-regime path (reads agent_weights.json, which "
            "is always DEFAULT_WEIGHT if nothing has called save_weights())."
        ),
    ),
) -> AgentWeightsResponse:
    """Return current AgentFeedbackTracker debate weights + supporting accuracy stats.

    Degrades gracefully when trade_outcomes is missing/empty — never 500s on cold start.
    """
    import json as _json
    import sqlite3 as _sqlite3

    try:
        from analytics.agent_feedback import (
            AGENT_NAMES,
            DEFAULT_WEIGHT,
            MAX_WEIGHT,
            MIN_WEIGHT,
            WEIGHTS_FILE,
            AgentFeedbackTracker,
        )
        from analytics.agent_feedback import (
            DB_PATH as FB_DB_PATH,
        )
    except Exception as exc:
        logger.error("[AgentWeights] import failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"agent-weights deps unavailable: {exc}") from exc

    min_trades = 5  # matches AgentFeedbackTracker._compute_accuracy_internal floor
    tracker = AgentFeedbackTracker()

    try:
        if regime:
            live_weights = tracker.get_weights_by_regime(regime)
            weights_source = f"get_weights_by_regime({regime!r}) — debate.py's live regime path"
        else:
            live_weights = tracker.load_weights()
            weights_source = "load_weights() — debate.py's live no-regime path (reads agent_weights.json)"
    except Exception as exc:
        logger.warning("[AgentWeights] live weight compute failed: %s", exc)
        live_weights = dict.fromkeys(AGENT_NAMES, DEFAULT_WEIGHT)
        weights_source = f"fallback defaults after error: {exc}"

    try:
        recomputed_weights = tracker.get_agent_weights()
    except Exception as exc:
        logger.warning("[AgentWeights] recomputed-weight compute failed: %s", exc)
        recomputed_weights = dict.fromkeys(AGENT_NAMES, DEFAULT_WEIGHT)

    accuracy_30d: dict[str, float] = {}
    accuracy_90d: dict[str, float] = {}
    sample_counts_30d: dict[str, int] = dict.fromkeys(AGENT_NAMES, 0)

    for a in AGENT_NAMES:
        try:
            accuracy_30d[a] = tracker.compute_accuracy(a, 30)
            accuracy_90d[a] = tracker.compute_accuracy(a, 90)
        except Exception as exc:
            logger.warning("[AgentWeights] accuracy compute failed for %s: %s", a, exc)
            accuracy_30d[a] = 0.5
            accuracy_90d[a] = 0.5

    try:
        if FB_DB_PATH.exists():
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            with _sqlite3.connect(str(FB_DB_PATH)) as conn:
                for a in AGENT_NAMES:
                    sig_col = f"{a}_signal"
                    try:
                        n = (
                            conn.execute(
                                f"SELECT COUNT(*) FROM trade_outcomes "
                                f"WHERE timestamp > ? AND {sig_col} != 0",
                                (cutoff,),
                            ).fetchone()[0]
                            or 0
                        )
                        sample_counts_30d[a] = int(n)
                    except _sqlite3.DatabaseError:
                        pass
    except Exception as exc:
        logger.warning("[AgentWeights] sample-count query failed: %s", exc)

    per_agent: dict[str, AgentWeightEntry] = {}
    for a in AGENT_NAMES:
        per_agent[a] = AgentWeightEntry(
            live_weight=live_weights.get(a, DEFAULT_WEIGHT),
            recomputed_weight=recomputed_weights.get(a, DEFAULT_WEIGHT),
            accuracy_30d=round(float(accuracy_30d[a]), 4),
            accuracy_90d=round(float(accuracy_90d[a]), 4),
            sample_count_30d=sample_counts_30d[a],
            ready=sample_counts_30d[a] >= min_trades,
        )

    weights_file_exists = WEIGHTS_FILE.exists()
    saved_updated_at: Optional[str] = None
    try:
        if weights_file_exists:
            with open(WEIGHTS_FILE) as f:
                saved_updated_at = _json.load(f).get("updated_at")
    except Exception as exc:
        logger.debug("[AgentWeights] saved-weights read skipped: %s", exc)

    return AgentWeightsResponse(
        min_weight=float(MIN_WEIGHT),
        max_weight=float(MAX_WEIGHT),
        default_weight=float(DEFAULT_WEIGHT),
        min_trades_threshold=min_trades,
        agents=list(AGENT_NAMES),
        per_agent=per_agent,
        regime=regime,
        weights_source=weights_source,
        weights_file_exists=weights_file_exists,
        saved_weights_updated_at=saved_updated_at,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─── Trade post-mortems (agents/post_mortem.py) ──────────────────────────────


class PostMortemEntry(BaseModel):
    """A single stored post-trade LLM analysis."""

    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    symbol: Optional[str]
    pnl: Optional[float]
    analysis: Optional[str]
    lesson: Optional[str]
    created_at: Optional[str]


class PostMortemsResponse(BaseModel):
    """Recent trade post-mortems, most recent first."""

    model_config = ConfigDict(from_attributes=True)

    entries: list[PostMortemEntry]
    total: int
    timestamp: str


@router.get(
    "/post-mortems",
    response_model=PostMortemsResponse,
    description=(
        "Recent trade_post_mortem rows written by agents/post_mortem.py's "
        "PostTradeAnalyzer. Returns an empty list (not an error) if the table "
        "doesn't exist yet — no post-mortem has ever been generated."
    ),
)
async def get_post_mortems(
    limit: int = Query(20, ge=1, le=200),
    symbol: Optional[str] = None,
) -> PostMortemsResponse:
    """Return recent post-mortems, gracefully handling a not-yet-created table."""
    import sqlite3 as _sqlite3

    db = _get_db()
    where_clause = " WHERE symbol = ?" if symbol else ""
    filter_params: list = [symbol] if symbol else []

    query = (
        "SELECT trade_id, symbol, pnl, analysis, lesson, created_at FROM trade_post_mortem"
        + where_clause
        + " ORDER BY created_at DESC LIMIT ?"
    )
    params = [*filter_params, limit]

    try:
        conn = db._connect()
        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM trade_post_mortem" + where_clause,
                tuple(filter_params),
            ).fetchone()[0]
        finally:
            conn.close()
    except _sqlite3.OperationalError as exc:
        logger.info("[PostMortems] table not yet created (%s) — returning empty", exc)
        return PostMortemsResponse(entries=[], total=0, timestamp=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.error("[PostMortems] query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"post-mortem query failed: {exc}") from exc

    entries = [
        PostMortemEntry(
            trade_id=row["trade_id"],
            symbol=row["symbol"],
            pnl=row["pnl"],
            analysis=row["analysis"],
            lesson=row["lesson"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return PostMortemsResponse(
        entries=entries,
        total=int(total or 0),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/mtf")
async def get_mtf_analysis(symbol: str = "MES"):
    """Multi-timeframe STC analysis for a single symbol.
    Returns 1h, 4h, and 1d STC signals with alignment and recommendation.
    """
    try:
        from analytics.mtf_analyzer import analyze_mtf

        sym = symbol.strip().upper()
        result = await analyze_mtf(sym, _data_mgr)
        return {
            "symbol": result.symbol,
            "recommendation": result.recommendation,
            "alignment": result.alignment,
            "confidence": result.confidence,
            "aligned_timeframes": result.aligned_timeframes,
            "total_timeframes": result.total_timeframes,
            "source": result.source,
            "timeframes": {
                s.timeframe: {
                    "stc_value": s.stc_value,
                    "stc_signal": s.stc_signal,
                    "price": s.price,
                    "source": s.source,
                }
                for s in result.signals
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ─── Market-regime endpoints (US-004, 2026-06-12) ────────────────────────────
# Consumed by dashboard RegimeDisplay (overview) and the jarvis page (per
# symbol). Honest-data contract: layers the engine has no live detector for
# report status="stub"; the overview regime derives only from the persistent-
# regime alert detector (VIX / RSI streaks), never from fabricated signals.


@router.get("/regime")
async def get_regime_overview():
    """Market-regime overview card.

    regime: BEARISH when the persistent-regime alert (high-VIX / persistent-
    oversold streaks) is firing, NEUTRAL when checks ran clean, UNKNOWN when
    the detector has no data. Only the vix layer is live; the rest are stubs.
    """
    regime, confidence, note = "UNKNOWN", 0.0, None
    vix_layer: dict = {"status": "stub"}
    trade_filter = "unknown"
    try:
        from analytics.regime_detector import VIX_ALERT_THRESHOLD, check_regime_alerts

        report = check_regime_alerts()
        alerts = getattr(report, "alerts", []) or []
        vix_val = getattr(report, "vix_current", None)
        if vix_val is not None:
            vix_layer = {
                "status": "active",
                "value": vix_val,
                "classification": "ELEVATED" if vix_val > VIX_ALERT_THRESHOLD else "NORMAL",
            }
        if alerts:
            regime, confidence = "BEARISH", 0.6
            trade_filter = "block"
            note = "; ".join(str(getattr(a, "condition", a)) for a in alerts)
        elif vix_val is not None:
            regime, confidence = "NEUTRAL", 0.4
            trade_filter = "pass"
            note = "no persistent-regime alerts; directional layers not yet wired"
    except Exception as exc:
        note = f"regime detector unavailable: {exc}"

    stub = {"status": "stub"}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "confidence": confidence,
        "layers": {
            "vix": vix_layer,
            "mtf": dict(stub),
            "stc": dict(stub),
            "ema_trend": dict(stub),
            "volume": dict(stub),
        },
        "note": note,
        "trade_filter": trade_filter,
    }


@router.get("/regime/{symbol}")
async def get_regime_for_symbol(symbol: str):
    """Per-symbol regime classification (TRENDING / RANGING / VOLATILE).

    NOTE: despite the docstring below, this is backtest.regime.RegimeClassifier
    (3-state), NOT the classifier engine/agents/pipeline.py actually uses live
    for regime-based strategy routing (that's RegimeClassifierV2, 5-state --
    see GET /analytics/regime-v2/{symbol} below). Left as-is to avoid changing
    behavior for any existing caller of this route.

    Same classifier the backtester uses; UNKNOWN when bar data is missing
    rather than a fabricated default.
    """
    sym = symbol.strip().upper()
    try:
        from backtest.regime import RegimeClassifier

        bars = None
        if _data_mgr is not None:
            bars = await _data_mgr.get_bars(sym, lookback_days=10, timeframe="1h")
        if bars is None or len(bars) < 20:
            return {"symbol": sym, "regime": "UNKNOWN", "note": "insufficient bar data"}
        classified = RegimeClassifier().classify(bars)
        regime = str(classified["regime_type"].iloc[-1]) if len(classified) else "UNKNOWN"
        return {"symbol": sym, "regime": regime, "current_regime": regime}
    except Exception as exc:
        return {"symbol": sym, "regime": "UNKNOWN", "error": str(exc)}


class RegimeV2Response(BaseModel):
    """Live regime classification from the same classifier the pipeline uses to route strategies."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    regime: str
    description: Optional[str] = None
    atr_norm: Optional[float] = None
    ema_alignment: Optional[dict] = None
    validated: bool
    probability_vector: Optional[dict] = None
    note: Optional[str] = None
    timestamp: str


@router.get(
    "/regime-v2/{symbol}",
    response_model=RegimeV2Response,
    description=(
        "Regime classification from backtest.regime_classifier.RegimeClassifierV2 -- "
        "the classifier engine/agents/pipeline.py actually uses live for regime-based "
        "strategy routing (5-state: TREND/MEANREV/RANGE/VOLATILE/CRISIS). Distinct from "
        "the legacy /analytics/regime/{symbol} above, which is not in the live routing path. "
        "Deterministic rule-based thresholds only -- probability_vector is always null "
        "(the classifier doesn't produce one) and validated is always false (no "
        "ground-truth accuracy score exists for this classifier yet)."
    ),
)
async def get_regime_v2_for_symbol(symbol: str) -> RegimeV2Response:
    """Return the live pipeline's regime classification for a symbol, on demand."""
    sym = symbol.strip().upper()
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        from backtest.regime_classifier import RegimeClassifierV2

        bars = None
        if _data_mgr is not None:
            bars = await _data_mgr.get_bars(sym, lookback_days=30, timeframe="1h")
        if bars is None or len(bars) < 50:
            return RegimeV2Response(
                symbol=sym,
                regime="UNKNOWN",
                validated=False,
                note="insufficient bar data (need >= 50 bars)",
                timestamp=timestamp,
            )
        report = RegimeClassifierV2().classify_latest(bars)
        return RegimeV2Response(
            symbol=sym,
            regime=str(report.get("regime", "UNKNOWN")),
            description=report.get("description"),
            atr_norm=report.get("atr_norm"),
            ema_alignment=report.get("ema_alignment"),
            validated=False,
            probability_vector=None,
            timestamp=timestamp,
        )
    except Exception as exc:
        logger.error("[RegimeV2] classification failed for %s: %s", sym, exc)
        return RegimeV2Response(
            symbol=sym,
            regime="UNKNOWN",
            validated=False,
            note=f"classification failed: {exc}",
            timestamp=timestamp,
        )


# ─── Portfolio correlation preview (risk/portfolio_sizer.py, NOT live-wired) ─


class CorrelationPreviewResponse(BaseModel):
    """Live pairwise return-correlation estimate across the watched instruments.

    risk/portfolio_sizer.py + risk/correlation_estimator.py are validated, pure
    functions that compute what a correlation-aware sizing trim WOULD be -- but
    per portfolio_sizer.py's own module docstring, they are "intentionally kept
    separate (and Amo-gated) so this module stays inert until a backtest
    validates the behaviour change." No live order has ever been trimmed for
    correlation. wired_into_live_sizing is hardcoded false so the dashboard can
    never accidentally imply otherwise.
    """

    model_config = ConfigDict(from_attributes=True)

    symbols: list[str]
    pairs: dict[str, float]
    omitted_pairs: list[str]
    wired_into_live_sizing: bool
    note: str
    timestamp: str


@router.get(
    "/correlation-preview",
    response_model=CorrelationPreviewResponse,
    description=(
        "Live pairwise correlation estimate (risk/correlation_estimator.py) across "
        "the watched futures instruments, for display only. The correlation-aware "
        "sizing trim this would feed (risk/portfolio_sizer.py) is NOT wired into "
        "the live order path -- wired_into_live_sizing is always false."
    ),
)
async def get_correlation_preview(
    symbols: str = Query("MES,MGC,MCL,MNQ", description="Comma-separated symbols"),
    lookback_days: int = Query(30, ge=5, le=180),
) -> CorrelationPreviewResponse:
    """Compute a live correlation matrix preview; never touches order sizing."""
    from risk.correlation_estimator import bars_to_returns, estimate_correlations

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    timestamp = datetime.now(timezone.utc).isoformat()

    returns_by_symbol: dict[str, list] = {}
    for sym in sym_list:
        try:
            if _data_mgr is None:
                continue
            bars = await _data_mgr.get_bars(sym, lookback_days=lookback_days, timeframe="1h")
            if bars is None or len(bars) < 21:
                continue
            closes = list(bars["close"])
            returns_by_symbol[sym] = bars_to_returns(closes)
        except Exception as exc:
            logger.warning("[CorrelationPreview] bars fetch failed for %s: %s", sym, exc)

    pairs = estimate_correlations(returns_by_symbol) if returns_by_symbol else {}

    # estimate_correlations() sorts symbols alphabetically before pairing them
    # (see risk/correlation_estimator.py), so the "expected pairs" set must use
    # the same sorted ordering -- otherwise every computed pair falsely shows
    # up as omitted under its differently-ordered key.
    sorted_syms = sorted(sym_list)
    all_expected_pairs = {
        f"{a}/{b}"
        for i, a in enumerate(sorted_syms)
        for b in sorted_syms[i + 1 :]
    }
    computed_pairs = {f"{a}/{b}" for (a, b) in pairs}
    omitted = sorted(all_expected_pairs - computed_pairs)

    return CorrelationPreviewResponse(
        symbols=sym_list,
        pairs={f"{a}/{b}": round(rho, 4) for (a, b), rho in pairs.items()},
        omitted_pairs=omitted,
        wired_into_live_sizing=False,
        note=(
            "Preview only. risk/portfolio_sizer.py's correlation-aware sizing "
            "trim is validated but not yet wired into the live order path."
        ),
        timestamp=timestamp,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /analytics/excursion   —   MAE/MFE post-trade excursion analytics
# ─────────────────────────────────────────────────────────────────────────────


class ExcursionTradeItem(BaseModel):
    """Per-trade MAE/MFE summary."""

    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    entry_time: str
    exit_time: Optional[str] = None
    mae_pct: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_usd: Optional[float] = None
    mfe_usd: Optional[float] = None
    mfe_capture_ratio: Optional[float] = None


class ExcursionAggregates(BaseModel):
    """Aggregate MAE/MFE statistics across the returned trade set."""

    model_config = ConfigDict(from_attributes=True)

    trade_count: int
    populated_count: int  # trades with non-NULL mae/mfe
    avg_mae_pct: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    avg_mae_usd: Optional[float] = None
    avg_mfe_usd: Optional[float] = None
    avg_mfe_capture_ratio: Optional[float] = None  # avg over trades where mfe_pct > 0


class ExcursionResponse(BaseModel):
    """Full excursion analytics response."""

    model_config = ConfigDict(from_attributes=True)

    trades: list[ExcursionTradeItem]
    aggregates: ExcursionAggregates
    timestamp: str


@router.get(
    "/excursion",
    response_model=ExcursionResponse,
    summary="MAE/MFE post-trade excursion analytics for closed paper trades",
)
def get_excursion_analytics(
    limit: int = Query(100, ge=1, le=500, description="Max trades to return"),
    symbol: Optional[str] = Query(None, description="Filter by symbol (case-insensitive)"),
) -> ExcursionResponse:
    """
    Return per-trade MAE/MFE excursion data and aggregate stats.

    Columns mae_pct / mfe_pct / mae_usd / mfe_usd are populated
    asynchronously after close; NULL values mean the backfill has not
    run yet for that trade.

    Aggregates include:
    - avg_mae_pct / avg_mfe_pct  (average excursion fractions)
    - avg_mfe_capture_ratio      = avg((mfe - mae) / mfe) over trades where mfe > 0
      (closer to 1.0 = exits near peak; closer to 0 = leaving money on the table)
    """
    from datetime import datetime as _dt

    from analytics.excursion import mfe_capture_ratio as _mfe_capture_ratio

    db = _get_db()

    sql_parts = ["SELECT * FROM paper_trades WHERE status = 'closed'"]
    params: list = []

    if symbol:
        sql_parts.append("AND symbol = ?")
        params.append(symbol.strip().upper())

    sql_parts.append("ORDER BY exit_time DESC LIMIT ?")
    params.append(limit)

    sql = " ".join(sql_parts)

    with db._lock:  # type: ignore[attr-defined]
        conn = db._connect()  # type: ignore[attr-defined]
        try:
            rows = conn.execute(sql, params).fetchall()
            raw_trades = [dict(r) for r in rows]
        finally:
            conn.close()

    trade_items: list[ExcursionTradeItem] = []
    for t in raw_trades:
        capture = _mfe_capture_ratio(t.get("mae_pct"), t.get("mfe_pct"))
        trade_items.append(
            ExcursionTradeItem(
                trade_id=str(t.get("trade_id", "")),
                symbol=str(t.get("symbol", "")),
                side=str(t.get("side", "")),
                entry_price=float(t.get("entry_price") or 0),
                exit_price=float(t["exit_price"]) if t.get("exit_price") is not None else None,
                pnl=float(t["pnl"]) if t.get("pnl") is not None else None,
                entry_time=str(t.get("entry_time", "")),
                exit_time=str(t["exit_time"]) if t.get("exit_time") else None,
                mae_pct=t.get("mae_pct"),
                mfe_pct=t.get("mfe_pct"),
                mae_usd=t.get("mae_usd"),
                mfe_usd=t.get("mfe_usd"),
                mfe_capture_ratio=capture,
            )
        )

    # Aggregates over trades with populated excursion data
    populated = [t for t in trade_items if t.mae_pct is not None]
    n = len(populated)

    def _avg(vals):
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 6) if clean else None

    capture_vals = [t.mfe_capture_ratio for t in populated if t.mfe_pct and t.mfe_pct > 0]

    agg = ExcursionAggregates(
        trade_count=len(trade_items),
        populated_count=n,
        avg_mae_pct=_avg([t.mae_pct for t in populated]),
        avg_mfe_pct=_avg([t.mfe_pct for t in populated]),
        avg_mae_usd=_avg([t.mae_usd for t in populated]),
        avg_mfe_usd=_avg([t.mfe_usd for t in populated]),
        avg_mfe_capture_ratio=_avg(capture_vals),
    )

    return ExcursionResponse(
        trades=trade_items,
        aggregates=agg,
        timestamp=_dt.utcnow().isoformat() + "Z",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /analytics/entry-timing   —   Entry-timing scenario analysis (US-005)
# ─────────────────────────────────────────────────────────────────────────────


class EntryTimingScenarioRow(BaseModel):
    """One offset scenario for a single trade."""

    model_config = ConfigDict(from_attributes=True)

    offset_bars: int
    hypothetical_entry: float
    pnl_usd: float
    pnl_pct: float
    delta_vs_actual_usd: float


class EntryTimingTradeItem(BaseModel):
    """Per-trade entry-timing scenario result."""

    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    entry_time: str
    exit_time: Optional[str] = None
    scenarios: list[EntryTimingScenarioRow]
    entry_bar_index: Optional[int] = None
    bars_available: bool = False


class EntryTimingAggregates(BaseModel):
    """Aggregate entry-timing insight across the returned trade set."""

    model_config = ConfigDict(from_attributes=True)

    trade_count: int
    computed_count: int  # trades for which scenarios were produced
    # Per-offset averages across all computed trades
    avg_delta_by_offset: dict[str, float]  # key = str(offset_bars), val = avg delta_vs_actual_usd
    # Directional summary: are entries systematically early or late?
    best_avg_offset: Optional[int] = None   # offset with highest avg delta
    worst_avg_offset: Optional[int] = None  # offset with lowest avg delta
    systematic_bias: Optional[str] = None   # "EARLY" | "LATE" | "NEUTRAL"


class EntryTimingResponse(BaseModel):
    """Full entry-timing scenario response."""

    model_config = ConfigDict(from_attributes=True)

    trades: list[EntryTimingTradeItem]
    aggregates: EntryTimingAggregates
    offsets_evaluated: list[int]
    timestamp: str


@router.get(
    "/entry-timing",
    response_model=EntryTimingResponse,
    summary="Entry-timing scenario analysis: what-if entered N bars earlier/later",
)
async def get_entry_timing(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Max trades to analyse"),
    symbol: Optional[str] = Query(None, description="Filter by symbol (case-insensitive)"),
    offsets: str = Query(
        "-3,-2,-1,0,1,2,3",
        description="Comma-separated bar offsets to evaluate (e.g. -3,-2,-1,0,1,2,3)",
    ),
) -> EntryTimingResponse:
    """
    For each closed paper trade, compute hypothetical PnL if entry had occurred
    N bars earlier or later (holding exit price constant).

    ``offset=0`` reproduces the actual trade PnL (sanity anchor).
    Negative offsets = earlier entry; positive = later entry.
    ``delta_vs_actual_usd > 0`` means that scenario was more profitable.

    Aggregates answer: "are my entries systematically early or late?"
    (``systematic_bias`` = EARLY when entering later is consistently better,
    LATE when entering earlier is consistently better, NEUTRAL otherwise).

    Bars are fetched via the engine MarketDataManager (TV MCP → IBKR → Polygon).
    Trades where bars are unavailable return ``bars_available=false`` with an
    empty scenarios list — they are excluded from aggregates.
    """
    from datetime import datetime as _dt

    from analytics.excursion_backfill import _filter_bars_to_window, _parse_utc
    from analytics.scenario import compute_entry_timing_scenarios
    from analytics.scenario_backfill import _locate_entry_bar
    from utils.position_sizing import get_contract_multiplier

    # Parse offset list
    try:
        parsed_offsets = [int(o.strip()) for o in offsets.split(",") if o.strip()]
    except ValueError:
        raise HTTPException(400, "offsets must be a comma-separated list of integers") from None

    if not parsed_offsets:
        raise HTTPException(400, "offsets must not be empty")

    db = _get_db()

    sql_parts = ["SELECT * FROM paper_trades WHERE status = 'closed'"]
    params: list = []

    if symbol:
        sql_parts.append("AND symbol = ?")
        params.append(symbol.strip().upper())

    sql_parts.append("ORDER BY exit_time DESC LIMIT ?")
    params.append(limit)

    sql = " ".join(sql_parts)

    with db._lock:  # type: ignore[attr-defined]
        conn = db._connect()  # type: ignore[attr-defined]
        try:
            rows = conn.execute(sql, params).fetchall()
            raw_trades = [dict(r) for r in rows]
        finally:
            conn.close()

    trade_items: list[EntryTimingTradeItem] = []
    # Accumulate delta sums per offset for aggregation
    delta_sums: dict[int, float] = dict.fromkeys(parsed_offsets, 0.0)
    delta_counts: dict[int, int] = dict.fromkeys(parsed_offsets, 0)
    computed_count = 0

    dm = _data_mgr

    for t in raw_trades:
        trade_id = str(t.get("trade_id", ""))
        sym = str(t.get("symbol", ""))
        side = str(t.get("side", "buy"))
        entry_price = float(t.get("entry_price") or 0)
        exit_price_val = t.get("exit_price")
        exit_price = float(exit_price_val) if exit_price_val is not None else None
        qty = float(t.get("quantity") or 1)
        entry_time_raw = t.get("entry_time", "")
        exit_time_raw = t.get("exit_time")

        base_item = EntryTimingTradeItem(
            trade_id=trade_id,
            symbol=sym,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=float(t["pnl"]) if t.get("pnl") is not None else None,
            entry_time=entry_time_raw,
            exit_time=str(exit_time_raw) if exit_time_raw else None,
            scenarios=[],
            bars_available=False,
        )

        # Skip if bars unavailable or invalid prices
        if dm is None or entry_price <= 0 or exit_price is None or exit_price <= 0:
            trade_items.append(base_item)
            continue

        entry_dt = _parse_utc(entry_time_raw)
        exit_dt = _parse_utc(exit_time_raw)
        if not entry_dt or not exit_dt:
            trade_items.append(base_item)
            continue

        max_pre = abs(min(parsed_offsets)) if parsed_offsets else 3
        fetch_days = max(1, (exit_dt - entry_dt).days + 1) + max(2, (max_pre // 390) + 2)

        try:
            from datetime import timedelta as _td

            bars_df = await dm.get_bars(sym, lookback_days=fetch_days, timeframe="1m", is_futures=True)
        except Exception as exc:
            logger.debug("[entry-timing] trade %s get_bars failed: %s", trade_id[:8], exc)
            trade_items.append(base_item)
            continue

        if bars_df is None or (hasattr(bars_df, "empty") and bars_df.empty):
            trade_items.append(base_item)
            continue

        from datetime import timedelta as _td

        window_bars = _filter_bars_to_window(
            bars_df,
            entry_dt - _td(minutes=max_pre + 5),
            exit_dt,
        )

        if len(window_bars) == 0:
            trade_items.append(base_item)
            continue

        entry_bar_idx = _locate_entry_bar(window_bars, entry_dt)
        if entry_bar_idx is None:
            trade_items.append(base_item)
            continue

        multiplier = get_contract_multiplier(sym)
        scenario_rows = compute_entry_timing_scenarios(
            side=side,
            actual_entry_price=entry_price,
            exit_price=exit_price,
            bars_df=window_bars,
            entry_bar_index=entry_bar_idx,
            offsets=parsed_offsets,
            multiplier=multiplier,
            qty=qty,
        )

        if not scenario_rows:
            trade_items.append(base_item)
            continue

        computed_count += 1
        scenario_models = [EntryTimingScenarioRow(**r) for r in scenario_rows]
        base_item.scenarios = scenario_models
        base_item.bars_available = True
        base_item.entry_bar_index = entry_bar_idx

        for row_s in scenario_rows:
            o = row_s["offset_bars"]
            if o in delta_sums:
                delta_sums[o] += row_s["delta_vs_actual_usd"]
                delta_counts[o] += 1

        trade_items.append(base_item)

    # Build per-offset avg delta dict
    avg_delta: dict[str, float] = {}
    for o in parsed_offsets:
        cnt = delta_counts[o]
        avg_delta[str(o)] = round(delta_sums[o] / cnt, 4) if cnt > 0 else 0.0

    # Best / worst offset (exclude offset=0 from the ranking)
    non_zero_offsets = [o for o in parsed_offsets if o != 0]
    best_offset: Optional[int] = None
    worst_offset: Optional[int] = None
    systematic_bias: Optional[str] = None

    if non_zero_offsets and computed_count > 0:
        best_offset = max(non_zero_offsets, key=lambda o: avg_delta.get(str(o), 0.0))
        worst_offset = min(non_zero_offsets, key=lambda o: avg_delta.get(str(o), 0.0))

        best_val = avg_delta.get(str(best_offset), 0.0)
        # Bias heuristic: best offset consistently positive → entering at that
        # point was better than actual.  Negative best_offset = earlier,
        # positive = later.
        if best_val > 0:
            if best_offset < 0:
                systematic_bias = "LATE"   # entering later than optimal → entering earlier helps
            elif best_offset > 0:
                systematic_bias = "EARLY"  # entering later helps → actual was early
        else:
            systematic_bias = "NEUTRAL"

    agg = EntryTimingAggregates(
        trade_count=len(trade_items),
        computed_count=computed_count,
        avg_delta_by_offset=avg_delta,
        best_avg_offset=best_offset,
        worst_avg_offset=worst_offset,
        systematic_bias=systematic_bias,
    )

    return EntryTimingResponse(
        trades=trade_items,
        aggregates=agg,
        offsets_evaluated=parsed_offsets,
        timestamp=_dt.utcnow().isoformat() + "Z",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /analytics/bar-depth   —   data-coverage / health per symbol × interval
# ─────────────────────────────────────────────────────────────────────────────


class BarDepthPair(BaseModel):
    """Coverage record for one (symbol, interval) in market_data_bars."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    interval: str
    rows: int
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    span_days: float
    gap_count: int          # consecutive bars spaced > 2× the median step
    max_gap_hours: float
    contaminated_pct: float  # % rejected by the live bar-quality predicate
    enforce_safe: bool       # True when zero rows would be rejected


class BarDepthSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pair_count: int
    symbol_count: int
    total_rows: int
    total_rejects: int
    contaminated_pct: float


class BarDepthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pairs: list[BarDepthPair]
    summary: BarDepthSummary
    timestamp: str


@router.get(
    "/bar-depth",
    response_model=BarDepthResponse,
    summary="Bar-data coverage/health per symbol × interval (rows, span, gaps, contaminated%)",
)
def get_bar_depth() -> BarDepthResponse:
    """
    Expose the data-coverage picture that was previously CLI-only
    (``scripts/bar_quality_fp_audit.py``): per (symbol, interval), the row count,
    calendar span, gap structure, and the fraction the write-time bar-quality gate
    would reject (same ``screen_bars`` predicate, so the number is consistent).

    Read-only and additive — no behaviour change to ingestion or the gate.
    """
    from analytics.bar_depth import compute_bar_depth

    data = compute_bar_depth()
    return BarDepthResponse(
        pairs=[BarDepthPair(**p) for p in data["pairs"]],
        summary=BarDepthSummary(**data["summary"]),
        timestamp=data["timestamp"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# WS4B post-trade / scenario analytics (exit-reason, slippage, losing-streak,
# P&L waterfall, regime attribution). All read-only over existing paper_trades
# columns; the compute lives in analytics.post_trade as pure functions so it is
# unit-tested offline. No new migration: exit_reason is DERIVED, never stored.
# ─────────────────────────────────────────────────────────────────────────────


def _post_trade_spec_lookup(symbol: str):
    """Adapter: backtest.contract_specs.get_spec, returning None for unknowns
    so analytics.post_trade stays dollar-agnostic when a symbol has no spec."""
    try:
        from backtest.contract_specs import get_spec

        return get_spec(symbol)
    except Exception:
        return None


def _fetch_closed_trades(symbol: Optional[str], limit: int) -> list[dict]:
    """Closed paper_trades as plain dicts, newest first. Mirrors /excursion."""
    db = _get_db()
    sql_parts = ["SELECT * FROM paper_trades WHERE status = 'closed'"]
    params: list = []
    if symbol:
        sql_parts.append("AND symbol = ?")
        params.append(symbol.strip().upper())
    sql_parts.append("ORDER BY exit_time DESC LIMIT ?")
    params.append(limit)
    sql = " ".join(sql_parts)
    with db._lock:  # type: ignore[attr-defined]
        conn = db._connect()  # type: ignore[attr-defined]
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


@router.get(
    "/exit-attribution",
    summary="Closed-trade P&L grouped by derived exit reason (target/stop/manual)",
)
def get_exit_attribution(
    limit: int = Query(500, ge=1, le=2000),
    symbol: Optional[str] = Query(None),
) -> dict:
    from analytics.post_trade import exit_attribution

    trades = _fetch_closed_trades(symbol, limit)
    out = exit_attribution(trades)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


@router.get(
    "/slippage-attribution",
    summary="Execution-quality breakdown of recorded slippage_ticks by symbol",
)
def get_slippage_attribution(
    limit: int = Query(500, ge=1, le=2000),
    symbol: Optional[str] = Query(None),
) -> dict:
    from analytics.post_trade import slippage_attribution

    trades = _fetch_closed_trades(symbol, limit)
    out = slippage_attribution(trades, _post_trade_spec_lookup)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


@router.get(
    "/losing-streak",
    summary="Consecutive win/loss runs and streak-local drawdown over closed trades",
)
def get_losing_streak(
    limit: int = Query(1000, ge=1, le=5000),
    symbol: Optional[str] = Query(None),
) -> dict:
    from analytics.post_trade import losing_streak

    trades = _fetch_closed_trades(symbol, limit)
    out = losing_streak(trades)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


@router.get(
    "/trades/by-regime",
    summary="Closed-trade P&L grouped by the regime each trade was entered in",
)
def get_trades_by_regime(
    limit: int = Query(1000, ge=1, le=5000),
    symbol: Optional[str] = Query(None),
) -> dict:
    from analytics.post_trade import regime_attribution

    trades = _fetch_closed_trades(symbol, limit)
    out = regime_attribution(trades)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


@router.get(
    "/trades/{trade_id}/pnl-breakdown",
    summary="Per-trade P&L waterfall (peak MFE -> given back -> realized)",
)
def get_trade_pnl_breakdown(trade_id: str) -> dict:
    from analytics.post_trade import pnl_waterfall

    db = _get_db()
    with db._lock:  # type: ignore[attr-defined]
        conn = db._connect()  # type: ignore[attr-defined]
        try:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No trade with id {trade_id!r}")
    out = pnl_waterfall(dict(row), _post_trade_spec_lookup)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out
