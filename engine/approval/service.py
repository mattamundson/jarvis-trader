"""Shared approval flow for API and OpenClaw approval paths."""

from __future__ import annotations

import logging
from typing import Any, Optional

from approval.snapshot import entry_price_from_snapshot
from config import settings

logger = logging.getLogger("jarvis_trader.approval.service")


class ApprovalFlowError(Exception):
    """Structured approval flow error that routers can map to HTTP responses."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def approved_watchlist_symbols() -> set[str]:
    """Approved futures symbols that may pass through the human approval gate."""
    return {s.upper() for s in (settings.FUTURES_WATCHLIST or [])}


def _extract_snapshot_price(snapshot: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    """Return the first key in ``keys`` that resolves to a positive float on
    ``snapshot``.  Used to lift stop_price / target_price from Trader output
    for HB-1 broker-side bracket wiring."""
    if not isinstance(snapshot, dict):
        return None
    # Check top-level first
    for k in keys:
        v = snapshot.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            return fv
    # Check nested 'trade_decision' dict (pipeline_result_for_approval_snapshot stores
    # TraderAgent output under 'trade_decision'; SQLite may persist it as a JSON string)
    trade_decision = snapshot.get("trade_decision")
    if isinstance(trade_decision, str):
        import json as _json

        try:
            trade_decision = _json.loads(trade_decision)
        except Exception:
            trade_decision = {}
    if isinstance(trade_decision, dict):
        for k in keys:
            v = trade_decision.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                return fv
    # Also check legacy 'decision' dict for backwards compatibility
    decision = snapshot.get("decision")
    if isinstance(decision, dict):
        for k in keys:
            v = decision.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                return fv
    return None


def extract_attribution(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Extract journal attribution metadata from a pipeline snapshot."""
    if not isinstance(snapshot, dict):
        return {}

    debate = snapshot.get("debate") or {}
    if not isinstance(debate, dict):
        debate = {}

    return {
        k: v
        for k, v in {
            "regime_tier": snapshot.get("regime_tier"),
            "deciding_stage": snapshot.get("deciding_stage"),
            "bull_score": debate.get("bull_score"),
            "bear_score": debate.get("bear_score"),
            "debate_confidence": debate.get("debate_confidence"),
        }.items()
        if v is not None
    }


def get_pending_approval_row(db_manager, approval_id: str) -> dict[str, Any]:
    """Load and validate a pending approval row."""
    if db_manager is None:
        raise ApprovalFlowError(503, "Database not available")

    row = db_manager.get_pending_approval(approval_id)
    if not row:
        raise ApprovalFlowError(404, "Approval not found")
    if row.get("status") != "pending":
        raise ApprovalFlowError(409, f"Already resolved: {row.get('status')}")
    return row


def get_latest_pending_approval_row(db_manager) -> dict[str, Any]:
    """Return the most recent pending approval row."""
    if db_manager is None:
        raise ApprovalFlowError(503, "Database not available")

    rows = db_manager.list_pending_approvals(limit=1)
    if not rows:
        raise ApprovalFlowError(404, "No pending approvals")
    return rows[0]


def resolve_entry_price(
    approval_row: dict[str, Any],
    *,
    entry_price_override: Optional[float] = None,
) -> float:
    """Resolve an entry price from override, row, or snapshot."""
    snapshot = approval_row.get("pipeline_snapshot") or {}
    price = (
        entry_price_override
        if entry_price_override is not None
        else approval_row.get("entry_price")
    )
    if price is None:
        price = entry_price_from_snapshot(snapshot)
    if price is None:
        raise ApprovalFlowError(400, "No entry price in snapshot; pass entry_price in request body")
    return float(price)


def ensure_approval_allowed(approval_row: dict[str, Any], safety_layer) -> None:
    """Validate approval-time safety gates before execution."""
    from agents.pipeline import VALIDATION_ONLY_STRATEGIES
    from backtest.gate_v2_policy import is_strategy_authorized

    symbol = str(approval_row["symbol"]).upper()

    if safety_layer and safety_layer.get_status().get("is_killed"):
        raise ApprovalFlowError(409, "Kill switch active — cannot approve")

    if symbol not in approved_watchlist_symbols():
        raise ApprovalFlowError(400, f"Symbol {symbol} not on approved futures watchlist")

    # Single source of truth: checks VALIDATION_ONLY_INSTRUMENTS, paper_config.enabled,
    # and gate v2 verdict in one call.  Replaces the previous inline VALIDATION_ONLY check.
    authorized, reason = is_strategy_authorized(symbol)
    if not authorized:
        raise ApprovalFlowError(
            409,
            f"{symbol} is not authorized for paper orders: {reason}",
        )

    # Validation-only strategies: mirrors the scanner gate so manual human approval
    # cannot bypass the strategy block (BLOCKER 5 — §6.3).
    # stark_signal is nested at analyst_reports.technical.indicators.stark_signal
    # (same path the scanner reads for its own gate in signal_scanner.py:_scan_symbol).
    _snapshot = approval_row.get("pipeline_snapshot") or {}
    if isinstance(_snapshot, str):
        import json as _json

        try:
            _snapshot = _json.loads(_snapshot)
        except Exception:
            _snapshot = {}
    _stark_signal = (
        ((_snapshot.get("analyst_reports") or {}).get("technical") or {})
        .get("indicators", {})
        .get("stark_signal", "")
        or ""
    ).upper()
    if _stark_signal and _stark_signal in VALIDATION_ONLY_STRATEGIES:
        raise ApprovalFlowError(
            409,
            f"Strategy {_stark_signal} is in VALIDATION_ONLY_STRATEGIES — "
            "manual approval is blocked until WFO validation + gate v2 PASS. "
            "Remove from VALIDATION_ONLY_STRATEGIES to re-enable.",
        )

    if safety_layer is not None and hasattr(safety_layer, "get_lockout_status"):
        lockout = safety_layer.get_lockout_status(symbol)
        if lockout.get("locked"):
            raise ApprovalFlowError(
                409,
                f"{symbol} locked out for {lockout['remaining_minutes']} more minutes after stop-out",
            )


def preflight_approval_status(
    approval_row: dict[str, Any], safety_layer
) -> tuple[bool, Optional[str]]:
    """Read-only preflight: would ``ensure_approval_allowed`` accept this row?

    Returns ``(approvable, block_reason)``.  Pending candidates are deliberately
    queued for audit/dashboard visibility even when they can never be approved
    (gate v2 FAIL, validation-only strategy, disabled paper_config, kill switch,
    lockout).  The approve endpoint then 409s them.  This lets the dashboard
    disable the Approve button and show *why* instead of surfacing a green
    button that always errors (the MGC "Engine error 409" a trader hit
    2026-07-21).

    Implemented by calling ``ensure_approval_allowed`` and converting its raise
    into a boolean, so it can never drift out of agreement with the actual
    approve-time gate.  ``ensure_approval_allowed`` is side-effect-free (it only
    reads safety state, the watchlist, and gate v2 verdicts), so calling it here
    is safe.
    """
    try:
        ensure_approval_allowed(approval_row, safety_layer)
        return True, None
    except ApprovalFlowError as exc:
        return False, exc.detail
    except Exception as exc:  # never let a preflight check break the list endpoint
        logger.warning("preflight_approval_status unexpected error: %s", exc)
        return False, f"preflight check failed: {exc}"


async def execute_approved_trade(
    *,
    safety_layer,
    symbol: str,
    action: str,
    quantity: float,
    entry_price: float,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
) -> dict[str, Any]:
    """
    Route an approved futures trade through the hard safety wrapper.

    The approval surface is futures-only today, so canonical execution goes through
    SafetyLayer.submit_paper_order() instead of directly calling the broker connector.

    HB-1 bracket wiring (2026-04-24): when ``settings.ENABLE_BROKER_BRACKETS`` is
    True AND the caller supplies ``stop_price``, route through
    ``SafetyLayer.submit_entry_with_stop`` so broker-side STP (and optional TP)
    children are placed atomically linked to the parent entry.

    The newer ``ENABLE_BRACKET_ORDERS`` env var (migration_031 / 2026-05-21) is
    the canonical opt-out gate — read fresh from os.environ so the flag can be
    toggled without an engine restart.  Both flags must be enabled for the bracket
    path to activate; either can suppress it independently.
    """
    import os as _os

    if safety_layer is None:
        raise ApprovalFlowError(503, "Safety layer not available")

    _raw_flag = _os.environ.get("ENABLE_BRACKET_ORDERS", "1").strip().lower()
    _bracket_orders_env_enabled = _raw_flag not in ("0", "false", "no", "off")

    use_bracket = (
        _bracket_orders_env_enabled
        and getattr(settings, "ENABLE_BROKER_BRACKETS", True)
        and stop_price is not None
    )

    if use_bracket:
        result = await safety_layer.submit_entry_with_stop(
            symbol=symbol,
            action=action.upper(),
            quantity=max(1, int(round(quantity))),
            price=float(entry_price),
            stop_price=float(stop_price),
            target_price=float(target_price) if target_price is not None else None,
        )
    else:
        result = await safety_layer.submit_paper_order(
            symbol=symbol,
            action=action.upper(),
            quantity=max(1, int(round(quantity))),
            price=float(entry_price),
            order_type="MKT",
            limit_price=None,
        )
    if not result.get("approved", False):
        raise ApprovalFlowError(
            409,
            str(result.get("reason") or "Safety layer blocked approved trade execution"),
        )
    return result


def write_trade_journal_entry(db_manager, trade_id: str, snapshot: dict[str, Any]) -> None:
    """Best-effort journal entry creation with attribution metadata."""
    if db_manager is None or not isinstance(snapshot, dict):
        return

    attribution = extract_attribution(snapshot)
    if not attribution:
        return

    timeframe = snapshot.get("timeframe")
    db_manager.add_journal_entry(
        trade_id=trade_id,
        note="Trade approved via pipeline",
        timestamp=None,
        timeframe=timeframe,
        **attribution,
    )


async def approve_pending_trade(
    *,
    approval_id: str,
    db_manager,
    paper_tracker,
    safety_layer,
    resolved_by: str,
    entry_price_override: Optional[float] = None,
    data_manager=None,
) -> dict[str, Any]:
    """Approve a pending trade via the canonical shared control path."""
    if paper_tracker is None:
        raise ApprovalFlowError(503, "Paper tracker not available")
    if safety_layer is None:
        raise ApprovalFlowError(503, "Safety layer not available")

    row = get_pending_approval_row(db_manager, approval_id)
    ensure_approval_allowed(row, safety_layer)

    symbol = str(row["symbol"]).upper()
    action = str(row["action"]).lower()
    quantity = float(row["quantity"])
    snapshot = row.get("pipeline_snapshot") or {}
    entry_price = resolve_entry_price(row, entry_price_override=entry_price_override)

    # Entry price sanity check — rejects corrupted prices (e.g. stop_loss field copied
    # into entry_price, as in the 2026-05-09 phantom-trade incident).
    # Runs AFTER all other pre-submission gates but BEFORE IB submission.
    from risk.entry_price_sanity import check_entry_price_sanity, is_entry_price_sanity_enabled

    if is_entry_price_sanity_enabled() and data_manager is not None:
        try:
            is_sane, sanity_reason = await check_entry_price_sanity(
                symbol=symbol,
                entry_price=entry_price,
                data_manager=data_manager,
            )
            if not is_sane:
                raise ApprovalFlowError(
                    422,
                    f"Entry price sanity check failed: {sanity_reason}",
                )
        except ApprovalFlowError:
            raise
        except Exception as _sanity_exc:
            # Fail CLOSED: an unexpected error verifying the price rejects the
            # approval rather than booking a possibly-corrupted entry. The caller
            # (human or automation) can re-submit once the data path recovers.
            logger.critical(
                "[ENTRY_PRICE_SANITY] error during check for %s: %s — rejecting (fail-closed)",
                approval_id[:8],
                _sanity_exc,
            )
            raise ApprovalFlowError(
                422,
                f"Entry price sanity check could not be verified: {_sanity_exc}",
            ) from _sanity_exc

    # HB-1 bracket params — lifted from the pipeline snapshot (Trader output).
    # When ENABLE_BROKER_BRACKETS is True and stop_price is non-None,
    # execute_approved_trade routes through SafetyLayer.submit_entry_with_stop.
    # target_price uses target_1 first (nearer profit target), target_2 fallback.
    stop_price = _extract_snapshot_price(snapshot, ("stop_price", "stop_loss"))
    target_price = _extract_snapshot_price(
        snapshot, ("target_1", "target_price", "take_profit", "target_2")
    )

    execution_result = await execute_approved_trade(
        safety_layer=safety_layer,
        symbol=symbol,
        action=action,
        quantity=quantity,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
    )

    notes = str(snapshot.get("summary") or "")[:2000] if isinstance(snapshot, dict) else ""

    # Extract rv_at_entry from the pipeline snapshot for forward validation tagging.
    _rv_at_entry: Optional[float] = None
    try:
        _ind = (snapshot.get("analyst_reports") or {}).get("technical", {}).get("indicators", {})
        _rv = _ind.get("rv_20_ann_pct") if isinstance(_ind, dict) else None
        if _rv is not None:
            _rv_at_entry = float(_rv)
    except Exception:
        pass

    try:
        # #287 fix: stop_price (above) was already computed for the broker
        # bracket order but dropped here -- open_trade() had no stop_loss
        # param, so even human-approved trades persisted stop_loss=NULL and
        # PaperStopMonitor had nothing to enforce. Thread the real,
        # decision-derived stop through instead of leaving the row naked.
        trade_id = paper_tracker.open_trade(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=entry_price,
            notes=notes,
            rv_at_entry=_rv_at_entry,
            stop_loss=stop_price,
        )
    except Exception as exc:
        logger.exception("approve_pending_trade open_trade failed for %s", approval_id[:8])
        raise ApprovalFlowError(500, str(exc)) from exc

    # Persist bracket order IDs so the position survives restarts with its STP intact.
    # Only populated when ENABLE_BROKER_BRACKETS is True and STP placement succeeded.
    broker_meta: dict[str, Any] = {}
    if execution_result.get("entry_order_id") is not None:
        broker_meta["entry_order_id"] = str(execution_result["entry_order_id"])
    if execution_result.get("stp_order_id") is not None:
        broker_meta["stp_order_id"] = str(execution_result["stp_order_id"])
    if execution_result.get("tp_order_id") is not None:
        broker_meta["tp_order_id"] = str(execution_result["tp_order_id"])
    if broker_meta and hasattr(paper_tracker, "set_broker_metadata"):
        try:
            paper_tracker.set_broker_metadata(trade_id, broker_meta)
        except Exception as exc:
            logger.warning(
                "approve_pending_trade: set_broker_metadata failed for %s: %s",
                trade_id[:8],
                exc,
            )

    # Migration 031: persist bracket order IDs directly on paper_trades row so
    # the position can be queried without deserialising strategy_params JSON.
    # stop_order_id / target_order_id cover the STP + TP child legs.
    # bracket_status mirrors the submit_bracket / submit_entry_with_stop outcome.
    _stop_oid = execution_result.get("stp_order_id") or execution_result.get("stop_order_id")
    _tp_oid = execution_result.get("tp_order_id") or execution_result.get("target_order_id")
    _bstatus: Optional[str] = None
    if _stop_oid is not None:
        _bstatus = "attached" if _tp_oid is not None else "partial"
    elif execution_result.get("routed_to_ib") and execution_result.get("approved"):
        _bstatus = None  # single-order path — no bracket columns needed

    if (_stop_oid is not None or _tp_oid is not None) and db_manager is not None:
        try:
            if hasattr(db_manager, "update_paper_trade_bracket_ids"):
                db_manager.update_paper_trade_bracket_ids(
                    trade_id=trade_id,
                    stop_order_id=str(_stop_oid) if _stop_oid is not None else None,
                    target_order_id=str(_tp_oid) if _tp_oid is not None else None,
                    bracket_status=_bstatus,
                )
        except Exception as exc:
            logger.warning(
                "approve_pending_trade: update_paper_trade_bracket_ids failed for %s: %s",
                trade_id[:8],
                exc,
            )

    ok = db_manager.resolve_pending_approval(
        approval_id,
        new_status="approved",
        resolved_by=resolved_by,
        paper_trade_id=trade_id,
    )
    if not ok:
        logger.error("resolve_pending_approval failed after open_trade id=%s", trade_id[:8])
        raise ApprovalFlowError(409, "Could not mark approval resolved (race?)")

    try:
        write_trade_journal_entry(db_manager, trade_id, snapshot)
    except Exception as exc:
        logger.warning(
            "Could not create journal entry with attribution for %s: %s", trade_id[:8], exc
        )

    return {
        "status": "approved",
        "approval_id": approval_id,
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "entry_price": entry_price,
        "execution": execution_result,
    }


def reject_pending_trade(
    *,
    approval_id: str,
    db_manager,
    resolved_by: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Reject a pending trade via the canonical shared control path."""
    row = get_pending_approval_row(db_manager, approval_id)
    rejection_reason = reason or "rejected_by_user"
    ok = db_manager.resolve_pending_approval(
        approval_id,
        new_status="rejected",
        resolved_by=resolved_by,
        rejection_reason=rejection_reason,
    )
    if not ok:
        logger.error("resolve_pending_approval failed for rejection id=%s", approval_id[:8])
        raise ApprovalFlowError(409, "Could not mark approval resolved (race?)")

    return {
        "status": "rejected",
        "approval_id": approval_id,
        "symbol": row["symbol"],
        "reason": rejection_reason,
    }


def cancel_expired_approvals(db_manager, timeout_minutes: int = 5) -> int:
    """
    Find all 'pending' approvals that have exceeded their dynamic lifetime
    and mark as 'rejected'.
    Returns number of rows cancelled.
    """
    if db_manager is None:
        return 0

    from risk.approval_timeout import is_expired

    rows = db_manager.list_pending_approvals(limit=100)
    if not rows:
        return 0

    expired_count = 0

    for row in rows:
        try:
            if is_expired(row):
                approval_id = row["approval_id"]
                db_manager.resolve_pending_approval(
                    approval_id,
                    new_status="rejected",
                    resolved_by="system_timeout",
                    rejection_reason="Dynamic approval timeout exceeded",
                )
                logger.info(
                    "[APPROVAL] Auto-expired stale approval %s (%s)",
                    approval_id[:8],
                    row["symbol"],
                )
                expired_count += 1
        except Exception as e:
            logger.warning(
                "[APPROVAL] Failed to check expiry for %s: %s", row.get("approval_id", "??"), e
            )

    return expired_count
