"""Phase 1c — `/trading-status` endpoint: the honest 'what's trading now' surface.

Thin wiring around ``services.trading_status``. Pulls the three canonical
authorities — ``paper_config.PAPER_CONFIGS`` (enabled), ``signals.DO_NOT_TRADE_SYMBOLS``
(authorized), and the gate-v2 verdict ledger via ``strategy_ledger_router.find_verdict``
— and returns one reconciled row per symbol plus a roll-up summary, flagging any
config split-brain. Read-only; no engine state mutated.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter

from services.trading_status import build_trading_status, summarize
from services.trading_status_live import build_live_status, summarize_live

logger = logging.getLogger("jarvis_trader.routers.trading_status")

router = APIRouter(tags=["trading-status"])


def _enabled_for(symbol: str) -> bool:
    from backtest.paper_config import PAPER_CONFIGS

    cfg = PAPER_CONFIGS.get(symbol) or {}
    return bool(cfg.get("enabled", False))


def _authorized_for(symbol: str) -> bool:
    from backtest.signals import DO_NOT_TRADE_SYMBOLS

    return symbol not in DO_NOT_TRADE_SYMBOLS


def _verdict_for(symbol: str) -> Optional[dict[str, Any]]:
    # find_verdict already returns None on malformed/missing files; the extra
    # guard makes the endpoint resilient to an unexpected reader failure.
    try:
        from routers.strategy_ledger_router import find_verdict

        return find_verdict(symbol)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trading-status: verdict lookup failed for %s: %s", symbol, exc)
        return None


def _all_symbols() -> list[str]:
    from backtest.paper_config import PAPER_CONFIGS
    from backtest.signals import DO_NOT_TRADE_SYMBOLS

    return sorted(set(PAPER_CONFIGS) | set(DO_NOT_TRADE_SYMBOLS))


@router.get(
    "/trading-status",
    summary="Honest per-symbol trading status (enabled · authorized · gate verdict · agreement)",
)
def get_trading_status() -> dict[str, Any]:
    statuses = build_trading_status(
        _all_symbols(),
        enabled_for=_enabled_for,
        authorized_for=_authorized_for,
        verdict_for=_verdict_for,
        now=datetime.now(timezone.utc),
    )
    return {
        "summary": summarize(statuses),
        "symbols": [s.to_dict() for s in statuses],
    }


# ---------------------------------------------------------------------------
# Live-state wiring (Phase 1c live-state) — sync local reads only, never a
# broker round-trip. Each source is wrapped so a malformed row or a missing
# table degrades to a safe default rather than 500-ing the whole surface.
# ---------------------------------------------------------------------------


def _last_signal_for(symbol: str) -> Optional[dict[str, Any]]:
    try:
        from database import get_db

        rows = get_db().get_decisions(symbol=symbol, limit=1)
        return rows[0] if rows else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trading-status/live: signal lookup failed for %s: %s", symbol, exc)
        return None


def _last_order_for(symbol: str) -> Optional[dict[str, Any]]:
    try:
        from database import get_db

        rows = get_db().fetch_all(
            "SELECT * FROM paper_trades WHERE symbol = ? ORDER BY entry_time DESC LIMIT 1",
            (symbol,),
        )
        return rows[0] if rows else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trading-status/live: order lookup failed for %s: %s", symbol, exc)
        return None


def _open_position_for(symbol: str) -> Optional[dict[str, Any]]:
    try:
        from database import get_db

        rows = get_db().get_open_trades(symbol=symbol)
        return rows[0] if rows else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trading-status/live: position lookup failed for %s: %s", symbol, exc)
        return None


def _realized_pnl_for(symbol: str) -> Optional[float]:
    try:
        from database import get_db

        rows = get_db().fetch_all(
            "SELECT COALESCE(SUM(pnl), 0.0) AS realized FROM paper_trades "
            "WHERE symbol = ? AND status = 'closed'",
            (symbol,),
        )
        if rows and rows[0].get("realized") is not None:
            return round(float(rows[0]["realized"]), 2)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trading-status/live: pnl lookup failed for %s: %s", symbol, exc)
        return None


def _account_pnl() -> Optional[dict[str, Any]]:
    """Most-recent daily P&L snapshot (account-level), or None. Pure SQLite read."""
    try:
        from database import get_db

        row = get_db().get_latest_daily_pnl()
        if not row:
            return None
        return {
            "date": row.get("date"),
            "realized_pnl": row.get("realized_pnl"),
            "unrealized_pnl": row.get("unrealized_pnl"),
            "ending_balance": row.get("ending_balance"),
            "max_drawdown": row.get("max_drawdown"),
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trading-status/live: account pnl lookup failed: %s", exc)
        return None


@router.get(
    "/trading-status/live",
    summary="Per-symbol trading status + live runtime state (signal · order · position · P&L)",
)
def get_trading_status_live() -> dict[str, Any]:
    """The unified Phase 1c pane: config reconciliation merged with runtime state.

    Each symbol row carries the config view (enabled · authorized · verdict + age)
    plus a nested ``live`` block (last signal · last order · open position ·
    realized P&L). All reads are local (DB / in-memory); no broker round-trip, so
    the surface stays fast and can't block on a gateway."""
    now = datetime.now(timezone.utc)
    symbols = _all_symbols()

    config = build_trading_status(
        symbols,
        enabled_for=_enabled_for,
        authorized_for=_authorized_for,
        verdict_for=_verdict_for,
        now=now,
    )
    live = build_live_status(
        symbols,
        last_signal_for=_last_signal_for,
        last_order_for=_last_order_for,
        open_position_for=_open_position_for,
        realized_pnl_for=_realized_pnl_for,
        now=now,
    )
    live_by_symbol = {s.symbol: s for s in live}

    rows: list[dict[str, Any]] = []
    for cfg in config:
        row = cfg.to_dict()
        ls = live_by_symbol.get(cfg.symbol)
        row["live"] = (
            {k: v for k, v in ls.to_dict().items() if k != "symbol"} if ls is not None else None
        )
        rows.append(row)

    return {
        "summary": {
            **summarize(config),
            "live": summarize_live(live),
            "account_pnl": _account_pnl(),
        },
        "symbols": rows,
    }
