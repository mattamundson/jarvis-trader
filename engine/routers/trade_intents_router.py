"""Fail-closed paper trade-intent API for Command Center V2.

This is the preferred manual futures path for the new dashboard. It deliberately
sits beside the legacy ``/orders/place`` endpoint so provenance is preserved while
RT-2 is reviewed. The browser never chooses authoritative quantity and never talks
to a broker directly.

Lifecycle:
    POST /trade-intents/preview
        -> fresh market/account checks
        -> zero-allowed server sizing
        -> durable short-lived PREVIEWED intent

    POST /trade-intents/{intent_id}/submit
        -> PAPER-mode + kill-switch recheck
        -> broker/tracker reconciliation
        -> fresh price/account revalidation
        -> quantity may stay the same or shrink, never grow
        -> atomic PREVIEWED->SUBMITTING claim
        -> SafetyLayer.submit_paper_bracket_order()
        -> SUBMITTED only after broker acknowledgement

Any ambiguous broker-call outcome remains SUBMITTING. That state is intentionally
non-retryable until reconciliation resolves it.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from approval.service import approved_watchlist_symbols
from config import settings
from risk.entry_price_sanity import check_entry_price_sanity
from trade_intents.core import TradeIntentError, compute_trade_intent_preview
from trade_intents.store import TradeIntentStore, TradeIntentStoreError

router = APIRouter(tags=["trade-intents"])

_FUTURES_ROOTS: frozenset[str] = frozenset(
    {"MES", "MNQ", "M2K", "MCL", "MGC", "MHG", "MSI", "ES", "NQ", "RTY", "CL", "GC", "HG"}
)


class TradeIntentPreviewRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    symbol: str = Field(..., min_length=1, max_length=20)
    direction: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: float | None = None
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    max_risk_fraction: float = Field(0.005, gt=0, le=0.01)
    requested_quantity: int | None = Field(None, ge=1)
    ttl_seconds: int = Field(60, ge=15, le=300)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_limit(self) -> "TradeIntentPreviewRequest":
        if self.order_type == "LIMIT" and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT intents")
        if self.order_type == "MARKET" and self.limit_price is not None:
            raise ValueError("limit_price must be omitted for MARKET intents")
        return self


class TradeIntentSubmitResponse(BaseModel):
    intent_id: str
    status: str
    preview: dict[str, Any]
    broker_result: dict[str, Any] | None = None
    order_id: str | None = None
    terminal_reason: str | None = None


def _parent_state():
    # Imported lazily to avoid a module-import cycle: orders_router includes this
    # subrouter only after its module globals have been created.
    from routers import orders_router

    return orders_router


def _deps():
    state = _parent_state()
    safety = getattr(state, "_safety_layer", None)
    data_manager = getattr(state, "_data_manager", None)
    if safety is None:
        raise HTTPException(503, "Safety layer not initialized")
    if data_manager is None:
        raise HTTPException(503, "Market data manager not initialized")
    return safety, data_manager


def _real_paper_broker_enabled() -> bool:
    return bool(getattr(settings, "IB_PAPER_BROKER_ENABLED", False))


def _configured_paper_account() -> str:
    return str(getattr(settings, "IB_ACCOUNT_ID", "") or "").strip()


def _require_paper_mode() -> None:
    if bool(getattr(settings, "LIVE_TRADING_ENABLED", False)):
        raise HTTPException(409, "Trade-intent execution is disabled in live mode")
    if not bool(getattr(settings, "PAPER_TRADING", True)):
        raise HTTPException(409, "Paper trading is not enabled")

    if _real_paper_broker_enabled():
        if not bool(getattr(settings, "IBKR_PAPER_MODE", False)):
            raise HTTPException(409, "Real broker execution requires IBKR_PAPER_MODE=True")
        if int(getattr(settings, "IBKR_PORT", 0)) != 4002:
            raise HTTPException(409, "Real broker execution requires IB Gateway paper port 4002")
        if not _configured_paper_account():
            raise HTTPException(409, "Real broker execution requires a configured IB_ACCOUNT_ID")


def _require_verified_paper_broker(safety) -> None:
    """Require configuration and connected-session proof before real IB mutation."""

    if not _real_paper_broker_enabled():
        return

    expected_account = _configured_paper_account()
    gateway = getattr(safety, "_ib_gateway", None)
    if gateway is None:
        raise HTTPException(503, "Real IB paper gateway is not attached")

    gateway_config = getattr(gateway, "_config", None)
    if gateway_config is None:
        raise HTTPException(503, "Attached gateway does not expose verifiable broker configuration")
    if int(getattr(gateway_config, "port", 0)) != 4002:
        raise HTTPException(409, "Attached gateway is not configured for paper port 4002")
    if str(getattr(gateway_config, "account", "") or "").strip() != expected_account:
        raise HTTPException(409, "Attached gateway account does not match IB_ACCOUNT_ID")

    is_connected = getattr(gateway, "is_connected", None)
    try:
        connected = bool(is_connected()) if callable(is_connected) else False
    except Exception as exc:
        raise HTTPException(503, "Unable to verify the IB paper gateway connection") from exc
    if not connected:
        raise HTTPException(503, "IB paper gateway is not connected")

    raw_ib = getattr(gateway, "_ib", None)
    managed_accounts = getattr(raw_ib, "managedAccounts", None)
    if not callable(managed_accounts):
        raise HTTPException(503, "IB managed-account identity is unavailable")
    try:
        actual_accounts = {
            str(account).strip()
            for account in managed_accounts()
            if str(account).strip()
        }
    except Exception as exc:
        raise HTTPException(503, "Unable to verify IB managed-account identity") from exc
    if expected_account not in actual_accounts:
        raise HTTPException(409, "Connected IB session does not include the configured paper account")


def _store() -> TradeIntentStore:
    safety, _ = _deps()
    db_path = getattr(safety, "_db_path", None)
    if not db_path:
        raise HTTPException(503, "Trade-intent store unavailable: safety DB path missing")
    return TradeIntentStore(db_path)


def _equity(safety) -> float:
    status = safety.get_status()
    try:
        equity = float(status.get("current_equity", 0.0))
    except (TypeError, ValueError):
        equity = 0.0
    if not math.isfinite(equity) or equity <= 0:
        raise HTTPException(409, "Current portfolio equity is unavailable or non-positive")
    return equity


def _symbol_root(symbol: str) -> str:
    return symbol.rstrip("0123456789").upper()


def _require_approved_futures(symbol: str) -> None:
    root = _symbol_root(symbol)
    if root not in _FUTURES_ROOTS:
        raise HTTPException(400, "RT-2 currently supports futures only")
    approved = {str(s).upper() for s in approved_watchlist_symbols()}
    if symbol.upper() not in approved and root not in approved:
        raise HTTPException(400, f"Symbol {symbol.upper()} is not on the approved futures watchlist")


async def _market_price(data_manager, symbol: str) -> tuple[float, str | None]:
    try:
        result = await data_manager.get_current_price(symbol, is_futures=True)
    except Exception as exc:
        raise HTTPException(503, f"Current market price unavailable: {exc}") from exc
    if not isinstance(result, dict):
        raise HTTPException(503, "Current market price returned an invalid response")
    try:
        price = float(result.get("last_price"))
    except (TypeError, ValueError):
        price = 0.0
    if not math.isfinite(price) or price <= 0:
        raise HTTPException(503, "Current market price is unavailable or invalid")
    return price, result.get("source")


async def _validate_entry(data_manager, symbol: str, entry_price: float) -> None:
    try:
        sane, reason = await check_entry_price_sanity(
            symbol=symbol,
            entry_price=entry_price,
            data_manager=data_manager,
            is_futures=True,
        )
    except Exception as exc:
        raise HTTPException(422, f"Entry price freshness/sanity could not be verified: {exc}") from exc
    if not sane:
        raise HTTPException(422, f"Entry price freshness/sanity failed: {reason}")


def _signed_tracker_positions(db_manager) -> dict[str, float]:
    if db_manager is None or not hasattr(db_manager, "get_open_trades"):
        raise HTTPException(503, "Tracker position state is unavailable")
    try:
        rows = db_manager.get_open_trades() or []
    except Exception as exc:
        raise HTTPException(503, f"Tracker position read failed: {exc}") from exc

    positions: dict[str, float] = {}
    for row in rows:
        if isinstance(row, dict):
            symbol = str(row.get("symbol") or "").upper()
            qty_raw = row.get("quantity") or 0
            action = str(row.get("action") or row.get("side") or "BUY").upper()
        else:
            symbol = str(getattr(row, "symbol", "") or "").upper()
            qty_raw = getattr(row, "quantity", 0) or 0
            action = str(getattr(row, "action", "BUY") or "BUY").upper()
        if not symbol:
            continue
        try:
            qty = abs(float(qty_raw))
        except (TypeError, ValueError):
            continue
        signed = qty if action in {"BUY", "BUY_TO_OPEN", "LONG"} else -qty
        positions[symbol] = positions.get(symbol, 0.0) + signed
    return positions


async def _require_reconciled(safety) -> dict[str, Any]:
    gateway = getattr(safety, "_ib_gateway", None)
    if gateway is None:
        raise HTTPException(503, "IB paper execution connector unavailable")
    try:
        connected_attr = getattr(gateway, "is_connected", False)
        connected = connected_attr() if callable(connected_attr) else bool(connected_attr)
    except Exception as exc:
        raise HTTPException(503, f"IB execution connection could not be verified: {exc}") from exc
    if not connected:
        raise HTTPException(503, "IB paper execution connector is not connected")

    try:
        broker_rows = await gateway.get_positions()
    except Exception as exc:
        raise HTTPException(503, f"IB position reconciliation failed: {exc}") from exc

    broker: dict[str, float] = {}
    for row in broker_rows or []:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        try:
            qty = float(row.get("position") or row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if abs(qty) > 1e-9:
            broker[symbol] = broker.get(symbol, 0.0) + qty

    tracker = _signed_tracker_positions(getattr(safety, "_db_manager", None))
    all_symbols = sorted(set(broker) | set(tracker))
    mismatches: list[dict[str, Any]] = []
    for symbol in all_symbols:
        broker_qty = broker.get(symbol, 0.0)
        tracker_qty = tracker.get(symbol, 0.0)
        if abs(broker_qty - tracker_qty) > 1e-9:
            mismatches.append(
                {
                    "symbol": symbol,
                    "broker_qty": broker_qty,
                    "tracker_qty": tracker_qty,
                    "delta": broker_qty - tracker_qty,
                }
            )
    if mismatches:
        raise HTTPException(409, detail={"message": "Broker/tracker reconciliation failed", "mismatches": mismatches})
    return {"in_sync": True, "symbols_checked": len(all_symbols)}


def _max_trade_loss() -> float:
    return float(getattr(settings, "MAX_TRADE_LOSS_USD", 50.0))


def _max_contracts() -> int:
    return int(getattr(settings, "MAX_CONTRACTS_PER_INSTRUMENT", 2))


def _record_response(record: dict[str, Any]) -> TradeIntentSubmitResponse:
    return TradeIntentSubmitResponse(
        intent_id=record["intent_id"],
        status=record["status"],
        preview=record["preview"],
        broker_result=record.get("broker_result"),
        order_id=record.get("order_id"),
        terminal_reason=record.get("terminal_reason"),
    )


@router.post("/trade-intents/preview", response_model=TradeIntentSubmitResponse)
async def preview_trade_intent(payload: TradeIntentPreviewRequest):
    _require_paper_mode()
    safety, data_manager = _deps()
    if safety.is_killed:
        raise HTTPException(409, "Kill switch active")
    _require_approved_futures(payload.symbol)

    market_price, _source = await _market_price(data_manager, payload.symbol)
    entry_price = payload.limit_price if payload.order_type == "LIMIT" else market_price
    assert entry_price is not None
    await _validate_entry(data_manager, payload.symbol, float(entry_price))

    try:
        preview = compute_trade_intent_preview(
            symbol=payload.symbol,
            direction=payload.direction,
            order_type=payload.order_type,
            entry_price=float(entry_price),
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            account_equity=_equity(safety),
            max_risk_fraction=payload.max_risk_fraction,
            max_trade_loss_usd=_max_trade_loss(),
            requested_quantity=payload.requested_quantity,
            max_contracts=_max_contracts(),
        )
    except TradeIntentError as exc:
        raise HTTPException(422, str(exc)) from exc

    request_payload = payload.model_dump(exclude={"ttl_seconds"})
    try:
        record = _store().create_preview(
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            preview=preview,
            ttl_seconds=payload.ttl_seconds,
        )
        if not preview.can_submit and record["status"] == "PREVIEWED":
            record = _store().mark_terminal(
                record["intent_id"],
                status="BLOCKED",
                reason=preview.blocking_reason or "Risk policy returned zero quantity",
            )
    except TradeIntentStoreError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _record_response(record)


@router.get("/trade-intents/{intent_id}", response_model=TradeIntentSubmitResponse)
async def get_trade_intent(intent_id: str):
    record = _store().get(intent_id)
    if record is None:
        raise HTTPException(404, "Trade intent not found")
    return _record_response(record)


@router.post("/trade-intents/{intent_id}/submit", response_model=TradeIntentSubmitResponse)
async def submit_trade_intent(intent_id: str):
    _require_paper_mode()
    safety, data_manager = _deps()
    _require_verified_paper_broker(safety)
    store = _store()

    try:
        record = store.require_submittable(intent_id)
    except TradeIntentStoreError as exc:
        raise HTTPException(409, str(exc)) from exc
    if record["status"] == "SUBMITTED":
        return _record_response(record)
    if safety.is_killed:
        blocked = store.mark_terminal(intent_id, status="BLOCKED", reason="Kill switch active")
        raise HTTPException(409, detail=_record_response(blocked).model_dump())

    preview = record["preview"]
    symbol = str(preview["symbol"]).upper()
    _require_approved_futures(symbol)
    await _require_reconciled(safety)

    market_price, _source = await _market_price(data_manager, symbol)
    order_type = str(preview["order_type"]).upper()
    entry_price = float(preview["entry_price"]) if order_type == "LIMIT" else market_price
    await _validate_entry(data_manager, symbol, entry_price)

    try:
        refreshed = compute_trade_intent_preview(
            symbol=symbol,
            direction=str(preview["direction"]).upper(),
            order_type=order_type,
            entry_price=entry_price,
            stop_loss=float(preview["stop_loss"]),
            take_profit=float(preview["take_profit"]),
            account_equity=_equity(safety),
            max_risk_fraction=float(preview["max_risk_fraction"]),
            max_trade_loss_usd=_max_trade_loss(),
            # Never grow beyond the quantity the human saw at preview time.
            requested_quantity=int(preview["final_quantity"]),
            max_contracts=_max_contracts(),
        )
    except TradeIntentError as exc:
        blocked = store.mark_terminal(intent_id, status="BLOCKED", reason=str(exc))
        raise HTTPException(409, detail=_record_response(blocked).model_dump()) from exc

    if not refreshed.can_submit or refreshed.final_quantity < 1:
        blocked = store.mark_terminal(
            intent_id,
            status="BLOCKED",
            reason=refreshed.blocking_reason or "Fresh risk policy returned zero quantity",
        )
        raise HTTPException(409, detail=_record_response(blocked).model_dump())

    try:
        claimed = store.claim_for_submission(intent_id)
    except TradeIntentStoreError as exc:
        raise HTTPException(409, str(exc)) from exc
    if claimed["status"] == "SUBMITTED":
        return _record_response(claimed)

    try:
        result = await safety.submit_paper_bracket_order(
            symbol=symbol,
            action=str(preview["direction"]).upper(),
            quantity=refreshed.final_quantity,
            price=entry_price,
            stop_loss=float(preview["stop_loss"]),
            take_profit=float(preview["take_profit"]),
            order_type="LMT" if order_type == "LIMIT" else "MKT",
            limit_price=float(preview["entry_price"]) if order_type == "LIMIT" else None,
        )
    except Exception as exc:
        # Ambiguous broker-call outcome: do NOT reset/retry. SUBMITTING + active
        # request-hash uniqueness prevents a duplicate order until reconciled.
        raise HTTPException(
            502,
            detail={
                "message": "Broker submission outcome is ambiguous; intent remains SUBMITTING",
                "intent_id": intent_id,
                "error": str(exc),
            },
        ) from exc

    if not result.get("approved"):
        blocked = store.mark_terminal(
            intent_id,
            status="BLOCKED",
            reason=str(result.get("reason") or "SafetyLayer rejected bracket"),
        )
        raise HTTPException(409, detail=_record_response(blocked).model_dump())

    if not result.get("routed_to_ib") or not result.get("entry_id"):
        # Once the broker call has occurred, routed_to_ib=False is still treated
        # conservatively as ambiguous. Keep SUBMITTING and require reconciliation.
        raise HTTPException(
            502,
            detail={
                "message": "Broker did not provide an unambiguous bracket acknowledgement; intent remains SUBMITTING",
                "intent_id": intent_id,
                "broker_result": result,
            },
        )

    try:
        submitted = store.mark_submitted(
            intent_id,
            broker_result=result,
            order_id=str(result.get("entry_id")),
            now=datetime.now(timezone.utc),
        )
    except TradeIntentStoreError as exc:
        raise HTTPException(500, f"Broker acknowledged order but intent persistence failed: {exc}") from exc
    return _record_response(submitted)
