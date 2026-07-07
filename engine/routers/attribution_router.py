"""
Attribution Router — read-only P&L decomposition endpoints.

All endpoints are GET-only and require X-API-Key authentication (via
APIKeyMiddleware already mounted globally on the app).

Endpoints:
  GET /attribution/daily?date=YYYY-MM-DD       single-day attribution
  GET /attribution/window?days=N               rolling N-day attribution (JSON)
  GET /attribution/window?days=N&format=markdown  vault-ready Markdown
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attribution", tags=["attribution"])

# ── Resolve DB path at import time (same pattern as other routers) ────────────


def _default_db_path() -> str:
    from pathlib import Path

    env_path = os.environ.get("DB_PATH", "")
    if env_path:
        return env_path
    return str(Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db")


# ── Response models ───────────────────────────────────────────────────────────


class DailyAttributionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: str
    total_pnl: float
    n_trades: int
    attribution: dict[str, float]
    top_contributor: str | None
    residual: float
    attributed_trade_count: int
    unattributed_trade_count: int


class AnalystWindowStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: float
    mean: float
    std: float
    max_loss: float
    win_rate_top: float


class WindowAttributionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_date: str
    end_date: str
    days_with_trades: int
    total_pnl: float
    n_trades: int
    per_analyst: dict[str, AnalystWindowStats]
    top_contributor_by_abs: str
    daily: list[DailyAttributionResponse]


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/daily", response_model=DailyAttributionResponse)
def get_daily_attribution(
    date: str = Query(
        default=None,
        description="ISO date YYYY-MM-DD. Defaults to today.",
    ),
) -> DailyAttributionResponse:
    """
    Return P&L attribution for all closed paper trades on a single calendar date.

    Pro-rata weights come from analyst_signals in strategy_params JSON stored at
    trade-entry time. Residual captures slippage, gap moves, and trades without
    a stored verdict.
    """
    from analytics.risk_attribution import attribute_daily_pnl

    try:
        target = _parse_date(date) if date else _today()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}") from exc

    try:
        result = attribute_daily_pnl(target, db_path=_default_db_path())
    except Exception as exc:
        logger.error("[attribution_router] daily attribution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Attribution error: {exc}") from exc

    return DailyAttributionResponse(
        date=result.date,
        total_pnl=result.total_pnl,
        n_trades=result.n_trades,
        attribution=result.attribution,
        top_contributor=result.top_contributor,
        residual=result.residual,
        attributed_trade_count=result.attributed_trade_count,
        unattributed_trade_count=result.unattributed_trade_count,
    )


@router.get("/window", response_model=None)
def get_window_attribution(
    days: int = Query(default=30, ge=1, le=365, description="Rolling window in calendar days."),
    format: str = Query(default="json", description="Response format: json or markdown."),
):
    """
    Return rolling N-day P&L attribution summary.

    Pass format=markdown for vault-ingestible Markdown output (gbrain / Obsidian).
    """
    from analytics.risk_attribution import attribute_window, format_markdown

    end = _today()
    start = end - timedelta(days=days - 1)

    try:
        window = attribute_window(start, end, db_path=_default_db_path())
    except Exception as exc:
        logger.error("[attribution_router] window attribution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Attribution error: {exc}") from exc

    if format.lower() == "markdown":
        md = format_markdown(window)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    # Build Pydantic response
    per_analyst_typed = {
        slot: AnalystWindowStats(**stats) for slot, stats in window.per_analyst.items()
    }
    daily_typed = [
        DailyAttributionResponse(
            date=d.date,
            total_pnl=d.total_pnl,
            n_trades=d.n_trades,
            attribution=d.attribution,
            top_contributor=d.top_contributor,
            residual=d.residual,
            attributed_trade_count=d.attributed_trade_count,
            unattributed_trade_count=d.unattributed_trade_count,
        )
        for d in window.daily
    ]
    return WindowAttributionResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        days_with_trades=window.days_with_trades,
        total_pnl=window.total_pnl,
        n_trades=window.n_trades,
        per_analyst=per_analyst_typed,
        top_contributor_by_abs=window.top_contributor_by_abs,
        daily=daily_typed,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _today() -> date:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).date()


def _parse_date(s: str) -> date:
    from datetime import datetime

    return datetime.strptime(s, "%Y-%m-%d").date()
