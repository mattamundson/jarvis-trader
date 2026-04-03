"""
Brokers router — consolidated position view across IBKR and Schwab.

GET /brokers/positions — combined live + paper positions with reconciliation
GET /brokers/status   — connectivity status for all brokers
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/brokers", tags=["brokers"])

# Module-level refs injected by main.py at startup
_ibkr = None
_schwab = None
_tracker = None


def inject_dependencies(ibkr=None, schwab=None, tracker=None) -> None:
    """Wire connector and tracker singletons in from main.py lifespan."""
    global _ibkr, _schwab, _tracker
    _ibkr = ibkr
    _schwab = schwab
    _tracker = tracker
    logger.info(
        "brokers_router deps injected — IBKR: %s | Schwab: %s | tracker: %s",
        _ibkr is not None,
        _schwab is not None,
        _tracker is not None,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ibkr_connected() -> bool:
    return _ibkr is not None and _ibkr.is_connected()


def _schwab_connected() -> bool:
    return _schwab is not None and _schwab.is_connected


def _normalise_ibkr_position(raw: dict) -> dict:
    """Map IBGatewayConnector position dict to the unified schema."""
    return {
        "symbol": raw.get("symbol", ""),
        "quantity": raw.get("position", 0),
        "avg_price": raw.get("avg_cost"),
        "market_price": raw.get("market_price"),
        "unrealized_pnl": raw.get("unrealized_pnl"),
        "sec_type": raw.get("sec_type", "FUT"),
    }


def _normalise_schwab_position(raw: dict) -> dict:
    """Map SchwabConnector position dict to the unified schema."""
    instrument = raw.get("instrument", {})
    symbol = instrument.get("symbol") or raw.get("symbol", "")
    return {
        "symbol": symbol,
        "quantity": raw.get("longQuantity", raw.get("quantity", 0)),
        "avg_price": raw.get("averagePrice"),
        "market_price": raw.get("marketValue"),
        "unrealized_pnl": raw.get("currentDayProfitLoss"),
        "sec_type": instrument.get("assetType", "EQUITY"),
    }


def _normalise_paper_position(raw: dict) -> dict:
    """Map PaperTrade.to_dict() to the unified schema."""
    action = raw.get("action", "buy").lower()
    direction = "LONG" if action in ("buy", "buy_to_open") else "SHORT"
    return {
        "trade_id": raw.get("trade_id", ""),
        "symbol": raw.get("symbol", ""),
        "direction": direction,
        "quantity": raw.get("quantity", 0),
        "entry_price": raw.get("entry_price"),
        "entry_time": raw.get("entry_time"),
    }


def _build_reconciliation(
    ibkr_positions: list,
    schwab_positions: list,
    paper_positions: list,
) -> dict:
    """
    Flag mismatches between paper tracker and live broker positions.

    A discrepancy is raised when:
    - A paper position exists for a symbol but neither live broker reports it.
    - A live broker position exists but no corresponding paper position is open.
    """
    live_symbols: set[str] = set()
    for p in ibkr_positions:
        live_symbols.add(p["symbol"].upper())
    for p in schwab_positions:
        live_symbols.add(p["symbol"].upper())

    paper_symbols: set[str] = {p["symbol"].upper() for p in paper_positions}

    discrepancies = []

    for sym in paper_symbols - live_symbols:
        discrepancies.append({
            "symbol": sym,
            "type": "paper_only",
            "detail": "Paper position open but no matching live broker position found.",
        })

    for sym in live_symbols - paper_symbols:
        discrepancies.append({
            "symbol": sym,
            "type": "live_only",
            "detail": "Live broker position found but no corresponding paper record.",
        })

    return {
        "discrepancies": discrepancies,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/positions",
    summary="Combined IBKR + Schwab + paper position view",
    description=(
        "Fetches live positions from IBKR (futures) and Schwab (equities/options), "
        "reads open paper-tracker trades, and returns a reconciliation diff."
    ),
)
async def get_broker_positions():
    """Return unified position view across all brokers plus paper tracker."""
    try:
        # IBKR positions
        ibkr_raw: list = []
        if _ibkr_connected():
            try:
                ibkr_raw = await _ibkr.get_positions() or []
            except Exception as exc:
                logger.warning("IBKR get_positions failed: %s", exc)

        ibkr_normalised = [_normalise_ibkr_position(p) for p in ibkr_raw]

        # Schwab positions
        schwab_raw: list = []
        if _schwab_connected():
            try:
                schwab_raw = await _schwab.get_positions() or []
            except Exception as exc:
                logger.warning("Schwab get_positions failed: %s", exc)

        schwab_normalised = [_normalise_schwab_position(p) for p in schwab_raw]

        # Paper tracker positions
        paper_raw: list = []
        if _tracker is not None:
            try:
                paper_raw = _tracker.get_open_positions() or []
            except Exception as exc:
                logger.warning("Paper tracker get_open_positions failed: %s", exc)

        paper_normalised = [_normalise_paper_position(p) for p in paper_raw]

        reconciliation = _build_reconciliation(
            ibkr_normalised, schwab_normalised, paper_normalised
        )

        return {
            "ibkr": {
                "connected": _ibkr_connected(),
                "positions": ibkr_normalised,
            },
            "schwab": {
                "connected": _schwab_connected(),
                "positions": schwab_normalised,
            },
            "paper": {
                "positions": paper_normalised,
            },
            "reconciliation": reconciliation,
        }

    except Exception as exc:
        logger.exception("brokers/positions failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Position retrieval failed: {exc}") from exc


@router.get(
    "/status",
    summary="Broker connectivity status",
    description="Returns connection state for IBKR, Schwab, and the OrderRouter.",
)
async def get_broker_status():
    """Return connectivity status for all brokers."""
    try:
        schwab_state = "DISCONNECTED"
        if _schwab is not None and hasattr(_schwab, "state"):
            schwab_state = _schwab.state.value

        futures_broker = "ibkr" if _ibkr_connected() else "unavailable"
        equity_broker = "schwab" if _schwab_connected() else "unavailable"

        return {
            "ibkr": {
                "connected": _ibkr_connected(),
                "port": 4002,
                "mode": "paper",
            },
            "schwab": {
                "connected": _schwab_connected(),
                "state": schwab_state,
            },
            "order_router": {
                "futures_broker": futures_broker,
                "equity_broker": equity_broker,
            },
        }

    except Exception as exc:
        logger.exception("brokers/status failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Broker status check failed: {exc}") from exc
