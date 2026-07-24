"""
Portfolio router - unified multi-market portfolio summary.

GET /portfolio/summary - total P&L, all markets, daily target progress
GET /portfolio/health - health status of all market modules
GET /portfolio/halt - emergency halt all markets (POST)
GET /portfolio/resume - resume after halt (POST)
GET /portfolio/risk - correlation exposure and margin utilization
GET /portfolio/paper/hourly-stats - win rate by hour-of-day (CT)
GET /portfolio/paper/streaks - consecutive win/loss streaks with history
POST /portfolio/paper/admin/close-stale - close stale test MES positions (admin only)
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from api import (
    DailyPnLResponse,
    DecisionHistoryResponse,
    DrawdownResponse,
    PaperTradeResponse,
    StatsSummaryResponse,
)
from approval.service import approved_watchlist_symbols
from config import settings
from data.provenance import DEFAULT_STALE_AFTER_S, derive_is_live
from execution.order_router import FUTURES_SYMBOLS
from utils.position_sizing import INSTRUMENT_MULTIPLIERS as INSTRUMENT_POINT_VALUES
from utils.trade_invariants import is_inverted_stop

logger = logging.getLogger("jarvis_trader.routers.portfolio")

router = APIRouter(prefix="", tags=["portfolio", "multi-market"])

TARGET_TRADING_DAYS = 30

# Global references (injected from main.py)
paper_tracker = None
db_manager = None
_data_manager = None
_safety_layer = None


def inject_dependencies(pt, dbm, dm=None, safety_layer=None):
    """Inject dependencies from main.py"""
    global paper_tracker, db_manager, _data_manager, _safety_layer
    paper_tracker = pt
    db_manager = dbm
    _data_manager = dm
    _safety_layer = safety_layer


def _ibkr_connected() -> bool | None:
    """IBKR data-leg connection state for the provenance envelope's ``is_live``
    gate — mirrors ``MarketDataManager.get_current_price_envelope``'s check.
    ``None`` (unknown) when no data manager is wired, rather than a hardcoded
    True/False that could misrepresent connectivity.
    """
    if _data_manager is None:
        return None
    return bool(getattr(_data_manager, "ibkr", None) and _data_manager.ibkr.is_connected)


@router.get("")
async def get_portfolio():
    """Current portfolio state — sourced from broker API, never from agent memory.

    ``positions`` is populated from the open paper positions, each enriched with
    a live mark and unrealized P&L via ``_compute_unrealized`` (the same helper
    ``/portfolio/summary`` and ``/paper/positions/unrealized`` use). The response
    is a plain dict (no response_model) so the frontend-facing fields
    (``avg_cost``/``market_value``/``is_futures``) survive serialization —
    the shared ``Position`` model only carries ``average_price``.
    """
    if not _safety_layer:
        raise HTTPException(503, "Safety layer not initialized")
    status = _safety_layer.get_status()
    # SafetyLayer.get_status() emits current_equity / daily_realized_pnl — NOT
    # portfolio_equity / daily_pnl (those names belong to /safety/status's
    # response shape, a different endpoint). Reading the wrong keys here always
    # fell through to the 0.0 default. See GT-01.
    equity = status.get("current_equity", 0.0)

    positions: list[dict] = []
    unrealized_total = 0.0
    if paper_tracker is not None:
        try:
            open_positions: list[dict] = paper_tracker.get_open_positions()
            if open_positions:
                symbols = [str(p.get("symbol", "")) for p in open_positions]
                if _data_manager is not None:
                    results = await asyncio.gather(
                        *[_data_manager.get_tick_price(sym) for sym in symbols],
                        return_exceptions=True,
                    )
                    marks: list[tuple[float | None, str | None]] = [
                        (
                            (
                                (r.get("last_price"), r.get("source"))
                                if isinstance(r, dict)
                                else (
                                    (float(r), None)
                                    if isinstance(r, (int, float))
                                    else (None, None)
                                )
                            )
                            if not isinstance(r, Exception) and r is not None
                            else (None, None)
                        )
                        for r in results
                    ]
                else:
                    marks = [(None, None)] * len(open_positions)

                for pos, (current_price, mark_source) in zip(
                    open_positions, marks, strict=True
                ):
                    computed = _compute_unrealized(
                        pos,
                        current_price,
                        INSTRUMENT_POINT_VALUES,
                        mark_source=mark_source,
                        ibkr_data_connected=_ibkr_connected(),
                    )
                    upnl = computed.get("unrealized_pnl")
                    if upnl:
                        unrealized_total += upnl
                    sym = computed["symbol"]
                    qty = computed["quantity"]
                    entry = computed["entry_price"]
                    cp = computed.get("current_price")
                    point_value = INSTRUMENT_POINT_VALUES.get(
                        sym, INSTRUMENT_POINT_VALUES.get("DEFAULT", 1.0)
                    )
                    mark_for_value = cp if cp is not None else entry
                    positions.append(
                        {
                            "symbol": sym,
                            "quantity": qty,
                            "avg_cost": entry,
                            "average_price": entry,  # back-compat alias
                            "current_price": cp,
                            "market_value": round(mark_for_value * point_value * qty, 2),
                            "unrealized_pnl": upnl,
                            "unrealized_pnl_pct": computed.get("unrealized_pnl_pct"),
                            "is_futures": _is_futures_symbol(sym),
                            "is_live": computed.get("is_live", False),
                            "source": computed.get("source"),
                            "as_of": computed.get("as_of"),
                            "stale_after_s": computed.get("stale_after_s"),
                        }
                    )
        except Exception as exc:
            logger.warning("get_portfolio: position enrichment failed: %s", exc)

    return {
        "total_equity": equity,
        "cash_balance": equity,
        "cash": equity,  # stable alias — dashboard's command-center page reads `cash` (GT-01)
        "unrealized_pnl": round(unrealized_total, 4),
        "realized_pnl": 0.0,
        "daily_pnl": status.get("daily_realized_pnl", 0.0),
        "margin_used": 0.0,
        "margin_available": equity,
        "positions": positions,
    }


def _is_futures_symbol(symbol: str) -> bool:
    return symbol.upper() in FUTURES_SYMBOLS


def _guard_direct_paper_open(symbol: str) -> None:
    """
    Constrain direct paper-sync opens so they cannot bypass the core safety posture.

    Close operations remain allowed so operators and sync jobs can flatten state
    even during a halt.
    """
    if settings.LIVE_TRADING_ENABLED:
        raise HTTPException(status_code=409, detail="Direct paper-trade open disabled in live mode")

    if _safety_layer is not None and _safety_layer.get_status().get("is_killed"):
        raise HTTPException(
            status_code=409, detail="Kill switch active — cannot open direct paper trade"
        )

    if _is_futures_symbol(symbol) and symbol.upper() not in approved_watchlist_symbols():
        raise HTTPException(
            status_code=400,
            detail=f"Symbol {symbol.upper()} not on approved futures watchlist",
        )


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
    "/summary",
    description="Unified multi-market P&L summary with total daily P&L, market breakdown, and daily target progress.",
)
async def portfolio_summary():
    """Unified multi-market P&L summary including unrealized P&L from open positions."""
    orch = _get_orchestrator()

    # ── Unrealized P&L from open positions ───────────────────────────────────
    unrealized_pnl = 0.0
    unrealized_marks_stale = 0
    unrealized_marks_live = 0
    if paper_tracker is not None:
        try:
            open_positions: list[dict] = paper_tracker.get_open_positions()
            if open_positions:
                symbols = [str(p.get("symbol", "")) for p in open_positions]
                if _data_manager is not None:
                    # Use tick-only path (skips TV) — /portfolio/summary fires
                    # once per open position and we care about tail latency,
                    # not necessarily the absolute freshest quote.
                    results = await asyncio.gather(
                        *[_data_manager.get_tick_price(sym) for sym in symbols],
                        return_exceptions=True,
                    )
                    # Keep the (price, source) pair so a stale CSV-cache mark can
                    # be excluded from the headline rather than fabricating P&L.
                    marks: list[tuple[float | None, str | None]] = [
                        (
                            (
                                (r.get("last_price"), r.get("source"))
                                if isinstance(r, dict)
                                else (
                                    (float(r), None)
                                    if isinstance(r, (int, float))
                                    else (None, None)
                                )
                            )
                            if not isinstance(r, Exception) and r is not None
                            else (None, None)
                        )
                        for r in results
                    ]
                else:
                    marks = [(None, None)] * len(open_positions)

                for pos, (current_price, mark_source) in zip(open_positions, marks, strict=True):
                    computed = _compute_unrealized(
                        pos,
                        current_price,
                        INSTRUMENT_POINT_VALUES,
                        mark_source=mark_source,
                        ibkr_data_connected=_ibkr_connected(),
                    )
                    if computed.get("mark_stale"):
                        unrealized_marks_stale += 1
                    if computed.get("is_live"):
                        unrealized_marks_live += 1
                    upnl = computed.get("unrealized_pnl") or 0.0
                    unrealized_pnl += upnl
        except Exception as exc:
            logger.warning("portfolio_summary: unrealized P&L fetch failed: %s", exc)

    if not orch:
        return {
            "total_daily_pnl": round(unrealized_pnl, 4),
            "realized_pnl": 0.0,
            "unrealized_pnl": round(unrealized_pnl, 4),
            "total_pnl": round(unrealized_pnl, 4),
            "daily_target": 500.0,
            "target_progress_pct": 0.0,
            "unrealized_marks_stale": unrealized_marks_stale,
            "unrealized_marks_live": unrealized_marks_live,
            "markets": {},
            "message": "Orchestrator not initialized",
        }

    summary = await orch.get_portfolio_summary()
    realized_pnl: float = summary.get("total_daily_pnl", 0.0)
    total_pnl = realized_pnl + unrealized_pnl
    daily_target: float = summary.get("daily_target") or 500.0

    summary["realized_pnl"] = round(realized_pnl, 4)
    summary["unrealized_pnl"] = round(unrealized_pnl, 4)
    summary["total_pnl"] = round(total_pnl, 4)
    summary["total_daily_pnl"] = round(total_pnl, 4)
    # >0 means some open positions were marked from a stale/unavailable feed and
    # excluded from unrealized — the degraded-state surface reads this.
    summary["unrealized_marks_stale"] = unrealized_marks_stale
    # Count of open positions currently marked from a genuine live-tier,
    # freshness-passing source (provenance envelope's is_live=True).
    summary["unrealized_marks_live"] = unrealized_marks_live
    if daily_target:
        summary["target_progress_pct"] = round(total_pnl / daily_target * 100, 2)
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


@router.get(
    "/capital",
    description="Per-market capital allocation and daily targets for the multi-market book.",
)
async def portfolio_capital():
    """Capital allocation per market for the dashboard's capital view.

    Shape matches the frontend ``CapitalAllocation`` type:
    ``{markets:{name:{capital, daily_target}}, total_capital, daily_target,
    enabled_markets}``. Sourced from each module's ``capital_allocated`` /
    ``daily_target`` and ``is_enabled()``.
    """
    orch = _get_orchestrator()
    if not orch:
        return {
            "markets": {},
            "total_capital": 0.0,
            "daily_target": 0.0,
            "enabled_markets": [],
            "message": "Orchestrator not initialized",
        }

    markets: dict[str, dict] = {}
    total_capital = 0.0
    enabled_markets: list[str] = []
    modules = getattr(orch, "_modules", {}) or {}
    for name, module in modules.items():
        try:
            cap = float(getattr(module, "capital_allocated", 0.0) or 0.0)
            tgt = float(getattr(module, "daily_target", 0.0) or 0.0)
            markets[name] = {"capital": cap, "daily_target": tgt}
            total_capital += cap
            if module.is_enabled():
                enabled_markets.append(name)
        except Exception as exc:
            logger.warning("portfolio_capital: module %s failed: %s", name, exc)
            markets[name] = {"capital": 0.0, "daily_target": 0.0}

    return {
        "markets": markets,
        "total_capital": round(total_capital, 2),
        "daily_target": float(getattr(orch, "daily_target", 0.0) or 0.0),
        "enabled_markets": enabled_markets,
    }


# GET /portfolio/stats/streaks - canonical handler is on the FastAPI app in main.py (StreakBadge).


@router.get(
    "/stats/paper-phase-summary",
    description="Paper validation phase rollup with balance, return percentage, trading days, and validation status.",
)
async def paper_phase_summary():
    """
    Paper validation phase rollup: balance, return, distinct trading days, status.

    Reads from SQLite when available (single source of truth for P&L history).
    Falls back to in-memory tracker on DB error or if no DB configured.
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
    # SQLite-first approach: query DB for authoritative trade history (Bug B9 / US-2004)
    if db_manager:
        try:
            rows = db_manager.get_trade_history(limit=5000)
        except Exception as exc:
            logger.warning(
                "paper_phase_summary: SQLite get_trade_history failed, using in-memory: %s", exc
            )
            rows = []

    # Fallback to in-memory if no DB rows or DB unavailable
    if not rows:
        try:
            rows = paper_tracker.get_trade_history(limit=5000)
        except Exception as exc:
            logger.warning("paper_phase_summary: in-memory get_trade_history failed: %s", exc)
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
        # Compute profit_factor from the same closed_rows used for total_pnl so
        # the validation_status gate is consistent with SQLite (Bug B9 / US-2504).
        pf: Any = None
        if closed_rows:
            try:
                row_pnls = [_row_pnl(r) for r in closed_rows]
                gross_profit = sum(p for p in row_pnls if p > 0)
                gross_loss = abs(sum(p for p in row_pnls if p <= 0))
                pf = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
            except Exception as exc:
                logger.warning("paper_phase_summary: profit_factor from rows failed: %s", exc)
                pf = None
        if pf is None:
            # Last-resort fallback to in-memory tracker
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
    """Open paper positions — DB-authoritative, reconciled against the tracker.

    The returned ``positions``/``count`` reflect ``paper_trades WHERE
    status='open'`` (the durable source of truth) when a DB is wired, so the UI
    can no longer show "no positions" while a row is open. ``reconciliation``
    surfaces any drift between the DB and the in-memory tracker.
    """
    if not paper_tracker:
        return {
            "positions": [],
            "count": 0,
            "reconciliation": {"source": "none", "reconciled": True},
        }
    # Prefer the authoritative reconciled read; fall back to in-memory if the
    # tracker predates the method (defensive — never 500 this endpoint).
    if hasattr(paper_tracker, "get_open_positions_authoritative"):
        positions, recon = paper_tracker.get_open_positions_authoritative()
    else:  # pragma: no cover - legacy tracker
        positions = paper_tracker.get_open_positions()
        recon = {"source": "memory", "reconciled": True, "count": len(positions)}

    # Enrich with a live mark + unrealized P&L + provenance envelope, same
    # helper/waterfall as /portfolio and /portfolio/summary, so OpenPositionsWidget
    # (which reads this endpoint) is no longer stuck rendering "—" for P&L and can
    # show the honest live/stale/static badge instead of a bare number.
    if positions and _data_manager is not None:
        try:
            symbols = [str(p.get("symbol", "")) for p in positions]
            results = await asyncio.gather(
                *[_data_manager.get_tick_price(sym) for sym in symbols],
                return_exceptions=True,
            )
            marks: list[tuple[float | None, str | None]] = [
                (
                    (
                        (r.get("last_price"), r.get("source"))
                        if isinstance(r, dict)
                        else ((float(r), None) if isinstance(r, (int, float)) else (None, None))
                    )
                    if not isinstance(r, Exception) and r is not None
                    else (None, None)
                )
                for r in results
            ]
            ibkr_connected = _ibkr_connected()
            for pos, (current_price, mark_source) in zip(positions, marks, strict=True):
                computed = _compute_unrealized(
                    pos,
                    current_price,
                    INSTRUMENT_POINT_VALUES,
                    mark_source=mark_source,
                    ibkr_data_connected=ibkr_connected,
                )
                pos["current_price"] = computed.get("current_price")
                pos["unrealized_pnl"] = computed.get("unrealized_pnl")
                pos["unrealized_pnl_pct"] = computed.get("unrealized_pnl_pct")
                pos["is_live"] = computed.get("is_live", False)
                pos["source"] = computed.get("source")
                pos["as_of"] = computed.get("as_of")
                pos["stale_after_s"] = computed.get("stale_after_s")
        except Exception as exc:
            logger.warning("paper_positions: mark enrichment failed: %s", exc)

    return {"positions": positions, "count": len(positions), "reconciliation": recon}


class UpdatePositionRequest(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None


@router.patch("/paper/positions/{trade_id}")
async def update_position(trade_id: str, req: UpdatePositionRequest):
    """Update stop_loss / take_profit on an open position (in-memory + SQLite)."""
    if not paper_tracker:
        raise HTTPException(status_code=503, detail="Paper tracker not available")

    # Update in-memory trade
    trade = paper_tracker._open.get(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"No open position with trade_id={trade_id!r}")

    # In-memory Trade uses ``action``; falling back to ``side`` keeps the
    # guard robust if the attribute is ever renamed or a test fake uses ``side``.
    trade_side = getattr(trade, "action", None) or getattr(trade, "side", None)
    if req.stop_loss is not None and is_inverted_stop(
        trade_side,
        getattr(trade, "entry_price", None),
        req.stop_loss,
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Inverted stop_loss rejected: side={trade_side} "
                f"entry_price={trade.entry_price} stop_loss={req.stop_loss}. "
                "For longs the stop must be below entry; for shorts, above. "
                "See docs/incident-notes/2026-04-09-mcl-inverted-stop.md"
            ),
        )

    if req.stop_loss is not None:
        trade.stop_loss = req.stop_loss
    if req.take_profit is not None:
        trade.take_profit = req.take_profit

    # Persist to SQLite
    try:
        if db_manager is not None:
            with db_manager._lock:
                conn = db_manager._connect()
                try:
                    conn.execute(
                        "UPDATE paper_trades SET stop_loss=?, take_profit=? WHERE trade_id=?",
                        (trade.stop_loss, trade.take_profit, trade_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
    except Exception as exc:
        logger.warning("update_position: SQLite write failed for %s: %s", trade_id[:8], exc)

    return {
        "trade_id": trade_id,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "status": "updated",
    }


@router.get(
    "/paper/trades",
    description="Paper trade history from SQLite. Optional status filter: 'open' or 'closed'.",
)
async def get_paper_trades(limit: int = 50, status: str = None):
    """Get paper trade history from SQLite."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        trades = db_manager.get_paper_trades(limit=limit, status=status)
        return {"trades": trades, "count": len(trades)}
    except Exception as exc:
        logger.error("get_paper_trades failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/paper/performance")
async def paper_performance():
    """
    Closed-trade performance summary with mark-to-market unrealized P&L.

    Computes metrics from SQLite when db_manager is available (single source of truth).
    Falls back to in-memory tracker on DB error.
    Includes unrealized_pnl for all open positions via current market prices.
    """
    if not paper_tracker:
        return {"performance": {}}

    # ── Mark-to-market unrealized P&L ────────────────────────────────────────
    unrealized_pnl = 0.0
    open_positions_detail: list[dict] = []
    open_positions: list[dict] = paper_tracker.get_open_positions()
    if open_positions and _data_manager is not None:
        try:
            symbols = [str(p.get("symbol", "")) for p in open_positions]
            price_results = await asyncio.gather(
                *[_data_manager.get_current_price(sym) for sym in symbols],
                return_exceptions=True,
            )
            for pos, price_result in zip(open_positions, price_results, strict=False):
                current_price = (
                    price_result.get("last_price") if isinstance(price_result, dict) else None
                )
                mark_source = price_result.get("source") if isinstance(price_result, dict) else None
                computed = _compute_unrealized(
                    pos,
                    current_price,
                    INSTRUMENT_POINT_VALUES,
                    mark_source=mark_source,
                    ibkr_data_connected=_ibkr_connected(),
                )
                upnl = computed.get("unrealized_pnl") or 0.0
                unrealized_pnl += upnl
                open_positions_detail.append(
                    {
                        "symbol": computed["symbol"],
                        "direction": computed["direction"],
                        "entry_price": computed["entry_price"],
                        "current_price": computed["current_price"],
                        "unrealized_pnl": round(upnl, 4),
                        "is_live": computed.get("is_live", False),
                        "source": computed.get("source"),
                        "as_of": computed.get("as_of"),
                        "stale_after_s": computed.get("stale_after_s"),
                    }
                )
        except Exception as exc:
            logger.warning("paper_performance: unrealized P&L fetch failed: %s", exc)

    # ── Closed-trade metrics ──────────────────────────────────────────────────
    # SQLite-first approach: query DB for closed trades if available (Bug B9 / US-2004)
    if db_manager:
        try:
            rows = db_manager.get_trade_history(limit=5000)
            if rows:
                # Filter to closed trades and compute performance from DB
                closed = [r for r in rows if r.get("exit_price") is not None]
                pnls = [float(r.get("pnl", 0)) for r in closed if r.get("pnl") is not None]

                if pnls:
                    wins = [p for p in pnls if p > 0]
                    losses = [p for p in pnls if p <= 0]
                    gross_profit = sum(wins) if wins else 0.0
                    gross_loss = abs(sum(losses)) if losses else 0.0
                    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

                    peak = 0.0
                    equity = 0.0
                    max_dd = 0.0
                    for p in pnls:
                        equity += p
                        if equity > peak:
                            peak = equity
                        dd = equity - peak
                        if dd < max_dd:
                            max_dd = dd

                    total_closed_pnl = round(sum(pnls), 4)
                    performance = {
                        "total_pnl": total_closed_pnl,
                        "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
                        "profit_factor": (
                            round(profit_factor, 4) if profit_factor is not None else None
                        ),
                        "num_trades": len(pnls),
                        "num_open": len(open_positions),
                        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
                        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
                        "max_dd": round(max_dd, 4),
                        "best_trade": round(max(pnls), 4) if pnls else None,
                        "worst_trade": round(min(pnls), 4) if pnls else None,
                        "unrealized_pnl": round(unrealized_pnl, 4),
                        "total_pnl_including_open": round(total_closed_pnl + unrealized_pnl, 4),
                        "open_positions": open_positions_detail,
                    }
                    return {"performance": performance}
        except Exception as exc:
            logger.warning("paper_performance: SQLite query failed, using in-memory: %s", exc)

    # Fallback to in-memory tracker — augment with unrealized
    perf = paper_tracker.get_performance()
    perf["unrealized_pnl"] = round(unrealized_pnl, 4)
    perf["total_pnl_including_open"] = round((perf.get("total_pnl") or 0.0) + unrealized_pnl, 4)
    perf["open_positions"] = open_positions_detail
    return {"performance": perf}


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
        _guard_direct_paper_open(sym)
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
        except ValueError as exc:
            # ExitPriceSanityError (phantom-price guard) subclasses ValueError —
            # reject a corrupt exit with 422 rather than letting it 500.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        # Mixed-provenance rows: some timestamps carry tzinfo, some are naive
        # UTC — naive minus aware raises TypeError, so normalize both to UTC.
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        if exit_dt.tzinfo is None:
            exit_dt = exit_dt.replace(tzinfo=timezone.utc)
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
    """Daily P&L rollup for closed trades, last 90 days.

    SQLite is the single source of truth (Bug B9 / US-2504).  Falls back to
    the in-memory tracker only when no db_manager is wired.
    """
    empty = {"daily_pnl": [], "total_days_traded": 0, "positive_days": 0, "negative_days": 0}
    if not paper_tracker:
        return empty

    rows: list[Any] = []
    if db_manager:
        try:
            rows = db_manager.get_trade_history(limit=5000)
        except Exception as exc:
            logger.warning(
                "get_daily_pnl: SQLite get_trade_history failed, using in-memory: %s", exc
            )
            rows = []

    if not rows:
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
    "/risk",
    description="Portfolio correlation exposure, margin utilization, and daily P&L.",
)
async def get_portfolio_risk():
    """
    Return current portfolio risk metrics including correlation-aware position sizing.

    Response includes:
    - instruments: List of all configured instruments
    - correlation_matrix: Instrument pair correlations
    - active_positions: Current open positions by symbol
    - correlation_reduction_active: Whether MNQ+MES sizing rule is in effect
    - total_margin_utilization: Percentage of available margin used
    - daily_pnl_pct: Daily P&L as percentage of account
    """
    try:
        from orchestrator.position_correlation import PositionCorrelationMonitor

        # Initialize correlation monitor with config values
        pairs = settings.INSTRUMENT_CORRELATION_PAIRS
        threshold = settings.CORRELATION_THRESHOLD
        monitor = PositionCorrelationMonitor(
            correlation_pairs=pairs,
            correlation_threshold=threshold,
            default_max_contracts=settings.MAX_CONTRACTS_PER_INSTRUMENT,
            correlated_max_contracts=settings.CORRELATED_PAIR_MAX_CONTRACTS,
        )

        # Get current positions (simplified; in production would integrate with
        # actual position tracker from paper_tracker or db_manager)
        open_positions = {}
        daily_pnl = 0.0
        margin_used = 0.0

        if paper_tracker:
            try:
                trades = paper_tracker.get_trade_history(limit=1000)
                for trade in trades:
                    t = trade if isinstance(trade, dict) else trade.to_dict()
                    if not t.get("is_open"):
                        # Accumulate closed trade P&L for daily calc
                        pnl = t.get("pnl")
                        if pnl and isinstance(pnl, (int, float)):
                            daily_pnl += float(pnl)

                # Try to get current positions (if paper_tracker exposes them)
                if hasattr(paper_tracker, "get_positions"):
                    positions = await paper_tracker.get_positions()
                    for pos in positions:
                        sym = pos.symbol if hasattr(pos, "symbol") else pos.get("symbol")
                        qty = pos.qty if hasattr(pos, "qty") else pos.get("qty", 0)
                        if sym:
                            monitor.update_position(sym, qty)
                            open_positions[sym] = qty
            except Exception as exc:
                logger.warning("Error fetching position data: %s", exc)

        # Calculate margin utilization as percentage
        # (simplified: in production would use broker margin data)
        account_value = settings.INITIAL_CAPITAL
        if paper_tracker and hasattr(paper_tracker, "get_account_value"):
            try:
                account_value = await paper_tracker.get_account_value()
            except Exception:
                pass

        daily_pnl_pct = (daily_pnl / account_value * 100) if account_value > 0 else 0.0

        # Build response
        correlation_exposure = monitor.get_correlation_exposure()

        return {
            "instruments": list(settings.FUTURES_WATCHLIST),
            "correlation_matrix": pairs,
            "correlation_threshold": threshold,
            "active_positions": open_positions,
            "open_symbol_count": correlation_exposure["open_count"],
            "correlation_reduction_active": correlation_exposure["correlation_reduction_active"],
            "default_max_contracts": settings.MAX_CONTRACTS_PER_INSTRUMENT,
            "correlated_max_contracts": settings.CORRELATED_PAIR_MAX_CONTRACTS,
            "total_margin_utilization": min(margin_used / 40.0 * 100, 100.0),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "account_value": round(account_value, 2),
        }

    except Exception as exc:
        logger.error("Error in get_portfolio_risk: %s", exc)
        raise HTTPException(status_code=500, detail=f"Risk calculation failed: {exc}") from exc


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
    """Recent closed paper trades for dashboards, including review grade."""
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

        trade_id = d.get("trade_id")
        grade: str | None = None
        review_status: str | None = None
        if db_manager and trade_id:
            try:
                review_row = db_manager.get_trade_review(trade_id)
                if review_row:
                    grade = review_row.get("grade")
                    review_status = review_row.get("review_status")
            except Exception:
                pass

        out.append(
            {
                # New canonical field names
                "timestamp": ts,
                "action": action,
                "price": float(price or 0),
                "pnl": d.get("pnl"),
                "trade_id": trade_id,
                "grade": grade,
                "review_status": review_status,
                # Legacy aliases — kept for BestWorstTradeWidget / TradeCalendarWidget
                "symbol": d.get("symbol", ""),
                "side": action,
                "quantity": float(d.get("quantity") or 0),
                "entry_price": float(d.get("entry_price") or 0),
                "exit_price": d.get("exit_price"),
                "realized_pnl": d.get("pnl"),
                "status": "OPEN" if d.get("is_open") else "CLOSED",
                "entry_time": d.get("entry_time") or ts,
                "exit_time": d.get("exit_time"),
                "notes": d.get("notes"),
                "id": d.get("id"),
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

    current_streak = {"type": current_type, "count": streak_count}
    max_win_streak = max((s["count"] for s in streak_history if s["type"] == "WIN"), default=0)
    max_loss_streak = max((s["count"] for s in streak_history if s["type"] == "LOSS"), default=0)

    return {
        "current_streak": current_streak,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "streak_history": streak_history,
        "total_trades": len(closed),
    }


# ── Admin endpoints ───────────────────────────────────────────────────────────

STALE_SYMBOL = "MES"
STALE_ENTRY_PRICE = 5800.0


@router.get(
    "/pnl-snapshot",
    description="Current daily P&L snapshot from SQLite persistence layer (survives engine restarts).",
)
async def get_pnl_snapshot():
    """
    Return today’s P&L snapshot from the pnl_snapshots SQLite table.

    This reflects the last state persisted by the SafetyLayer’s sync_from_broker()
    call, which runs every 60 seconds. The snapshot survives engine restarts so
    intraday drawdown tracking is not lost on restart.
    """
    today_str = date.today().isoformat()

    if db_manager is None:
        return {
            "date": today_str,
            "daily_pnl": 0.0,
            "portfolio_equity": 0.0,
            "peak_equity": 0.0,
            "drawdown_pct": 0.0,
            "consecutive_losses": 0,
            "last_updated": None,
            "source": "no_db",
        }

    try:
        snap = db_manager.get_pnl_snapshot(today_str)
    except Exception as exc:
        logger.warning("get_pnl_snapshot: DB read failed: %s", exc)
        snap = None

    if snap is None:
        return {
            "date": today_str,
            "daily_pnl": 0.0,
            "portfolio_equity": 0.0,
            "peak_equity": 0.0,
            "drawdown_pct": 0.0,
            "consecutive_losses": 0,
            "last_updated": None,
            "source": "no_snapshot",
        }

    portfolio_equity = float(snap.get("portfolio_equity", 0.0))
    peak_equity = float(snap.get("peak_equity", 0.0))
    drawdown_pct = 0.0
    if peak_equity > 0 and portfolio_equity < peak_equity:
        drawdown_pct = round((portfolio_equity - peak_equity) / peak_equity * 100, 4)

    return {
        "date": snap.get("date", today_str),
        "daily_pnl": round(float(snap.get("daily_pnl", 0.0)), 4),
        "portfolio_equity": round(portfolio_equity, 4),
        "peak_equity": round(peak_equity, 4),
        "drawdown_pct": drawdown_pct,
        "consecutive_losses": int(snap.get("consecutive_losses", 0)),
        "last_updated": snap.get("updated_at"),
        "source": "sqlite",
    }


@router.post("/paper/admin/close-stale")
async def close_stale_positions():
    """
    Close stale test MES positions at 5800.0 that were created during
    Sprint 18/19 testing.  Sets exit_price = entry_price (zero P&L) so
    they do not distort win-rate or profit-factor metrics.

    Returns {"status": "success", "closed_count": N}.
    """
    if not paper_tracker:
        return {"status": "success", "closed_count": 0}

    try:
        open_pos = paper_tracker.get_open_positions()
        stale_ids: list[str] = []
        for pos in open_pos:
            p = pos if isinstance(pos, dict) else (pos.to_dict() if hasattr(pos, "to_dict") else {})
            sym = str(p.get("symbol", "")).upper()
            try:
                entry = float(p.get("entry_price", -1))
            except (TypeError, ValueError):
                entry = -1.0
            if sym == STALE_SYMBOL and abs(entry - STALE_ENTRY_PRICE) < 0.01:
                tid = p.get("trade_id")
                if tid:
                    stale_ids.append(str(tid))

        closed_count = 0
        for trade_id in stale_ids:
            try:
                paper_tracker.close_trade(trade_id, STALE_ENTRY_PRICE)
                closed_count += 1
            except Exception as exc:
                logger.warning("close_stale_positions: could not close %s: %s", trade_id, exc)

        logger.info(
            "close_stale_positions: closed %d stale %s positions", closed_count, STALE_SYMBOL
        )
        return {"status": "success", "closed_count": closed_count}
    except Exception as exc:
        logger.error("close_stale_positions failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UnrealizedPositionResponse(BaseModel):
    trade_id: str
    symbol: str
    action: str
    quantity: float
    entry_price: float
    current_price: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    stop_loss: float | None
    take_profit: float | None
    stop_distance: float | None
    target_distance: float | None
    entry_time: str
    direction: str
    entry_suspect: bool = False
    mark_suspect: bool = False
    mark_stale: bool = False
    mark_source: str | None = None
    # Provenance envelope (Phase 1) — see data/provenance.py / dashboard/lib/provenance.ts.
    is_live: bool = False
    source: str | None = None
    as_of: float | None = None
    stale_after_s: float = DEFAULT_STALE_AFTER_S

    model_config = ConfigDict(from_attributes=True)


# Contaminated-entry guard (2026-06-12 phantom-aggregate fix). A paper position
# can be recorded at the IB snapshot sentinel (100.5) or another non-fill price;
# trusting it makes unrealized P&L explode and poison /portfolio/summary (one MES
# position at 100.5 vs a real ~7414 mark fabricated +$36,568). Mirror the
# bars_repository sentinel and reject an implausible entry before computing P&L.
_IB_SNAPSHOT_SENTINEL = 100.5
#: Entry/mark ratio beyond this is contamination, not a real move (symbol-agnostic).
_EXTREME_ENTRY_DIVERGENCE = 5.0

#: get_tick_price() sources that are NOT a live quote — a stale daily close
#: (CSV cache fallback) or no data at all. A position marked from one of these
#: must not drive the live unrealized P&L headline: while the IBKR data leg was
#: degraded on 2026-06-16, get_tick_price fell through to the Tier-5 csv_cache
#: last-daily-close (MGC ~3757 vs a real ~4311 mark), fabricating a -$11,076
#: unrealized that poisoned /portfolio/summary.total_daily_pnl. Realized P&L and
#: the risk/kill-switch path are unaffected (separate date-filtered DB source).
_STALE_MARK_SOURCES = frozenset(
    {"csv_cache", "unavailable", "polygon_cache_expired", "ibkr_historical"}
)


def _entry_is_suspect(entry_price: float, current_price: float | None) -> bool:
    """True if an entry price is implausible and must not drive unrealized P&L."""
    if entry_price <= 0:
        return True
    if entry_price == _IB_SNAPSHOT_SENTINEL:
        return True
    if current_price is not None and current_price > 0:
        hi, lo = max(entry_price, current_price), min(entry_price, current_price)
        if lo > 0 and hi / lo > _EXTREME_ENTRY_DIVERGENCE:
            return True
    return False


#: A mark that implies a larger fractional move than this from the entry is treated
#: as a data error (wrong-scale / cross-wired / stale tick), NOT a real move, and
#: must not drive unrealized P&L. A position cannot plausibly move this far on a
#: liquid micro future within a session; a live MES short at 5299.875 received a
#: 7521.75 mark (+41.9%) that fabricated -$11,109 unrealized and poisoned
#: /portfolio/summary's headline daily P&L while passing the looser 5x entry-
#: divergence guard (7521/5299 = 1.42x) (2026-06-16). Symbol-agnostic; generous
#: enough to never reject a believable single-session futures move.
_IMPLAUSIBLE_MARK_MOVE = 0.30


def _mark_is_suspect(entry_price: float, current_price: float | None) -> bool:
    """True if a mark price is implausible vs the entry and must not drive P&L.

    Distinct from `_entry_is_suspect`: here the entry is a valid fill but the
    *current price* is the contamination. A missing mark (None) is not suspect —
    absence is handled separately and simply yields no unrealized P&L.
    """
    if current_price is None:
        return False
    if current_price <= 0:
        return True
    if entry_price > 0 and abs(current_price - entry_price) / entry_price > _IMPLAUSIBLE_MARK_MOVE:
        return True
    return False


def _compute_unrealized(
    pos: dict,
    current_price: float | None,
    point_values: dict,
    mark_source: str | None = None,
    ibkr_data_connected: bool | None = None,
) -> dict:
    """Compute unrealized P&L fields for one position.

    ``mark_source`` is the get_tick_price() source tag for ``current_price``. A
    stale mark (CSV-cache daily close / no data) is flagged ``mark_stale`` and
    does NOT produce an unrealized_pnl number, so it cannot poison the portfolio
    aggregate when the live data leg is degraded. That P&L-blocking gate
    (``_STALE_MARK_SOURCES``) is intentionally left untouched here — it is
    incident-hardened (see the module comments above) and stricter changes to
    it are out of scope.

    Additionally builds the data-provenance envelope fields (``is_live``,
    ``source``, ``as_of``, ``stale_after_s``) via ``derive_is_live`` (Phase 1
    envelope, ``engine/data/provenance.py``) so the dashboard can render the
    mark with the same honest live/stale/static badge every other price panel
    uses (see ``dashboard/lib/provenance.ts`` / ``<DataValue>``), instead of a
    portfolio-router-only ``mark_stale`` boolean nothing else understands.
    ``LIVE_SOURCES`` and ``_STALE_MARK_SOURCES`` are disjoint, so
    ``is_live=True`` always implies ``mark_stale=False`` — the new envelope
    field never contradicts the existing P&L gate above.
    """
    symbol = str(pos.get("symbol", "")).upper()
    action = str(pos.get("action", "") or pos.get("side", "") or "").lower()
    quantity = float(pos.get("quantity", 1) or 1)
    entry_price = float(pos.get("entry_price", 0) or 0)
    stop_loss = pos.get("stop_loss") or pos.get("stop_price")
    take_profit = pos.get("take_profit") or pos.get("target_price")
    entry_time = str(pos.get("entry_time") or pos.get("created_at") or "")
    trade_id = str(pos.get("trade_id") or pos.get("id") or "")

    # Direction
    if action in ("buy", "buy_to_open", "long", "buy_to_close"):
        direction = "LONG"
    elif action in ("sell", "sell_to_open", "short", "sell_to_close"):
        direction = "SHORT"
    else:
        direction = "LONG"

    point_value = point_values.get(symbol, point_values.get("DEFAULT", 1.0))

    # Reject contaminated entries (sentinel / non-positive / extreme divergence)
    # so one corrupt position can't fabricate a phantom portfolio aggregate.
    entry_suspect = _entry_is_suspect(entry_price, current_price)
    # Reject an implausible MARK the same way — the entry can be a real fill while
    # the current price is the data error (wrong-scale / stale tick).
    mark_suspect = _mark_is_suspect(entry_price, current_price)
    # Reject stale marks (CSV-cache daily close / no data) for the same reason —
    # a weeks-old close is not a live mark and must not drive unrealized P&L.
    mark_stale = mark_source in _STALE_MARK_SOURCES

    # Provenance envelope (Phase 1). ``as_of`` is "now" when a price was
    # actually fetched — every call site here fetches synchronously per
    # request (no background cache to be stale relative to), so the only
    # honest freshness signal is "did we get a value this call", not an age
    # since some earlier poll. Mirrors ``get_current_price_envelope``'s own
    # as_of semantics (set at fetch time via ``_mark_symbol_fresh``).
    as_of = time.time() if current_price is not None else None
    is_live = derive_is_live(
        mark_source,
        as_of,
        DEFAULT_STALE_AFTER_S,
        ibkr_data_connected=ibkr_data_connected,
    )

    # Unrealized P&L
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    if current_price is not None and not entry_suspect and not mark_suspect and not mark_stale:
        if direction == "LONG":
            unrealized_pnl = (current_price - entry_price) * point_value * quantity
        else:
            unrealized_pnl = (entry_price - current_price) * point_value * quantity
        denom = entry_price * point_value * quantity
        if denom != 0:
            unrealized_pnl_pct = (unrealized_pnl / denom) * 100

    # Distance to stop / target
    stop_distance: float | None = None
    target_distance: float | None = None
    if stop_loss is not None and current_price is not None:
        try:
            stop_distance = abs(current_price - float(stop_loss))
        except (TypeError, ValueError):
            pass
    if take_profit is not None and current_price is not None:
        try:
            target_distance = abs(float(take_profit) - current_price)
        except (TypeError, ValueError):
            pass

    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "entry_price": entry_price,
        "current_price": current_price,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "stop_loss": float(stop_loss) if stop_loss is not None else None,
        "take_profit": float(take_profit) if take_profit is not None else None,
        "stop_distance": stop_distance,
        "target_distance": target_distance,
        "entry_time": entry_time,
        "direction": direction,
        "entry_suspect": entry_suspect,
        "mark_suspect": mark_suspect,
        "mark_stale": mark_stale,
        "mark_source": mark_source,
        # Provenance envelope (Phase 1) — canonical is_live/source/as_of shape
        # consumed by dashboard/lib/provenance.ts's classifyProvenance().
        "is_live": is_live,
        "source": mark_source or "unavailable",
        "as_of": as_of,
        "stale_after_s": DEFAULT_STALE_AFTER_S,
    }


@router.get("/paper/positions/unrealized", response_model=list[UnrealizedPositionResponse])
async def get_unrealized_positions() -> list[UnrealizedPositionResponse]:
    """
    Return all open paper positions enriched with current price and unrealized P&L.
    Prices are fetched concurrently via asyncio.gather. Returns [] if no positions.
    """
    try:
        if paper_tracker is None:
            return []

        positions: list[dict] = paper_tracker.get_open_positions()
        if not positions:
            return []

        # Fetch current prices concurrently
        symbols = [str(p.get("symbol", "")) for p in positions]
        if _data_manager is not None:
            results = await asyncio.gather(
                *[_data_manager.get_current_price(sym) for sym in symbols],
                return_exceptions=True,
            )
            marks = [
                (
                    (
                        (r.get("last_price"), r.get("source"))
                        if isinstance(r, dict)
                        else ((float(r), None) if isinstance(r, (int, float)) else (None, None))
                    )
                    if not isinstance(r, Exception) and r is not None
                    else (None, None)
                )
                for r in results
            ]
        else:
            marks = [(None, None)] * len(positions)

        enriched = []
        for pos, (current_price, mark_source) in zip(positions, marks, strict=True):
            computed = _compute_unrealized(
                pos,
                current_price,
                INSTRUMENT_POINT_VALUES,
                mark_source=mark_source,
                ibkr_data_connected=_ibkr_connected(),
            )
            enriched.append(UnrealizedPositionResponse(**computed))

        return enriched

    except Exception as exc:
        logger.error("[UnrealizedPnL] Endpoint error: %s", exc)


# ── Parallel paper A/B stats endpoint ────────────────────────────────────────


class AccountStatsResponse(BaseModel):
    """Stats for one paper account over a rolling window."""

    model_config = ConfigDict(extra="ignore")

    account_id: str = Field(..., description="'A' or 'B'")
    days: int
    n_trades: int
    win_rate: float | None = None
    sortino: float | None = None
    sharpe: float | None = None
    calmar: float | None = None
    max_dd: float | None = None
    equity_curve: list[dict] = Field(default_factory=list, description="[{date, equity}]")


@router.get(
    "/paper/account/{account_id}/stats",
    response_model=AccountStatsResponse,
    tags=["portfolio", "parallel-paper"],
    description=(
        "Parallel paper testing stats for one account (A or B) over a rolling window. "
        "Account B is only populated when ENABLE_PARALLEL_PAPER=1."
    ),
)
async def get_paper_account_stats(
    account_id: str,
    days: int = 30,
) -> AccountStatsResponse:
    """
    Return rolling performance stats for paper account A or B.

    Reads closed trades from paper_trades WHERE account_id = ? over the
    requested window, computes basic tearsheet metrics in-process.
    No external dependency — pure SQLite + math.
    """
    import math
    from datetime import date, timedelta

    from analytics import metrics  # canonical guarded Sharpe/Calmar (PR #272 invariants)

    if account_id not in {"A", "B"}:
        raise HTTPException(status_code=400, detail="account_id must be 'A' or 'B'")
    if days < 1 or days > 730:
        raise HTTPException(status_code=400, detail="days must be between 1 and 730")

    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database not available")

    cutoff = (date.today() - timedelta(days=days)).isoformat()

    try:
        with db_manager._lock:
            conn = db_manager._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT pnl, exit_time
                    FROM paper_trades
                    WHERE status = 'closed'
                      AND account_id = ?
                      AND exit_time >= ?
                    ORDER BY exit_time ASC
                    """,
                    (account_id, cutoff),
                ).fetchall()
            finally:
                conn.close()
    except Exception as exc:
        logger.error("[AccountStats] DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    pnls = [float(r["pnl"] or 0.0) for r in rows]
    n_trades = len(pnls)

    if n_trades == 0:
        return AccountStatsResponse(
            account_id=account_id,
            days=days,
            n_trades=0,
        )

    wins = [p for p in pnls if p > 0]
    win_rate = len(wins) / n_trades

    # Equity curve — cumulative P&L grouped by date
    equity_curve_map: dict[str, float] = {}
    for r in rows:
        day = str(r["exit_time"] or "")[:10]
        pnl_val = float(r["pnl"] or 0.0)
        equity_curve_map[day] = equity_curve_map.get(day, 0.0) + pnl_val

    cumulative = 0.0
    equity_curve: list[dict] = []
    for day in sorted(equity_curve_map):
        cumulative += equity_curve_map[day]
        equity_curve.append({"date": day, "equity": round(cumulative, 4)})

    # Max drawdown as a fraction of the running peak. The equity curve here is
    # cumulative P&L (starts at 0), so a % drawdown is only meaningful once a
    # positive peak exists — guarding on peak > 0 avoids the divide-by-1e-9
    # blowup that produced nonsense like -1.46e14 when P&L was always negative.
    peak = 0.0
    max_dd: float | None = None
    for pt in equity_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak
            if max_dd is None or dd < max_dd:
                max_dd = dd

    # Sortino (downside deviation; annualised assuming daily returns)
    mean_pnl = sum(pnls) / n_trades
    neg_sq = [(p - mean_pnl) ** 2 for p in pnls if p < mean_pnl]
    downside_dev = math.sqrt(sum(neg_sq) / len(neg_sq)) if neg_sq else None
    sortino: float | None = (mean_pnl / downside_dev * math.sqrt(252)) if downside_dev else None

    # Sharpe (std dev of all returns) — canonical module (near-zero std-dev guard -> None)
    sharpe: float | None = metrics.sharpe(pnls)

    # Calmar (annualised return / abs max drawdown). abs(max_dd) is floored at
    # CALMAR_MIN_DD_FLOOR (0.5%) before dividing -- an account that's mostly
    # winning with only a razor-thin dip (e.g. max_dd = -0.0001) combined with
    # a healthy annualized return otherwise explodes into millions (e.g.
    # 2,014,774.72). Below the floor, Calmar is undefined -- report None
    # (dashboard renders "--") rather than a fabricated ratio.
    # NOTE (#272<>#274 merge): keep PR #272's explicit block. The canonical
    # metrics.calmar() floor was aligned 1e-6 -> 0.005 to match, so the two now
    # agree; this inline additionally enforces the max_dd < 0 guard (count real
    # drawdowns only). metrics.sharpe() above uses the canonical module.
    CALMAR_MIN_DD_FLOOR = 0.005
    calmar: float | None = None
    if max_dd is not None and max_dd < 0 and abs(max_dd) >= CALMAR_MIN_DD_FLOOR:
        ann_return = mean_pnl * 252
        calmar = ann_return / abs(max_dd)

    return AccountStatsResponse(
        account_id=account_id,
        days=days,
        n_trades=n_trades,
        win_rate=round(win_rate, 4),
        sortino=round(sortino, 4) if sortino is not None else None,
        sharpe=round(sharpe, 4) if sharpe is not None else None,
        calmar=round(calmar, 4) if calmar is not None else None,
        max_dd=round(max_dd, 4) if max_dd is not None else None,
        equity_curve=equity_curve,
    )


# ── Paper Trade Manual Submit ─────────────────────────────────────────────


class PaperTradeRequest(BaseModel):
    symbol: str
    action: str  # "buy" | "sell" | "sell_short" | "buy_to_cover"
    quantity: float
    price: float
    notes: str = ""
    close_trade_id: str | None = None


@router.post("/paper/trade/manual", response_model=PaperTradeResponse)
async def submit_paper_trade(req: PaperTradeRequest):
    """
    Open or close a paper trade.\n
    - If close_trade_id is omitted (or null):  opens a new position.
    - If close_trade_id is provided:           closes that position at req.price.\n
    """
    if not paper_tracker:
        raise HTTPException(503, "Paper tracker not initialized")

    if req.close_trade_id:
        try:
            trade = paper_tracker.close_trade(req.close_trade_id, req.price)
        except KeyError as e:
            raise HTTPException(404, f"No open trade with id={req.close_trade_id!r}") from e
        except ValueError as e:
            # ExitPriceSanityError (phantom-price guard) subclasses ValueError.
            raise HTTPException(422, str(e)) from e

        try:
            from notifications.whatsapp import format_trade_closed_alert, send_whatsapp_message

            duration_min = None
            if trade.entry_time:
                try:
                    from dateutil import parser as dtparser

                    entry_dt = dtparser.parse(trade.entry_time)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                    duration_min = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60
                except Exception:
                    pass

            msg = format_trade_closed_alert(
                symbol=trade.symbol,
                side=trade.action,
                quantity=int(trade.quantity),
                entry_price=float(trade.entry_price),
                exit_price=float(trade.exit_price),
                pnl=float(trade.pnl),
                duration_minutes=duration_min,
            )
            asyncio.create_task(send_whatsapp_message(msg))
        except Exception:
            pass

        return {"status": "closed", "trade": trade.to_dict()}
    else:
        if settings.LIVE_TRADING_ENABLED:
            raise HTTPException(409, "Direct paper-trade open disabled in live mode")
        if _safety_layer and _safety_layer.get_status().get("is_killed"):
            raise HTTPException(409, "Kill switch active — cannot open direct paper trade")
        if (
            req.symbol.upper() in FUTURES_SYMBOLS
            and req.symbol.upper() not in approved_watchlist_symbols()
        ):
            raise HTTPException(
                400,
                f"Symbol {req.symbol.upper()} not on approved futures watchlist",
            )
        trade_id = paper_tracker.open_trade(
            symbol=req.symbol,
            action=req.action,
            quantity=req.quantity,
            price=req.price,
            notes=req.notes,
        )
        return {
            "status": "opened",
            "trade_id": trade_id,
            "symbol": req.symbol.upper(),
            "action": req.action,
            "quantity": req.quantity,
            "entry_price": req.price,
        }


# ── Historical Query Endpoints ─────────────────────────────────────────────


@router.get("/history/daily-pnl", response_model=DailyPnLResponse)
async def get_history_daily_pnl(days: int = 30):
    """Return daily P&L snapshots for the last N days."""
    if not db_manager:
        return {"daily_pnl": [], "days": days, "note": "db_manager not initialized"}
    try:
        records = db_manager.get_daily_pnl(days=days)
        return {"daily_pnl": records, "days": days, "count": len(records)}
    except Exception as exc:
        logger.error(f"[DB] get_daily_pnl failed: {exc}")
        return {"daily_pnl": [], "days": days, "error": str(exc)}


@router.get("/history/equity-curve")
async def get_history_equity_curve(days: int = 90):
    """Equity-curve points derived from daily P&L snapshots.

    Shape consumed by the dashboard PerformancePanel: {points: [{date, equity}]}.
    """
    if not db_manager:
        return {"points": [], "days": days, "note": "db_manager not initialized"}
    try:
        records = db_manager.get_daily_pnl(days=days)
        points = [
            {"date": r.get("date"), "equity": r.get("ending_balance")}
            for r in sorted(records, key=lambda r: str(r.get("date", "")))
            if r.get("date") is not None and r.get("ending_balance") is not None
        ]
        return {"points": points, "days": days, "count": len(points)}
    except Exception as exc:
        logger.error(f"[DB] get_history_equity_curve failed: {exc}")
        return {"points": [], "days": days, "error": str(exc)}


@router.get("/history/decisions", response_model=DecisionHistoryResponse)
async def get_decision_history(limit: int = 50, symbol: str = ""):
    """Return historical agent decisions from SQLite."""
    if not db_manager:
        return {"decisions": [], "count": 0, "note": "db_manager not initialized"}
    try:
        decisions = db_manager.get_decisions(
            limit=limit,
            symbol=symbol.upper() if symbol else None,
        )
        return {"decisions": decisions, "count": len(decisions)}
    except Exception as exc:
        logger.error(f"[DB] get_decisions failed: {exc}")
        return {"decisions": [], "count": 0, "error": str(exc)}


@router.get("/stats/summary", response_model=StatsSummaryResponse)
async def get_stats_summary():
    """Aggregate performance summary from SQLite — win rate, total P&L, trade counts."""
    if not db_manager:
        return {"note": "db_manager not initialized"}
    try:
        summary = db_manager.get_stats_summary()
        return summary
    except Exception as exc:
        logger.error(f"[DB] get_stats_summary failed: {exc}")
        return {"error": str(exc)}


@router.get("/stats/drawdown", response_model=DrawdownResponse)
async def get_drawdown():
    """Return max drawdown and the equity curve used to compute it."""
    if not db_manager:
        return {"max_drawdown": 0.0, "equity_curve": [], "note": "db_manager not initialized"}
    try:
        drawdown = db_manager.get_drawdown()
        return drawdown
    except Exception as exc:
        logger.error(f"[DB] get_drawdown failed: {exc}")
        return {"max_drawdown": 0.0, "equity_curve": [], "error": str(exc)}


@router.get("/stats/streaks")
async def get_trading_streaks():
    """Calculate current and maximum win/loss streaks from closed trades."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                rows = conn.execute(
                    """SELECT pnl FROM paper_trades
                       WHERE status = 'closed' AND pnl IS NOT NULL
                       ORDER BY exit_time ASC"""
                ).fetchall()
            finally:
                conn.close()

        if not rows:
            return {
                "current_streak": 0,
                "current_type": "none",
                "max_win_streak": 0,
                "max_loss_streak": 0,
                "total_trades": 0,
                "recent_results": [],
            }

        pnls = [r[0] for r in rows]
        results = ["W" if p > 0 else "L" for p in pnls]

        current_type = results[-1]
        current = 0
        for r in reversed(results):
            if r == current_type:
                current += 1
            else:
                break

        max_win = max_loss = win_run = loss_run = 0
        for r in results:
            if r == "W":
                win_run += 1
                loss_run = 0
            else:
                loss_run += 1
                win_run = 0
            max_win = max(max_win, win_run)
            max_loss = max(max_loss, loss_run)

        return {
            "current_streak": current,
            "current_type": "win" if current_type == "W" else "loss",
            "max_win_streak": max_win,
            "max_loss_streak": max_loss,
            "total_trades": len(results),
            "recent_results": results[-10:],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats/session-today")
async def get_todays_session():
    """Get today's trading session stats (current calendar day in CT)."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        import pytz

        ct = pytz.timezone("America/Chicago")
        now_ct = datetime.now(ct)
        today_ct = now_ct.strftime("%Y-%m-%d")

        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                cursor = conn.execute(
                    """SELECT pnl, side, symbol, quantity, entry_price, exit_price, entry_time, exit_time
                       FROM paper_trades
                       WHERE status = 'closed'
                         AND date(exit_time) = ?
                       ORDER BY exit_time ASC""",
                    (today_ct,),
                )
                cols = [d[0] for d in cursor.description]
                trades = [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]

                cursor2 = conn.execute(
                    """SELECT symbol, side, quantity, entry_price, entry_time
                       FROM paper_trades
                       WHERE status = 'open'
                         AND date(entry_time) = ?""",
                    (today_ct,),
                )
                cols2 = [d[0] for d in cursor2.description]
                open_today = [dict(zip(cols2, row, strict=False)) for row in cursor2.fetchall()]
            finally:
                conn.close()

        pnls = [float(t.get("pnl", 0) or 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        gross_pnl = sum(pnls)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / len(pnls) if pnls else None

        return {
            "date": today_ct,
            "session": "RTH" if 8 <= now_ct.hour < 15 else "EXTENDED",
            "closed_trades": len(trades),
            "open_trades": len(open_today),
            "gross_pnl": round(gross_pnl, 2),
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "best_trade": round(max(pnls), 2) if pnls else None,
            "worst_trade": round(min(pnls), 2) if pnls else None,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "symbols_traded": list({t.get("symbol") for t in trades}),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats/weekly")
async def get_weekly_stats():
    """Rolling 7-day trade statistics for the paper trading phase."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with db_manager._lock:
            conn = db_manager._connect()
            try:
                cursor = conn.execute(
                    "SELECT pnl, symbol FROM paper_trades WHERE status = 'closed' AND exit_time >= ? ORDER BY exit_time DESC",
                    (cutoff,),
                )
                cols = [d[0] for d in cursor.description]
                trades = [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]
            finally:
                conn.close()

        pnls = [float(t.get("pnl", 0) or 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        total = len(pnls)
        win_rate = round(len(wins) / total, 4) if total else 0.0
        return {
            "period": "7d",
            "total_trades": total,
            "wins": len(wins),
            "losses": len([p for p in pnls if p < 0]),
            "win_rate": win_rate,
            "gross_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / total, 2) if total else 0.0,
            "symbols": list({t.get("symbol") for t in trades}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats/commissions")
async def get_commission_stats():
    """Estimate total commissions paid during paper trading phase."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        RATES = {"MES": 1.57, "MNQ": 1.57, "MCL": 2.05, "DEFAULT": 1.57}
        trades = db_manager.get_trade_history(limit=10000)
        total_commissions = 0.0
        by_symbol: dict[str, float] = {}
        for t in trades:
            sym = (t.get("symbol") or "").upper()
            qty = int(t.get("quantity") or 1)
            rate = RATES.get(sym, RATES["DEFAULT"])
            commission = rate * qty * 2
            total_commissions += commission
            by_symbol[sym] = by_symbol.get(sym, 0.0) + commission

        gross_pnl = sum(float(t.get("pnl") or 0) for t in trades if t.get("status") == "closed")
        net_pnl = gross_pnl - total_commissions

        return {
            "total_commissions": round(total_commissions, 2),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "by_symbol": {k: round(v, 2) for k, v in by_symbol.items()},
            "trade_count": len(trades),
            "avg_commission_per_trade": round(total_commissions / max(len(trades), 1), 2),
            "rates": RATES,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/import/trades")
async def import_paper_trades(request: Request):
    """Bulk import paper trades from JSON array."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        body = await request.json()
        trades = body.get("trades", [])
        if not isinstance(trades, list):
            raise HTTPException(status_code=400, detail="'trades' must be a list")
        if len(trades) > 1000:
            raise HTTPException(status_code=400, detail="Max 1000 trades per import")

        imported = 0
        errors = []

        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                for i, t in enumerate(trades):
                    try:
                        import uuid as _uuid

                        trade_id = t.get("trade_id") or str(_uuid.uuid4())
                        conn.execute(
                            """INSERT OR IGNORE INTO paper_trades
                               (trade_id, symbol, side, entry_price, exit_price, quantity,
                                pnl, status, entry_time, exit_time, strategy_params, notes)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                trade_id,
                                str(t.get("symbol", "UNKNOWN")),
                                str(t.get("action", t.get("side", "LONG"))),
                                float(t.get("entry_price", 0)),
                                float(t.get("exit_price", 0)),
                                int(t.get("quantity", 1)),
                                float(t.get("pnl", 0)),
                                "CLOSED",
                                str(t.get("entry_time", datetime.now(timezone.utc).isoformat())),
                                str(t.get("exit_time", datetime.now(timezone.utc).isoformat())),
                                str(t.get("strategy", t.get("strategy_params", "imported"))),
                                str(t.get("notes", "")),
                            ),
                        )
                        imported += 1
                    except Exception as e:
                        errors.append({"index": i, "error": str(e)})
                conn.commit()
            finally:
                conn.close()

        return {"imported": imported, "skipped": len(errors), "errors": errors[:10]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
