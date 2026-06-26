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
