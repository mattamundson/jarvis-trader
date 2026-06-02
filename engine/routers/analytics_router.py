"""
Analytics Router — exposes trade_analytics and signal_quality endpoints.

Endpoints:
  GET /analytics/trades — calculate_analytics() from paper trades
  GET /analytics/signal-quality — analyze_signal_quality() with optional filters
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
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
            parsed.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except (ValueError, AttributeError):
            logger.debug("Could not parse trade timestamp: %s", raw)
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
            logger.error("_get_all_trades: SQLite query failed, falling back to ValidationTracker: %s", exc)

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
        )
    except Exception as exc:
        logger.error(f"Trade analytics error: {exc}")
        raise HTTPException(500, str(exc)) from exc


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


@router.get("/mtf")
async def get_mtf_analysis(symbol: str = "MES"):
    """
    Multi-timeframe STC analysis for a single symbol.
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

    brier_score: float              # Mean Brier over window; lower is better
    brier_weight: float             # Normalized inverse-Brier weight (sums to 1.0)
    ic_score: float                 # Spearman IC over window
    sample_count: int               # Non-zero-signal trade count in window
    ready: bool                     # True when sample_count >= min_trades


class CalibrationDiagnosticsResponse(BaseModel):
    """Full calibration snapshot — Brier + IC across all tracked analysts."""

    model_config = ConfigDict(from_attributes=True)

    brier_enabled: bool             # Reflects BRIER_CALIBRATION_ENABLED env var
    brier_blend_alpha: float        # Current blend alpha (debate.BRIER_BLEND_ALPHA)
    min_trades_threshold: int       # Minimum sample size before calibration activates
    window_days: int                # Rolling window length
    agents: list[str]               # Tracked analyst names
    per_agent: dict[str, CalibrationAgentEntry]
    total_outcomes: int             # Total rows in trade_outcomes within window
    ready_to_activate: bool         # All agents have >= min_trades
    neutral_sentinel: float         # Brier value returned when insufficient data
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
    import os as _os
    import sqlite3 as _sqlite

    try:
        from analytics.agent_feedback import AGENT_NAMES, DB_PATH as FB_DB_PATH
        from analytics.ic_ensemble import (
            BRIER_NEUTRAL,
            BrierCalibrationTracker,
            ICWeightedEnsemble,
            DEFAULT_WINDOW_DAYS,
            MIN_TRADES_FOR_IC,
        )
        # Pull live blend alpha from debate module so the endpoint tracks the
        # constant if it's ever tuned per-regime.
        from agents.debate import BRIER_BLEND_ALPHA, _is_brier_enabled
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
        brier_scores = {a: BRIER_NEUTRAL for a in agents}
        brier_weights = {a: 1.0 / len(agents) for a in agents}

    try:
        ic_scores = {a: ic.compute_ic(a) for a in agents}
    except Exception as exc:
        logger.warning("[Calibration] IC compute failed: %s", exc)
        ic_scores = {a: 0.0 for a in agents}

    # Per-agent sample count — direct SQL so it stays cheap.
    sample_counts: dict[str, int] = {a: 0 for a in agents}
    total_outcomes = 0
    try:
        if FB_DB_PATH.exists():
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            cutoff = (_dt.now(_tz.utc) - _td(days=DEFAULT_WINDOW_DAYS)).isoformat()
            with _sqlite.connect(str(FB_DB_PATH)) as conn:
                total_outcomes = conn.execute(
                    "SELECT COUNT(*) FROM trade_outcomes WHERE timestamp >= ?",
                    (cutoff,),
                ).fetchone()[0] or 0
                for a in agents:
                    sig_col = f"{a}_signal"
                    try:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM trade_outcomes "
                            f"WHERE timestamp >= ? AND {sig_col} IS NOT NULL AND {sig_col} != 0",
                            (cutoff,),
                        ).fetchone()[0] or 0
                        sample_counts[a] = int(n)
                    except _sqlite.DatabaseError:
                        # Column missing on a newly-created DB → leave 0
                        pass
    except Exception as exc:
        logger.warning("[Calibration] sample-count query failed: %s", exc)

    per_agent: dict[str, CalibrationAgentEntry] = {}
    all_ready = True
    for a in agents:
        ready = sample_counts[a] >= MIN_TRADES_FOR_IC
        all_ready = all_ready and ready
        per_agent[a] = CalibrationAgentEntry(
            brier_score=round(float(brier_scores[a]), 6),
            brier_weight=round(float(brier_weights.get(a, 0.0)), 6),
            ic_score=round(float(ic_scores[a]), 6),
            sample_count=sample_counts[a],
            ready=ready,
        )

    from datetime import timezone as _tz_iso
    return CalibrationDiagnosticsResponse(
        brier_enabled=_is_brier_enabled(),
        brier_blend_alpha=float(BRIER_BLEND_ALPHA),
        min_trades_threshold=int(MIN_TRADES_FOR_IC),
        window_days=int(DEFAULT_WINDOW_DAYS),
        agents=agents,
        per_agent=per_agent,
        total_outcomes=int(total_outcomes),
        ready_to_activate=all_ready,
        neutral_sentinel=float(BRIER_NEUTRAL),
        timestamp=datetime.now(_tz_iso.utc).isoformat(),
    )

@router.get("/analytics/performance/rolling")
async def get_rolling_performance(days: int = 30):
    """Get rolling performance metrics for the last N days (7, 14, or 30)."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")
    days = max(1, min(days, 90))  # clamp to 1-90 days
    try:
        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(db_manager)
        return calc.calculate_rolling(days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e



@router.get("/analytics/performance/compare")
async def get_analytics_performance_compare():
    """
    Compare current forward-test metrics against backtest targets.

    Forward metrics (from live paper trading in SQLite) are compared to the
    reference backtest results: PF=5.27, Sharpe=4.16.

    Returns per-metric diffs, retention percentages, and a ``degradation_ok``
    flag that is True when forward results still exceed the paper thresholds
    (PF > 2.0 and Sharpe > 1.5).
    """
    if not db_manager:
        return {
            "forward": {},
            "backtest": {"profit_factor": 5.27, "sharpe_ratio": 4.16},
            "comparison": {},
            "degradation_ok": False,
            "note": "Database not initialized.",
        }
    try:
        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(db_manager)
        return calc.compare_to_backtest()
    except Exception as exc:
        logger.error(f"[Analytics] compare_to_backtest failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}") from exc



@router.get("/analytics/trades/by-day")
async def get_trades_by_day():
    """Day-of-week breakdown of paper trade performance.
    Returns win rate, avg pnl, count for each day (Mon-Fri).
    """
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                rows = conn.execute(
                    """SELECT
                         strftime('%w', exit_time) AS dow,
                         COUNT(*) AS cnt,
                         SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                         SUM(pnl) AS total_pnl,
                         AVG(pnl) AS avg_pnl
                       FROM paper_trades
                       WHERE status = 'closed' AND exit_time IS NOT NULL
                       GROUP BY dow
                       ORDER BY dow"""
                ).fetchall()
            finally:
                conn.close()

        DAY_NAMES = {
            "0": "Sun",
            "1": "Mon",
            "2": "Tue",
            "3": "Wed",
            "4": "Thu",
            "5": "Fri",
            "6": "Sat",
        }
        result = []
        for row in rows:
            dow, cnt, wins, total_pnl, avg_pnl = row
            result.append(
                {
                    "day": DAY_NAMES.get(str(dow), str(dow)),
                    "count": cnt,
                    "wins": wins,
                    "losses": cnt - wins,
                    "win_rate": round(wins / cnt, 3) if cnt > 0 else 0.0,
                    "total_pnl": round(total_pnl or 0, 2),
                    "avg_pnl": round(avg_pnl or 0, 2),
                }
            )
        return {"days": result, "total_days_analyzed": len(result)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e



@router.get("/analytics/trades/by-symbol")
async def get_trades_by_symbol():
    """Per-symbol breakdown of paper trade performance."""
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                rows = conn.execute(
                    """SELECT
                         symbol,
                         COUNT(*) AS cnt,
                         SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                         SUM(pnl) AS total_pnl,
                         AVG(pnl) AS avg_pnl,
                         MAX(pnl) AS best_trade,
                         MIN(pnl) AS worst_trade
                       FROM paper_trades
                       WHERE status = 'closed'
                       GROUP BY symbol
                       ORDER BY total_pnl DESC"""
                ).fetchall()
            finally:
                conn.close()

        result = []
        for row in rows:
            symbol, cnt, wins, total_pnl, avg_pnl, best, worst = row
            result.append(
                {
                    "symbol": symbol,
                    "count": cnt,
                    "wins": wins,
                    "losses": cnt - wins,
                    "win_rate": round(wins / cnt, 3) if cnt > 0 else 0.0,
                    "total_pnl": round(total_pnl or 0, 2),
                    "avg_pnl": round(avg_pnl or 0, 2),
                    "best_trade": round(best or 0, 2),
                    "worst_trade": round(worst or 0, 2),
                }
            )
        return {"symbols": result, "total_symbols": len(result)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


