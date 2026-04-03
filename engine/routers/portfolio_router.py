"""
Portfolio router - unified multi-market portfolio summary.

GET /portfolio/summary - total P&L, all markets, daily target progress
GET /portfolio/health - health status of all market modules
GET /portfolio/halt - emergency halt all markets (POST)
GET /portfolio/resume - resume after halt (POST)
GET /portfolio/paper/hourly-stats - win rate by hour-of-day (CT)
GET /portfolio/paper/streaks - consecutive win/loss streaks with history
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
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


@router.get(
    "",
    description="Unified multi-market P&L summary with total daily P&L, market breakdown, and daily target progress.",
)
@router.get(
    "/summary",
    description="Unified multi-market P&L summary with total daily P&L, market breakdown, and daily target progress.",
)
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


@router.get(
    "/health",
    description="Health status of all registered market modules including daily P&L and open position count.",
)
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


@router.post(
    "/halt",
    description="Emergency halt all market modules with optional reason parameter.",
)
async def halt(reason: str = "Manual halt via API"):
    """Emergency halt all market modules."""
    orch = _get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    orch.halt_all(reason=reason)
    return {"status": "halted", "reason": reason}


@router.post(
    "/resume",
    description="Resume trading after a halt once investigation is complete.",
)
async def resume():
    """Resume trading after a halt (requires investigation first)."""
    orch = _get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    orch.resume()
    return {"status": "resumed"}


# GET /portfolio/stats/streaks - canonical handler is on the FastAPI app in main.py (StreakBadge).


@router.get(
    "/stats/paper-phase-summary",
    description="Paper validation phase rollup with balance, return percentage, trading days, and validation status.",
)
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


@router.get(
    "/paper/hold-time-stats",
    description="Average hold duration by direction and symbol, with distribution buckets. Open trades excluded.",
)
async def paper_hold_time_stats():
    """Hold time statistics broken down by direction, symbol, and 5-bucket distribution."""
    if not paper_tracker:
        return _empty_hold_time_stats()

    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("paper_hold_time_stats: get_trade_history failed: %s", exc)
        return _empty_hold_time_stats()

    durations_minutes: list[float] = []
    by_direction: dict[str, list[float]] = {"LONG": [], "SHORT": []}
    by_symbol: dict[str, list[float]] = {}

    for row in rows:
        d = row if isinstance(row, dict) else row.to_dict()
        entry_str = d.get("entry_time")
        exit_str = d.get("exit_time")
        if not entry_str or not exit_str:
            continue
        try:
            entry_dt = datetime.fromisoformat(str(entry_str).replace("Z", "+00:00"))
            exit_dt = datetime.fromisoformat(str(exit_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        mins = (exit_dt - entry_dt).total_seconds() / 60.0
        if mins < 0:
            continue

        durations_minutes.append(mins)
        action = str(d.get("action", "")).lower()
        direction = "SHORT" if ("sell" in action or "short" in action) else "LONG"
        by_direction[direction].append(mins)
        sym = str(d.get("symbol", "UNKNOWN")).upper()
        by_symbol.setdefault(sym, []).append(mins)

    return _build_hold_time_response(durations_minutes, by_direction, by_symbol)


def _empty_hold_time_stats() -> dict:
    return {
        "overall_avg_minutes": 0.0,
        "by_direction": {},
        "by_symbol": {},
        "hold_time_distribution": _distribution_buckets([]),
    }


def _avg(vals: list[float]) -> float:
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    mid = len(s) // 2
    return round((s[mid - 1] + s[mid]) / 2.0 if len(s) % 2 == 0 else s[mid], 1)


def _distribution_buckets(mins: list[float]) -> list[dict]:
    buckets = [
        {"bucket": "0-30m", "lo": 0, "hi": 30},
        {"bucket": "30-60m", "lo": 30, "hi": 60},
        {"bucket": "1-2h", "lo": 60, "hi": 120},
        {"bucket": "2-4h", "lo": 120, "hi": 240},
        {"bucket": "4h+", "lo": 240, "hi": float("inf")},
    ]
    total = len(mins) or 1
    result = []
    for b in buckets:
        cnt = sum(1 for m in mins if b["lo"] <= m < b["hi"])
        result.append({"bucket": b["bucket"], "count": cnt, "pct": round(cnt / total, 4)})
    return result


def _build_hold_time_response(
    all_mins: list[float],
    by_dir: dict[str, list[float]],
    by_sym: dict[str, list[float]],
) -> dict:
    return {
        "overall_avg_minutes": _avg(all_mins),
        "by_direction": {
            k: {"avg_minutes": _avg(v), "trade_count": len(v), "median_minutes": _median(v)}
            for k, v in by_dir.items()
            if v
        },
        "by_symbol": {
            k: {"avg_minutes": _avg(v), "trade_count": len(v)} for k, v in by_sym.items()
        },
        "hold_time_distribution": _distribution_buckets(all_mins),
    }


@router.get(
    "/paper/daily-pnl",
    description="P&L grouped by calendar day (UTC) across the last 90 days with positive/negative day counts.",
)
async def get_daily_pnl():
    """Daily P&L rollup for closed trades, last 90 days."""
    empty = {"daily_pnl": [], "total_days_traded": 0, "positive_days": 0, "negative_days": 0}
    if not paper_tracker:
        return empty

    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("get_daily_pnl: get_trade_history failed: %s", exc)
        return empty

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).date()
    day_pnl: dict[date, float] = {}
    day_count: dict[date, int] = {}

    for row in rows:
        if not _row_is_closed(row):
            continue
        d = _parse_trade_day(row)
        if d is None or d < cutoff:
            continue
        pnl = _row_pnl(row)
        day_pnl[d] = day_pnl.get(d, 0.0) + pnl
        day_count[d] = day_count.get(d, 0) + 1

    daily_list = [
        {
            "date": str(d),
            "pnl": round(day_pnl[d], 4),
            "trade_count": day_count[d],
        }
        for d in sorted(day_pnl)
    ]
    positive_days = sum(1 for entry in daily_list if entry["pnl"] > 0)
    negative_days = sum(1 for entry in daily_list if entry["pnl"] < 0)

    return {
        "daily_pnl": daily_list,
        "total_days_traded": len(daily_list),
        "positive_days": positive_days,
        "negative_days": negative_days,
    }


_CT = timezone(timedelta(hours=-5))  # Central Standard; close enough for bucketing


@router.get(
    "/paper/hourly-stats",
    description="Win rate by hour of day (Central Time) with best and worst hour summary.",
)
async def get_hourly_stats():
    """Win rate per hour-of-day (CT) for closed trades."""
    empty = {"hourly_stats": [], "best_hour": None, "worst_hour": None}
    if not paper_tracker:
        return empty

    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("get_hourly_stats: get_trade_history failed: %s", exc)
        return empty

    hour_trades: dict[int, list[float]] = {}

    for row in rows:
        if not _row_is_closed(row):
            continue
        if isinstance(row, dict):
            ts = row.get("entry_time")
        else:
            ts = getattr(row, "entry_time", None)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ct_dt = dt.astimezone(_CT)
            hour = ct_dt.hour
        except (ValueError, TypeError):
            continue
        pnl = _row_pnl(row)
        hour_trades.setdefault(hour, []).append(pnl)

    if not hour_trades:
        return empty

    hourly_stats = []
    for h in sorted(hour_trades):
        pnls = hour_trades[h]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = round(wins / len(pnls), 4) if pnls else 0.0
        hourly_stats.append(
            {
                "hour": h,
                "hour_label": f"{h:02d}:00 CT",
                "trade_count": len(pnls),
                "win_count": wins,
                "win_rate": win_rate,
                "avg_pnl": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
            }
        )

    best = max(hourly_stats, key=lambda x: x["win_rate"])
    worst = min(hourly_stats, key=lambda x: x["win_rate"])

    return {"hourly_stats": hourly_stats, "best_hour": best, "worst_hour": worst}


@router.get(
    "/paper/streaks",
    description="Current win/loss streak and historical max win/loss streaks from closed trades.",
)
async def get_streaks():
    """Win/loss streak analysis for closed trades sorted chronologically."""
    empty = {
        "current_streak": {"type": "NONE", "count": 0},
        "max_win_streak": 0,
        "max_loss_streak": 0,
        "total_trades": 0,
    }
    if not paper_tracker:
        return empty

    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("get_streaks: get_trade_history failed: %s", exc)
        return empty

    closed = [r for r in rows if _row_is_closed(r)]
    if not closed:
        return empty

    def _sort_key(r: Any) -> str:
        if isinstance(r, dict):
            ts = r.get("exit_time") or r.get("entry_time") or ""
        else:
            ts = getattr(r, "exit_time", None) or getattr(r, "entry_time", None) or ""
        return str(ts)

    closed_sorted = sorted(closed, key=_sort_key)

    outcomes: list[bool] = [_row_pnl(r) > 0 for r in closed_sorted]

    max_win = 0
    max_loss = 0
    cur_win = 0
    cur_loss = 0
    for win in outcomes:
        if win:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        max_win = max(max_win, cur_win)
        max_loss = max(max_loss, cur_loss)

    if cur_win > 0:
        current = {"type": "WIN", "count": cur_win}
    elif cur_loss > 0:
        current = {"type": "LOSS", "count": cur_loss}
    else:
        current = {"type": "NONE", "count": 0}

    return {
        "current_streak": current,
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
        "total_trades": len(outcomes),
    }


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


# ── Hourly Stats & Streak endpoints ───────────────────────────────────────────

# Central Time fixed offset: UTC-6 (CST).  For DST-aware code, use zoneinfo.
_CT_OFFSET_HOURS = -6


def _to_ct_hour(iso_ts: str | None) -> int | None:
    """Convert an ISO-8601 UTC timestamp to Central Time hour (0-23)."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ct_dt = dt + timedelta(hours=_CT_OFFSET_HOURS)
        return ct_dt.hour
    except (ValueError, TypeError):
        return None


def _hour_label(h: int) -> str:
    if h == 0:
        return "12am"
    if h < 12:
        return f"{h}am"
    if h == 12:
        return "12pm"
    return f"{h - 12}pm"


@router.get(
    "/paper/hourly-stats",
    description="Win rate broken down by hour of day in Central Time from closed paper trades.",
)
async def paper_hourly_stats():
    """
    Return per-hour-of-day win rate, trade count, and average P&L.

    Hours are in Central Time (UTC-6 fixed offset / CST).
    Only hours with at least one closed trade are included.
    """
    if not paper_tracker:
        return {"hourly_stats": [], "best_hour": None, "worst_hour": None}

    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("paper_hourly_stats: get_trade_history failed: %s", exc)
        rows = []

    buckets: dict[int, dict] = {}
    for row in rows:
        d = row if isinstance(row, dict) else row.to_dict()
        if d.get("is_open") or d.get("exit_time") is None:
            continue
        pnl_val = d.get("pnl")
        if pnl_val is None:
            continue
        hour = _to_ct_hour(d.get("exit_time"))
        if hour is None:
            continue
        if hour not in buckets:
            buckets[hour] = {"trades": 0, "wins": 0, "pnl_sum": 0.0}
        buckets[hour]["trades"] += 1
        if float(pnl_val) > 0:
            buckets[hour]["wins"] += 1
        buckets[hour]["pnl_sum"] += float(pnl_val)

    hourly_stats = []
    for h in sorted(buckets.keys()):
        b = buckets[h]
        trades = b["trades"]
        wins = b["wins"]
        win_rate = round(wins / trades, 4) if trades else 0.0
        avg_pnl = round(b["pnl_sum"] / trades, 2) if trades else 0.0
        hourly_stats.append(
            {
                "hour": h,
                "label": _hour_label(h),
                "trades": trades,
                "wins": wins,
                "win_rate": win_rate,
                "avg_pnl": avg_pnl,
            }
        )

    best_hour = None
    worst_hour = None
    eligible = [s for s in hourly_stats if s["trades"] >= 2]
    if eligible:
        best = max(eligible, key=lambda x: x["win_rate"])
        worst = min(eligible, key=lambda x: x["win_rate"])
        best_hour = {"hour": best["hour"], "label": best["label"], "win_rate": best["win_rate"]}
        worst_hour = {"hour": worst["hour"], "label": worst["label"], "win_rate": worst["win_rate"]}

    return {"hourly_stats": hourly_stats, "best_hour": best_hour, "worst_hour": worst_hour}


@router.get(
    "/paper/streaks",
    description="Consecutive win/loss streak tracker from closed paper trades ordered chronologically.",
)
async def paper_streaks():
    """
    Return current streak, max win/loss streaks, and full streak history.

    Trades are ordered by exit_time ascending.  The current streak is the
    streak containing the most recent closed trade.
    """
    if not paper_tracker:
        return {
            "current_streak": {"type": "NONE", "count": 0},
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "streak_history": [],
            "total_trades": 0,
        }

    try:
        rows = paper_tracker.get_trade_history(limit=5000)
    except Exception as exc:
        logger.warning("paper_streaks: get_trade_history failed: %s", exc)
        rows = []

    closed: list[tuple[str, str]] = []
    for row in rows:
        d = row if isinstance(row, dict) else row.to_dict()
        if d.get("is_open") or d.get("exit_time") is None:
            continue
        pnl_val = d.get("pnl")
        if pnl_val is None:
            continue
        outcome = "WIN" if float(pnl_val) > 0 else "LOSS"
        exit_ts = str(d.get("exit_time", ""))
        exit_date = exit_ts[:10] if len(exit_ts) >= 10 else ""
        closed.append((outcome, exit_date))

    if not closed:
        return {
            "current_streak": {"type": "NONE", "count": 0},
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "streak_history": [],
            "total_trades": 0,
        }

    streak_history: list[dict] = []
    current_type = closed[0][0]
    streak_count = 0
    streak_start = closed[0][1]
    streak_end = closed[0][1]

    for outcome, exit_date in closed:
        if outcome == current_type:
            streak_count += 1
            streak_end = exit_date
        else:
            streak_history.append(
                {
                    "type": current_type,
                    "count": streak_count,
                    "start_date": streak_start,
                    "end_date": streak_end,
                }
            )
            current_type = outcome
            streak_count = 1
            streak_start = exit_date
            streak_end = exit_date

    streak_history.append(
        {
            "type": current_type,
            "count": streak_count,
            "start_date": streak_start,
            "end_date": streak_end,
        }
    )

    max_win = max((s["count"] for s in streak_history if s["type"] == "WIN"), default=0)
    max_loss = max((s["count"] for s in streak_history if s["type"] == "LOSS"), default=0)
    current = streak_history[-1]

    return {
        "current_streak": {"type": current["type"], "count": current["count"]},
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
        "streak_history": streak_history[-20:],
        "total_trades": len(closed),
    }
