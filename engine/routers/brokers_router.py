"""
Brokers router — consolidated position view across IBKR and Schwab.

GET  /brokers/positions  — combined live + paper positions with reconciliation
GET  /brokers/status     — connectivity status for all brokers
GET  /brokers/executions — cached IBKR fills from ibkr_fills table
POST /brokers/reconcile  — pull live fills from IBKR and import into ibkr_fills
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/brokers", tags=["brokers"])

# Module-level refs injected by main.py at startup
_ibkr = None  # IBGatewayConnector (mock, for paper-sim order routing)
_data_manager = None  # MarketDataManager — holds the real ib_async connection
# at .ibkr (an IBKRDataConnector), reassigned by data_manager.initialize()
# ASYNCHRONOUSLY, after inject_dependencies() runs. Snapshotting `.ibkr` once
# here (as 2026-08-11's #608 did) freezes on the pre-initialize None/stale
# value forever -- read it lazily via _real_ibkr() below instead, same
# reasoning already applied to _reconciler just below.
#
# Also: IBKRDataConnector.is_connected is a @property (no parens);
# IBGatewayManager.is_connected (used elsewhere, e.g. safety_layer._ib_gateway)
# is a plain method (calls with parens). #608 called `_real_ibkr.is_connected()`
# assuming the IBGatewayManager convention -- on an IBKRDataConnector that's
# either a silent short-circuit to False (when the snapshot was None) or a
# TypeError. IBKRDataConnector also had no get_positions() at all before this
# fix (data-only connector) -- added below, mirroring
# IBGatewayManager.get_positions()'s reqPositionsAsync()+cache-fallback
# hardening (2026-08-03 incident).
_schwab = None
_tracker = None
_reconciler = None  # IBKRReconciler — lazily created on first use


def _real_ibkr():
    """Lazily resolve the live ib_async data connection. See _data_manager
    comment above for why this can't be a snapshot taken at injection time."""
    return getattr(_data_manager, "ibkr", None) if _data_manager is not None else None


def inject_dependencies(
    ibkr=None, schwab=None, tracker=None, data_manager=None, db_path: str = ""
) -> None:
    """Wire connector and tracker singletons in from main.py lifespan."""
    global _ibkr, _data_manager, _schwab, _tracker, _reconciler
    _ibkr = ibkr
    _data_manager = data_manager
    _schwab = schwab
    _tracker = tracker
    # Reconciler holds data_manager (not ibkr) because ibkr is initialized
    # asynchronously in background after this call — resolved lazily on use.
    if data_manager is not None and db_path:
        from execution.ibkr_reconciler import IBKRReconciler

        _reconciler = IBKRReconciler(db_path, data_manager)
    logger.info(
        "brokers_router deps injected — IBKR mock: %s | data_manager: %s | Schwab: %s | tracker: %s | reconciler: %s",
        _ibkr is not None,
        data_manager is not None,
        _schwab is not None,
        _tracker is not None,
        _reconciler is not None,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ibkr_connected() -> bool:
    """Live IBKR connectivity — backed by the real ib_async connection
    (`_real_ibkr()`), not the paper-sim order-routing mock (`_ibkr`). Those two
    are unrelated: the mock can report connected=True with zero relationship
    to whether the actual Gateway session is up. `.is_connected` is a
    property on IBKRDataConnector (no parens) — see the _data_manager
    comment above."""
    real = _real_ibkr()
    return real is not None and bool(real.is_connected)


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
    ibkr_connected: bool,
    schwab_connected: bool,
) -> dict:
    """
    Flag mismatches between paper tracker and live broker positions.

    A discrepancy is raised when:
    - A paper position exists for a symbol but neither live broker reports it.
    - A live broker position exists but no corresponding paper position is open.
    - A symbol is present on BOTH sides but the signed quantities differ
      (qty_mismatch) — e.g. paper believes LONG 2 while the broker is SHORT 3.
      Without this check a same-symbol sign/size divergence reads as "in sync".
    - Neither broker is queryable (blind state — empty discrepancy lists are NOT
      a clean state, they are a no-data state, surfaced explicitly).

    Returns a dict with:
      - discrepancies: list of mismatch entries
      - health: "ok" | "partial" | "blind" — data quality of this reconciliation
      - ibkr_queryable / schwab_queryable: which sides we could read
    """
    last_checked = datetime.now(timezone.utc).isoformat()

    # Blind state — neither broker queryable; an empty discrepancy list here is
    # silent failure (see project_tracker_broker_drift_2026_04_24.md). Surface it.
    if not ibkr_connected and not schwab_connected:
        return {
            "discrepancies": [
                {
                    "symbol": None,
                    "type": "all_brokers_disconnected",
                    "detail": (
                        "Cannot reconcile — neither IBKR nor Schwab is connected. "
                        "An empty discrepancy list is NOT a clean state; it's a blind state."
                    ),
                }
            ],
            "health": "blind",
            "ibkr_queryable": False,
            "schwab_queryable": False,
            "last_checked": last_checked,
        }

    # Signed-quantity maps so a same-symbol size/sign divergence is detectable.
    # IBKR `quantity` is already signed (long +, short -); paper carries an
    # unsigned `quantity` plus a LONG/SHORT `direction`, so we sign it here.
    def _to_float(v) -> float:
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    live_qty: dict[str, float] = {}
    for p in ibkr_positions:
        sym = p["symbol"].upper()
        live_qty[sym] = live_qty.get(sym, 0.0) + _to_float(p.get("quantity"))
    for p in schwab_positions:
        sym = p["symbol"].upper()
        live_qty[sym] = live_qty.get(sym, 0.0) + _to_float(p.get("quantity"))

    paper_qty: dict[str, float] = {}
    for p in paper_positions:
        sym = p["symbol"].upper()
        qty = abs(_to_float(p.get("quantity")))
        signed = qty if str(p.get("direction", "LONG")).upper() == "LONG" else -qty
        paper_qty[sym] = paper_qty.get(sym, 0.0) + signed

    live_symbols: set[str] = set(live_qty)
    paper_symbols: set[str] = set(paper_qty)

    discrepancies = []

    for sym in paper_symbols - live_symbols:
        discrepancies.append(
            {
                "symbol": sym,
                "type": "paper_only",
                "detail": "Paper position open but no matching live broker position found.",
            }
        )

    for sym in live_symbols - paper_symbols:
        discrepancies.append(
            {
                "symbol": sym,
                "type": "live_only",
                "detail": "Live broker position found but no corresponding paper record.",
            }
        )

    # Symbol present on BOTH sides but signed quantities diverge.
    for sym in paper_symbols & live_symbols:
        p_qty = paper_qty[sym]
        l_qty = live_qty[sym]
        if abs(p_qty - l_qty) > 1e-9:
            discrepancies.append(
                {
                    "symbol": sym,
                    "type": "qty_mismatch",
                    "paper_qty": p_qty,
                    "live_qty": l_qty,
                    "delta": p_qty - l_qty,
                    "detail": (
                        "Paper and live broker positions differ in signed quantity "
                        f"(paper={p_qty:+g}, live={l_qty:+g}). Possible missed fill, "
                        "double-count, or sign error."
                    ),
                }
            )

    health = "ok" if (ibkr_connected and schwab_connected) else "partial"

    return {
        "discrepancies": discrepancies,
        "health": health,
        "ibkr_queryable": ibkr_connected,
        "schwab_queryable": schwab_connected,
        "last_checked": last_checked,
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
        # Snapshot connection state once -- avoids drift if the underlying
        # connectors flap during a single request, and lets the reconciler
        # see the same "queryable" answer the response reports.
        ibkr_conn = _ibkr_connected()
        schwab_conn = _schwab_connected()

        # IBKR positions
        ibkr_raw: list = []
        if ibkr_conn:
            try:
                ibkr_raw = await _real_ibkr().get_positions() or []
            except Exception as exc:
                logger.warning("IBKR get_positions failed: %s", exc)

        ibkr_normalised = [_normalise_ibkr_position(p) for p in ibkr_raw]

        # Schwab positions
        schwab_raw: list = []
        if schwab_conn:
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
            ibkr_normalised,
            schwab_normalised,
            paper_normalised,
            ibkr_connected=ibkr_conn,
            schwab_connected=schwab_conn,
        )

        return {
            "ibkr": {
                "connected": ibkr_conn,
                "positions": ibkr_normalised,
            },
            "schwab": {
                "connected": schwab_conn,
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


@router.get(
    "/executions",
    summary="Cached IBKR execution fills",
    description=(
        "Returns fills previously imported from IB via POST /brokers/reconcile. "
        "Reads only from the local ibkr_fills table — does NOT hit the live gateway."
    ),
)
async def get_executions(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. MES"),
    account: Optional[str] = Query(None, description="Filter by account ID, e.g. DUP662235"),
    limit: int = Query(200, ge=1, le=1000, description="Max rows returned"),
):
    """Return fills from the ibkr_fills cache table."""
    if _reconciler is None:
        return {
            "fills": [],
            "count": 0,
            "message": "Reconciler not initialised — engine started without real IBKR gateway or db_path.",
        }
    try:
        fills = _reconciler.get_fills(symbol=symbol, account=account, limit=limit)
        return {"fills": fills, "count": len(fills)}
    except Exception as exc:
        logger.exception("brokers/executions failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Execution fetch failed: {exc}") from exc


@router.post(
    "/reconcile",
    summary="Pull live IBKR fills and import into ibkr_fills",
    description=(
        "Calls reqExecutionsAsync() on the live IB gateway and upserts new fills "
        "into the ibkr_fills table keyed by exec_id (idempotent). "
        "Returns a summary: imported (new), skipped (duplicate), total_in_db."
    ),
)
async def reconcile_fills():
    """Import live IBKR execution fills into the local cache."""
    if _reconciler is None:
        raise HTTPException(
            status_code=503,
            detail="Reconciler not initialised — engine started without real IBKR gateway.",
        )
    try:
        result = await _reconciler.reconcile()
        return result
    except Exception as exc:
        logger.exception("brokers/reconcile failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Reconcile failed: {exc}") from exc


class _CSVImportRequest(BaseModel):
    csv_path: str
    statement_date: str = "20260529"


@router.post(
    "/import-csv-positions",
    summary="Import IBKR open futures positions from activity-statement CSV",
    description=(
        "Parses an IBKR activity-statement CSV and imports open Futures positions "
        "as synthetic fills keyed by 'CSV_POS_{account}_{symbol}_{date}' (idempotent). "
        "Use to bootstrap ibkr_fills with pre-existing positions that pre-date the "
        "live reconciler (e.g. DUP662235 demo positions from a downloaded statement)."
    ),
)
async def import_csv_positions(req: _CSVImportRequest):
    """Import futures open-position records from a downloaded IBKR activity statement."""
    if _reconciler is None:
        raise HTTPException(
            status_code=503,
            detail="Reconciler not initialised — engine started without real IBKR gateway.",
        )
    try:
        result = _reconciler.import_csv_positions(req.csv_path, req.statement_date)
        return result
    except Exception as exc:
        logger.exception("brokers/import-csv-positions failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"CSV import failed: {exc}") from exc
