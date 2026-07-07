"""
Learning System API Router — Phase 6 (US-011 through US-014)

Endpoints for pattern extraction, trade classification, strategy tuning,
and session memory management.
"""

import logging
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from learning._experimental.pattern_extractor import PatternExtractor
from learning._experimental.session_memory import SessionMemory
from learning._experimental.strategy_tuner import StrategyTuner
from learning._experimental.trade_classifier import TradeClassifier

logger = logging.getLogger("jarvis_trader.learning")

router = APIRouter(prefix="/learning", tags=["learning"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db_path() -> str:
    """Return the SQLite database path from env or default."""
    return os.environ.get("DB_PATH", "data/jarvis_trader.db")


def _query_db(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT query and return results as a list of dicts."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def _fetch_closed_trades(
    symbol: Optional[str] = None,
    lookback_days: int = 30,
    limit: int = 200,
) -> list[dict]:
    """
    Pull closed trades from paper_trades, mapped to the dict shape that
    PatternExtractor, TradeClassifier, and StrategyTuner expect.
    """
    db_path = _get_db_path()

    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d %H:%M:%S")

    conditions = ["status = 'closed'", "exit_time IS NOT NULL", "exit_time >= ?"]
    params: list = [cutoff]

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())

    where = "WHERE " + " AND ".join(conditions)
    sql = f"""
        SELECT id, trade_id, symbol, side, quantity,
               entry_price, exit_price, entry_time, exit_time,
               pnl, strategy_params, notes
        FROM paper_trades
        {where}
        ORDER BY exit_time DESC
        LIMIT ?
    """
    params.append(limit)

    try:
        rows = _query_db(db_path, sql, tuple(params))
    except Exception as exc:
        logger.warning(f"DB query failed in _fetch_closed_trades: {exc}")
        return []

    trades = []
    for row in rows:
        pnl = float(row.get("pnl") or 0)
        risk = abs(pnl) * 0.5 if pnl != 0 else 1.0  # conservative fallback

        # Derive time_in_trade in hours
        time_in_trade = 1.0
        try:
            entry = row.get("entry_time")
            exit_ = row.get("exit_time")
            if entry and exit_:
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                    try:
                        dt_entry = datetime.strptime(entry, fmt)
                        dt_exit = datetime.strptime(exit_, fmt)
                        time_in_trade = max(0.01, (dt_exit - dt_entry).total_seconds() / 3600)
                        break
                    except ValueError:
                        continue
        except Exception:
            pass

        # Derive return_pct relative to entry price
        entry_price = float(row.get("entry_price") or 1)
        exit_price = float(row.get("exit_price") or entry_price)
        return_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0

        trades.append(
            {
                "id": row.get("trade_id") or str(row.get("id", "")),
                "symbol": row.get("symbol", ""),
                "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"),
                "pnl": pnl,
                "risk": risk,
                "return_pct": return_pct,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "time_in_trade": time_in_trade,
                "regime": "unknown",  # extended later if regime column exists
                "regime_aligned": False,
                "won": pnl > 0,
                "slippage": 0.0,
                "entry_confidence": 0.5,
                "target_atr": 0.0,
            }
        )
    return trades


def _get_trade_by_id(trade_id: str) -> Optional[dict]:
    """Look up a single trade by trade_id (UUID) or integer id."""
    db_path = _get_db_path()
    try:
        rows = _query_db(
            db_path,
            "SELECT * FROM paper_trades WHERE trade_id = ?",
            (trade_id,),
        )
        if not rows:
            # Try integer id fallback
            rows = _query_db(
                db_path,
                "SELECT * FROM paper_trades WHERE id = ?",
                (trade_id,),
            )
        if not rows:
            return None
        return rows[0]
    except Exception as exc:
        logger.warning(f"DB lookup failed for trade_id={trade_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LessonRequest(BaseModel):
    """Body for POST /learning/memory."""

    lesson: str
    category: str = "general"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/patterns")
async def get_patterns(
    symbol: Optional[str] = Query(None, description="Filter trades by symbol (e.g. MES)"),
    lookback_days: int = Query(30, ge=1, le=365, description="Days of history to scan"),
):
    """
    Extract recurring trading patterns from recent closed trades.

    Returns time-of-day windows, regime patterns, and win/loss streak
    patterns discovered by PatternExtractor.
    """
    try:
        trades = _fetch_closed_trades(symbol=symbol, lookback_days=lookback_days)

        extractor = PatternExtractor()
        patterns = extractor.extract(trades)

        time_of_day = []
        regime_patterns = []
        streak_patterns = []

        for p in patterns:
            serialized = {
                "name": p.name,
                "frequency": p.frequency,
                "win_rate": round(p.win_rate, 4),
                "avg_return": round(p.avg_return, 4),
                "conditions": p.conditions,
                "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            }
            key = next(iter(p.conditions), "")
            if key == "hour":
                time_of_day.append(serialized)
            elif key == "regime":
                regime_patterns.append(serialized)
            else:
                streak_patterns.append(serialized)

        return {
            "status": "ok",
            "data": {
                "symbol": symbol,
                "lookback_days": lookback_days,
                "trades_analyzed": len(trades),
                "patterns_found": len(patterns),
                "time_of_day": time_of_day,
                "regime_patterns": regime_patterns,
                "streak_patterns": streak_patterns,
            },
        }
    except Exception as exc:
        logger.exception(f"Error in GET /learning/patterns: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/classify")
async def classify_trade(
    trade_id: str = Query(..., description="Trade UUID or integer id to classify"),
):
    """
    Classify a single completed trade by outcome quality.

    Returns a letter grade (A/B/C/D/F), setup_quality, execution_quality,
    and a list of contributing factors.
    """
    try:
        raw = _get_trade_by_id(trade_id)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"Trade '{trade_id}' not found")

        pnl = float(raw.get("pnl") or 0)
        risk = abs(pnl) * 0.5 if pnl != 0 else 1.0
        entry_price = float(raw.get("entry_price") or 1)
        exit_price = float(raw.get("exit_price") or entry_price)

        time_in_trade = 1.0
        try:
            entry = raw.get("entry_time")
            exit_ = raw.get("exit_time")
            if entry and exit_:
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                    try:
                        dt_entry = datetime.strptime(entry, fmt)
                        dt_exit = datetime.strptime(exit_, fmt)
                        time_in_trade = max(0.01, (dt_exit - dt_entry).total_seconds() / 3600)
                        break
                    except ValueError:
                        continue
        except Exception:
            pass

        trade_dict = {
            "id": raw.get("trade_id") or str(raw.get("id", "")),
            "pnl": pnl,
            "risk": risk,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "time_in_trade": time_in_trade,
            "regime": "unknown",
            "regime_aligned": False,
            "won": pnl > 0,
            "slippage": 0.0,
            "entry_confidence": 0.5,
            "target_atr": 0.0,
        }

        classifier = TradeClassifier()
        result = classifier.classify(trade_dict)

        return {
            "status": "ok",
            "data": {
                "trade_id": result.trade_id,
                "grade": result.grade,
                "setup_quality": round(result.setup_quality, 4),
                "execution_quality": round(result.execution_quality, 4),
                "factors": result.factors,
                "explanation": _grade_explanation(result.grade),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in GET /learning/classify trade_id={trade_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/suggestions")
async def get_suggestions(
    symbol: Optional[str] = Query(None, description="Symbol to analyze (e.g. MES)"),
    lookback_days: int = Query(30, ge=5, le=90, description="Days of history to analyze"),
):
    """
    Generate conservative parameter adjustment suggestions based on recent
    trade performance.  Safety parameters are never touched.
    """
    try:
        trades = _fetch_closed_trades(symbol=symbol, lookback_days=lookback_days, limit=50)

        # Pull current strategy params from settings table if available
        current_params = _load_strategy_params()

        tuner = StrategyTuner()
        suggestions = tuner.suggest_adjustments(trades, current_params)

        return {
            "status": "ok",
            "data": {
                "symbol": symbol,
                "trades_analyzed": len(trades),
                "current_params": current_params,
                "suggestions": [
                    {
                        "param_name": s.param_name,
                        "current_value": s.current_value,
                        "suggested_value": s.suggested_value,
                        "confidence": round(s.confidence, 4),
                        "reason": s.reason,
                    }
                    for s in suggestions
                ],
                "suggestion_count": len(suggestions),
            },
        }
    except Exception as exc:
        logger.exception(f"Error in GET /learning/suggestions: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/memory")
async def get_memory(
    condition: Optional[str] = Query(
        None, description="Filter by market condition (e.g. TRENDING, CHOPPY)"
    ),
):
    """
    Retrieve all recorded lessons from SessionMemory.
    Optionally filter by market condition string.
    """
    try:
        mem = SessionMemory()

        if condition:
            lessons = mem.get_lessons(condition)
        else:
            lessons = mem.get_all_lessons()

        return {
            "status": "ok",
            "data": {
                "filter_condition": condition,
                "total": len(lessons),
                "lessons": [asdict(lesson) for lesson in lessons],
            },
        }
    except Exception as exc:
        logger.exception(f"Error in GET /learning/memory: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/memory")
async def record_lesson(body: LessonRequest):
    """
    Record a new lesson in SessionMemory.

    Body: ``{"lesson": "...", "category": "..."}``

    The category is stored as the market condition for later filtering.
    """
    try:
        if not body.lesson.strip():
            raise HTTPException(status_code=400, detail="lesson text must not be empty")

        mem = SessionMemory()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        success = mem.record_session(
            date=today,
            trades=[],
            market_conditions={"regime": body.category},
            lessons=[body.lesson.strip()],
        )

        if not success:
            raise HTTPException(status_code=500, detail="SessionMemory failed to persist lesson")

        return {
            "status": "ok",
            "data": {
                "recorded": True,
                "date": today,
                "category": body.category,
                "lesson": body.lesson.strip(),
                "total_lessons": len(mem.get_all_lessons()),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in POST /learning/memory: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/consolidate")
async def consolidate_memory(target_date: Optional[str] = Query(None)) -> dict:
    """
    Trigger nightly memory consolidation for the learning system.

    Consolidates trades from target_date into pattern database via TradingMemoryConsolidator.
    Runs automatically at EOD (4:05pm ET) via scheduler but can be triggered manually.

    Args:
        target_date: ISO-8601 date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Consolidation result with status, patterns extracted, and signal accuracy.
    """
    try:
        from database.manager import db_manager
        from learning.consolidator import TradingMemoryConsolidator

        consolidator = TradingMemoryConsolidator(db_manager=db_manager)
        result = await consolidator.consolidate_daily(target_date=target_date)

        logger.info(
            f"Memory consolidation completed: {result.get('patterns_extracted', 0)} "
            f"patterns from {result.get('trades_analyzed', 0)} trades"
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in POST /learning/consolidate: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _grade_explanation(grade: str) -> str:
    """Return a human-readable explanation for a letter grade."""
    explanations = {
        "A": "Excellent trade — strong R-multiple, well-timed, regime-aligned.",
        "B": "Good trade — solid R-multiple with acceptable execution.",
        "C": "Average trade — positive R-multiple but room for improvement.",
        "D": "Below-average trade — low R-multiple, slow or misaligned entry.",
        "F": "Failed trade — negative R-multiple (loss).",
    }
    return explanations.get(grade, "Unknown grade.")


def _compute_local_metrics(trades: list[dict]) -> tuple[float, float, float, float]:
    """
    Compute win_rate, avg_winner, avg_loser, and r_ratio from trades list.
    Local copy to avoid circular import.

    Returns: (win_rate, avg_winner, avg_loser, r_ratio)
    """
    if not trades:
        return 0.0, 0.0, 0.0, 1.0

    total = len(trades)
    winners = []
    losers = []
    wins = 0

    for trade in trades:
        pnl = float(trade.get("pnl") or 0)
        outcome = str(trade.get("outcome") or "").lower()

        if pnl > 0 or outcome == "winning_trade":
            wins += 1
            winners.append(pnl if pnl > 0 else 1.0)
        elif pnl < 0 or outcome == "losing_trade":
            losers.append(abs(pnl))

    win_rate = wins / total if total > 0 else 0.0
    avg_winner = sum(winners) / len(winners) if winners else 0.0
    avg_loser = sum(losers) / len(losers) if losers else 0.0
    r_ratio = avg_winner / avg_loser if avg_loser > 0 else 1.0

    return win_rate, avg_winner, avg_loser, r_ratio


def _format_confidence_note(win_rate: float, r_ratio: float, multiplier: float) -> str:
    """Return a human-readable explanation for the confidence adjustment."""
    if multiplier == 1.35:
        return f"Strong edge detected: {win_rate:.1%} win rate with {r_ratio:.2f}R ratio"
    elif multiplier == 1.20:
        return f"Solid edge: {win_rate:.1%} win rate with {r_ratio:.2f}R ratio"
    elif multiplier == 1.10:
        return f"Slight edge: {win_rate:.1%} win rate"
    elif multiplier == 0.65:
        return f"Poor performance: {win_rate:.1%} win rate — signal confidence reduced 35%"
    elif multiplier == 0.80:
        return f"Below average: {win_rate:.1%} win rate — signal confidence reduced 20%"
    else:
        return f"Neutral: {win_rate:.1%} win rate, {r_ratio:.2f}R ratio"


def _load_strategy_params() -> dict:
    """
    Attempt to load current strategy parameters from the settings table.
    Returns a sensible defaults dict if the table is unavailable.
    """
    defaults = {
        "STC_OS": 15,
        "STC_OB": 83,
        "STOP_ATR": 0.7,
        "T1_ATR": 1.0,
        "T2_ATR": 2.0,
        "T3_ATR": 3.0,
        "ATR_PERIOD": 14,
    }
    try:
        db_path = _get_db_path()
        rows = _query_db(
            db_path,
            "SELECT key, value FROM settings WHERE key IN "
            "('STC_OS','STC_OB','STOP_ATR','T1_ATR','T2_ATR','T3_ATR','ATR_PERIOD')",
        )
        for row in rows:
            key = row["key"]
            raw_val = row["value"]
            try:
                defaults[key] = float(raw_val)
            except (TypeError, ValueError):
                pass
    except Exception as exc:
        logger.debug(f"Could not load strategy params from settings table: {exc}")

    return defaults


@router.get("/confidence/{symbol}")
async def get_confidence_score(symbol: str):
    """
    Get the confidence adjustment score for a symbol based on recent trade history.

    Returns:
        {
            "symbol": str,
            "confidence_adjustment": float (multiplier in [0.60, 1.40]),
            "trade_count": int,
            "win_rate": float (0.0-1.0),
            "r_ratio": float,
            "sample_sufficient": bool (True if >= 20 trades),
            "note": str (human-readable explanation)
        }
    """
    try:
        from learning.confidence_scorer import MIN_TRADES_REQUIRED

        symbol = symbol.upper().strip()

        # Fetch trades for this symbol
        db_path = _get_db_path()
        cutoff = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        # paper_trades has no `outcome`/`created_at` columns; win/loss is derived
        # from the pnl sign in _compute_local_metrics. Count only closed,
        # realized-pnl rows and order by exit_time (matching _fetch_closed_trades
        # above and learning/confidence_scorer). Before this fix the query raised
        # "no such column: outcome" so this endpoint failed for every symbol.
        sql = """
            SELECT pnl FROM paper_trades
            WHERE symbol = ? AND status = 'closed' AND pnl IS NOT NULL
              AND COALESCE(exit_time, entry_time) >= ?
            ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT 100
        """
        trades = _query_db(db_path, sql, (symbol, cutoff))

        trade_count = len(trades)
        sample_sufficient = trade_count >= MIN_TRADES_REQUIRED

        if not sample_sufficient:
            return {
                "status": "ok",
                "data": {
                    "symbol": symbol,
                    "confidence_adjustment": 1.0,
                    "trade_count": trade_count,
                    "win_rate": 0.0,
                    "r_ratio": 1.0,
                    "sample_sufficient": False,
                    "note": f"Only {trade_count} trades found (minimum {MIN_TRADES_REQUIRED} required)",
                },
            }

        # Compute metrics (replicate logic from confidence_scorer)
        win_rate, avg_winner, avg_loser, r_ratio = _compute_local_metrics(trades)

        # Compute multiplier
        if win_rate >= 0.65 and r_ratio >= 1.8:
            multiplier = 1.35
        elif win_rate >= 0.60 and r_ratio >= 1.5:
            multiplier = 1.20
        elif win_rate >= 0.55:
            multiplier = 1.10
        elif win_rate <= 0.35:
            multiplier = 0.65
        elif win_rate <= 0.42:
            multiplier = 0.80
        else:
            multiplier = 1.0

        return {
            "status": "ok",
            "data": {
                "symbol": symbol,
                "confidence_adjustment": multiplier,
                "trade_count": trade_count,
                "win_rate": round(win_rate, 4),
                "r_ratio": round(r_ratio, 4),
                "sample_sufficient": True,
                "note": _format_confidence_note(win_rate, r_ratio, multiplier),
            },
        }

    except Exception as exc:
        logger.exception(f"Error in GET /learning/confidence/{symbol}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status")
async def get_learning_status() -> dict:
    """
    Get the current status of the learning system.

    Returns:
        {
            "feedback_lessons": int,
            "patterns": int,
            "recommendations_available": int,
            "last_lesson_at": str or null,
            "connection_status": {
                "events": bool,
                "feedback": bool,
                "patterns": bool,
                "recommendations": bool
            }
        }
    """
    try:
        from datetime import datetime, timedelta

        from database import get_db as get_db_manager

        db = get_db_manager()
        if not db:
            return {
                "feedback_lessons": 0,
                "patterns": 0,
                "recommendations_available": 0,
                "last_lesson_at": None,
                "connection_status": {
                    "events": False,
                    "feedback": False,
                    "patterns": False,
                    "recommendations": False,
                },
                "error": "Database unavailable",
            }

        # Count feedback lessons. The original `learning_events` table from
        # migration 013 was never wired up (see migrations.py ghost-table note);
        # `trade_outcomes` is the actual per-trade feedback record written by
        # AgentFeedbackTracker.record_outcome() and is the correct source here.
        try:
            lesson_rows = db.query(
                "SELECT COUNT(*) as count, MAX(timestamp) as last_at FROM trade_outcomes"
            )
            lesson_count = lesson_rows[0]["count"] if lesson_rows else 0
            last_lesson_at = (
                lesson_rows[0]["last_at"] if lesson_rows and lesson_rows[0]["last_at"] else None
            )
        except Exception as e:
            logger.debug(f"Could not query trade_outcomes: {e}")
            lesson_count = 0
            last_lesson_at = None

        # Count patterns (from trading_patterns table)
        try:
            pattern_rows = db.query(
                "SELECT COUNT(*) as count FROM trading_patterns WHERE is_active = 1"
            )
            pattern_count = pattern_rows[0]["count"] if pattern_rows else 0
        except Exception as e:
            logger.debug(f"Could not query trading_patterns: {e}")
            pattern_count = 0

        # Count active recommendations for last 30 days
        try:
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            rec_rows = db.query(
                "SELECT COUNT(*) as count FROM trading_patterns "
                "WHERE is_active = 1 AND last_seen >= ?",
                (cutoff,),
            )
            rec_count = rec_rows[0]["count"] if rec_rows else 0
        except Exception as e:
            logger.debug(f"Could not query recommendations: {e}")
            rec_count = 0

        return {
            "feedback_lessons": lesson_count,
            "patterns": pattern_count,
            "recommendations_available": rec_count,
            "last_lesson_at": last_lesson_at,
            "connection_status": {
                "events": True,  # Always true if we got this far
                "feedback": True,
                "patterns": True,
                "recommendations": True,
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error in GET /learning/status: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
