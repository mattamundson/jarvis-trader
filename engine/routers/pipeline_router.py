"""Pipeline notification router - test webhooks."""

import asyncio
import inspect
import logging
from collections import deque
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

<<<<<<< HEAD
=======
from utils.data_provenance import build_data_provenance, stamp_signal_data

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

try:  # dual-path import (engine.* package vs bare under engine/ cwd)
    from engine.analytics.agent_feedback import build_analyst_signals_map
except ImportError:  # pragma: no cover
    from analytics.agent_feedback import build_analyst_signals_map

# ── Signal Debug Log ──────────────────────────────────────────────────────────
# Rolling log of the last 50 pipeline filter decisions (pre-filter + pass-through).
# Populated by record_signal_debug() called from agents/pipeline.py.
_signal_debug_log: deque = deque(maxlen=50)


def record_signal_debug(entry: dict) -> None:
    """Append a filter decision to the signal debug log."""
    _signal_debug_log.append(entry)


class PipelineRunRequest(BaseModel):
    """Request to execute the trading pipeline for a symbol"""

    symbol: str = Field(..., description="Trading symbol (e.g., MCL, MNQ, SPY)")
    is_futures: bool = Field(True, description="True for futures, False for options")
    interval: str = Field("1h", description="Bar timeframe (e.g., 1h, 4h, 1d)")


class SchedulerJobInfo(BaseModel):
    """Job information from APScheduler."""

    id: str
    name: str
    next_run: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SchedulerStatusResponse(BaseModel):
    """Status of the APScheduler and decision logging."""

    running: bool
    total_jobs: int
    jobs: list[SchedulerJobInfo]
    total_decisions_logged: int

    model_config = ConfigDict(from_attributes=True)


class ExpensiveStageInfo(BaseModel):
    """Top expensive stages by average token usage."""

    stage: str
    avg_tokens: float

    model_config = ConfigDict(from_attributes=True)


class CostSummaryResponse(BaseModel):
    """LLM cost tracking summary across all pipeline runs."""

    today_usd: float = Field(..., description="Total cost for today (UTC)")
    this_week_usd: float = Field(..., description="Total cost for the past 7 days")
    all_time_usd: float = Field(..., description="Total cost across all recorded calls")
    cost_per_trade_usd: float = Field(..., description="Average cost per unique run_id")
    top_expensive_stages: list[ExpensiveStageInfo] = Field(
        ..., description="Top 5 stages by avg token usage"
    )

    model_config = ConfigDict(from_attributes=True)


# Global references (injected from main.py)
_scheduler = None
_trading_pipeline = None
_safety_layer = None
_db_manager = None
<<<<<<< HEAD
=======
_data_manager = None  # MarketDataManager, injected via inject_dependencies() — decision provenance
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
_paper_tracker = None
_telegram_notifier = None
_sdk_pipeline = None
_decision_log_ref: list[dict] = []  # reference to main.py's in-memory ring buffer
_log_decision_fn = None  # callable: main.py._log_decision


def _guard_background_paper_open(symbol: str) -> None:
    """
    Apply the same direct-open policy to background auto-logging.

    Background pipeline runs must not write trades that would be rejected by the
    live/paper safety posture elsewhere in the system.
    """
    from approval.service import approved_watchlist_symbols
    from config import settings
    from execution.order_router import FUTURES_SYMBOLS

    if settings.LIVE_TRADING_ENABLED:
        raise RuntimeError("Direct paper-trade open disabled in live mode")

    if _safety_layer is not None and _safety_layer.get_status().get("is_killed"):
        raise RuntimeError("Kill switch active - cannot open direct paper trade")

    if symbol.upper() in FUTURES_SYMBOLS and symbol.upper() not in approved_watchlist_symbols():
        raise RuntimeError(f"Symbol {symbol.upper()} not on approved futures watchlist")


async def _submit_broker_entry_with_stop(
    *,
    symbol: str,
    action: str,
    quantity: float | int,
    entry_price: float,
    stop_price: float | None,
) -> dict | None:
    """
    Route approved non-human directional paper decisions through SafetyLayer.

    The paper tracker is an audit/portfolio mirror; broker-side protection still
    has to happen through SafetyLayer so the computed stop reaches IB as a child
    STP order.
    """
    if stop_price is None or _safety_layer is None:
        return None

    submitter = getattr(_safety_layer, "submit_entry_with_stop", None)
    if submitter is None:
        logger.warning(
            "[EXECUTION] %s %s has stop_price=%s but SafetyLayer lacks submit_entry_with_stop",
            symbol,
            action.upper(),
            stop_price,
        )
        return None

    result = submitter(
        symbol=symbol,
        action=action.upper(),
        quantity=int(quantity),
        price=float(entry_price),
        stop_price=float(stop_price),
    )
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        logger.warning("[EXECUTION] submit_entry_with_stop returned unexpected value: %r", result)
        return None

    if not result.get("approved"):
        raise RuntimeError(f"SafetyLayer rejected broker entry: {result.get('reason')}")

    logger.info(
        "[EXECUTION] Broker STP route %s %s qty=%s entry_id=%s stp_id=%s linked=%s routed=%s",
        symbol,
        action.upper(),
        int(quantity),
        result.get("entry_order_id"),
        result.get("stp_order_id"),
        result.get("stp_linked"),
        result.get("routed_to_ib"),
    )
    return result


def inject_dependencies(
    scheduler,
    trading_pipeline,
    safety_layer,
    db_manager,
    paper_tracker=None,
    sdk_pipeline=None,
    decision_log=None,
    log_decision_fn=None,
<<<<<<< HEAD
):
    """Inject global dependencies from main.py"""
    global _scheduler, _trading_pipeline, _safety_layer, _db_manager, _paper_tracker, _sdk_pipeline, _decision_log_ref, _log_decision_fn
=======
    data_manager=None,
):
    """Inject global dependencies from main.py"""
    global _scheduler, _trading_pipeline, _safety_layer, _db_manager, _paper_tracker, _sdk_pipeline, _decision_log_ref, _log_decision_fn, _data_manager
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    _scheduler = scheduler
    _trading_pipeline = trading_pipeline
    _safety_layer = safety_layer
    _db_manager = db_manager
    _paper_tracker = paper_tracker
    _sdk_pipeline = sdk_pipeline
<<<<<<< HEAD
=======
    if data_manager is not None:
        _data_manager = data_manager
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    if decision_log is not None:
        _decision_log_ref = decision_log
    if log_decision_fn is not None:
        _log_decision_fn = log_decision_fn

    # Wire paper tracker as portfolio provider so the risk manager sees real positions
    if trading_pipeline is not None and paper_tracker is not None:
        trading_pipeline._agents["portfolio"] = paper_tracker
        logger.info("[Pipeline] paper_tracker injected as portfolio provider")


def set_notifier(notifier) -> None:
    """Inject the Telegram notifier (called from main.py lifespan startup)."""
    global _telegram_notifier
    _telegram_notifier = notifier


@router.get("/signal-debug")
async def get_signal_debug():
    """Return the last 50 pipeline filter decisions.

    Each entry contains:
      - timestamp: ISO string of when the decision was made
      - symbol: trading symbol
      - stc_val: the STC value at decision time
      - stage_blocked: one of 'pre_filter' | 'approved' | 'regime' | 'llm_confidence'
      - reason: human-readable explanation
    """
    return {"entries": list(_signal_debug_log), "count": len(_signal_debug_log)}


@router.post("/cache/invalidate/{symbol}")
async def invalidate_cache(symbol: str):
    """Invalidate the signal cache for a specific symbol.

    Forces the next pipeline run for this symbol to bypass the cache
    and fetch fresh data + re-run all agents.
    """
    from cache.signal_cache import invalidate_signal

    ok = await invalidate_signal(symbol.upper())
    return {"invalidated": ok, "symbol": symbol.upper()}


@router.post("/cache/invalidate-all")
async def invalidate_all_cache():
    """Invalidate the entire signal cache (all symbols)."""
    from cache.signal_cache import invalidate_all

    ok = await invalidate_all()
    return {"invalidated": ok}


@router.post("/notifications/telegram/test")
async def test_telegram():
    """Test Telegram notification config"""
    from datetime import timezone as _tz

    try:
        from notifications.telegram import get_notifier

        notifier = get_notifier()
        ts = datetime.now(_tz.utc).isoformat()
        if not notifier.enabled:
            return {
                "sent": False,
                "status": "not_configured",
                "message": "Add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID to .env",
                "timestamp": ts,
            }
        ok = await notifier.test()
        return {
            "sent": ok,
            "status": "ok" if ok else "failed",
            "timestamp": ts,
        }
    except ImportError:
        return {
            "sent": False,
            "status": "module_not_found",
            "message": "Telegram module not installed",
        }
    except Exception as e:
        logger.error(f"[TELEGRAM] Test failed: {e}")
        raise HTTPException(500, f"Telegram test failed: {e}") from e


@router.get("/scheduler/status")
async def scheduler_status() -> SchedulerStatusResponse:
    """
    Get scheduler status and decision logging metrics.

    Returns:
        running: Whether APScheduler is currently running
        total_jobs: Number of scheduled jobs
        jobs: List of job details (id, name, next_run)
        total_decisions_logged: Count of decisions in the database
    """
    try:
        # Get scheduler status
        is_running = _scheduler is not None and _scheduler.running
        total_jobs = 0
        jobs_list: list[SchedulerJobInfo] = []

        if _scheduler is not None:
            total_jobs = len(_scheduler.get_jobs())
            for job in _scheduler.get_jobs():
                job_next_run = (
                    job.next_run_time.isoformat() if job.next_run_time is not None else None
                )
                jobs_list.append(
                    SchedulerJobInfo(
                        id=job.id,
                        name=job.name or job.id,
                        next_run=job_next_run,
                    )
                )

        # Get decision count from database
        total_decisions = 0
        if _db_manager is not None:
            try:
                decisions = _db_manager.get_decisions(limit=999999)
                total_decisions = len(decisions)
            except Exception:
                total_decisions = 0

        return SchedulerStatusResponse(
            running=is_running,
            total_jobs=total_jobs,
            jobs=jobs_list,
            total_decisions_logged=total_decisions,
        )
    except Exception as e:
        logger.error(f"[SCHEDULER] Status query failed: {e}")
        raise HTTPException(500, f"Scheduler status query failed: {e}") from e


@router.post("/scheduler/manual-scan")
async def manual_scan():
    """Manually trigger market scan"""
    try:
        from schedulers.market_scanner import MarketScanner

        scanner = MarketScanner()
        result = await scanner.scan_all_markets()
        return {"status": "ok", "scanned": result}
    except Exception as e:
        logger.error(f"[SCHEDULER] Manual scan failed: {e}")
        raise HTTPException(500, f"Scan failed: {e}") from e


@router.post("/notifications/whatsapp/test")
async def test_whatsapp():
    """Test WhatsApp notification config"""
    from datetime import timezone as _tz

    try:
        from notifications.whatsapp import get_notifier

        notifier = get_notifier()
        ts = datetime.now(_tz.utc).isoformat()
        if not notifier.enabled:
            return {
                "sent": False,
                "status": "not_configured",
                "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
                "timestamp": ts,
            }
        ok = await notifier.test()
        return {
            "sent": ok,
            "status": "ok" if ok else "failed",
            "timestamp": ts,
        }
    except ImportError:
        return {
            "sent": False,
            "status": "module_not_found",
            "message": "WhatsApp module not installed",
        }
    except Exception as e:
        logger.error(f"[WHATSAPP] Test failed: {e}")
        raise HTTPException(500, f"WhatsApp test failed: {e}") from e


async def _send_signal_alert(symbol: str, final_action: str, result: dict) -> None:
    """
    Fire-and-forget Telegram alert for a non-HOLD pipeline result.

    Formats the canonical JARVIS SIGNAL line:
        JARVIS SIGNAL: LONG MCL @ 75.32 | Stop: 74.80 | Target: 76.20 | R:R: 1.71 | Conviction: 8/10

    Skips gracefully if the notifier is None or disabled.
    """
    notifier = _telegram_notifier
    if notifier is None:
        # Fall back to the module-level singleton if no injected notifier
        try:
            from notifications.telegram import get_notifier

            notifier = get_notifier()
        except Exception:
            logger.warning("[PIPELINE] Telegram notifier unavailable — signal alert skipped")
            return

    if not notifier.enabled:
        return

    trade_dec = result.get("trade_decision") or {}
    analyst_reports = result.get("analyst_reports") or {}
    technical_report = analyst_reports.get("technical") or {}
    fund_decision = result.get("fund_decision") or {}

    entry_price = (
        trade_dec.get("entry_price")
        or trade_dec.get("limit_price")
        or technical_report.get("current_price")
        or technical_report.get("price")
        or 0.0
    )
    stop_price = trade_dec.get("stop_price") or 0.0
    target_price = (
        trade_dec.get("target_1")
        or trade_dec.get("target_price")
        or trade_dec.get("take_profit")
        or 0.0
    )
    conviction_raw = fund_decision.get("final_conviction") or trade_dec.get("conviction") or 0.0
    conviction_score = round(float(conviction_raw) * 10, 1)

    # Risk:Reward ratio
    if entry_price and stop_price and target_price and stop_price != entry_price:
        risk = abs(float(entry_price) - float(stop_price))
        reward = abs(float(target_price) - float(entry_price))
        rr_ratio = f"{reward / risk:.2f}" if risk else "N/A"
    else:
        rr_ratio = "N/A"

    direction = final_action.upper()
    price_str = f"{float(entry_price):.2f}" if entry_price else "N/A"
    stop_str = f"{float(stop_price):.2f}" if stop_price else "N/A"
    target_str = f"{float(target_price):.2f}" if target_price else "N/A"

    message = (
        f"<b>JARVIS SIGNAL: {direction} {symbol}</b>\n"
        f"@ {price_str} | Stop: {stop_str} | Target: {target_str} | R:R: {rr_ratio} | "
        f"Conviction: {conviction_score}/10"
    )

    try:
        await notifier.send(message)
        logger.info("[PIPELINE] Telegram signal alert sent for %s %s", direction, symbol)
    except Exception as exc:
        logger.error("[PIPELINE] Telegram send failed for %s: %s", symbol, exc)


def _log_decision_to_db(
    symbol: str,
    action: str,
    confidence: float,
    source: str,
    summary: str,
    reasoning: str,
    regime: str | None,
    signal_data: dict | None,
    full_pipeline_data: dict | None,
) -> None:
    """Persist a pipeline decision to SQLite via the injected db_manager.

    Best-effort — never raises; failures are logged and swallowed.
    """
    if _db_manager is None:
        logger.warning("[DECISION] db_manager not injected — decision for %s not persisted", symbol)
        return
    try:
<<<<<<< HEAD
=======
        # Data-truth: stamp *what data* this decision was based on (tier +
        # per-symbol serve-age), matching main.py's _log_decision (PR #286).
        # Additive only — never changes a trade decision, never raises.
        provenance = build_data_provenance(_data_manager, symbol)
        sig = signal_data or {"source": source, "summary": summary}
        sig = stamp_signal_data(sig, provenance)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        _db_manager.insert_decision(
            symbol=symbol,
            action=action,
            confidence=confidence,
            regime=regime,
<<<<<<< HEAD
            signal_data=signal_data or {"source": source, "summary": summary},
=======
            signal_data=sig,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
            reasoning=reasoning or summary,
            full_pipeline_data=full_pipeline_data,
        )
        logger.info(
            "[DECISION] Persisted %s %s (confidence=%.0f%%) source=%s",
            symbol,
            action.upper(),
            confidence * 100,
            source,
        )
    except Exception as exc:
        logger.warning("[DECISION] Failed to persist decision for %s: %s", symbol, exc)


async def _run_pipeline_and_log(symbol: str, is_futures: bool) -> None:
    """
    Internal coroutine: runs the pipeline, logs the decision to SQLite, and
    auto-logs paper trades for LONG/SHORT decisions.

    Called as a background task from run_pipeline() so the HTTP response is immediate.
    Decision logging and paper trade logging are best-effort — failures are caught and logged.
    """
    try:
        result = await _trading_pipeline.analyze_and_decide(symbol=symbol, is_futures=is_futures)
    except Exception as exc:
        logger.error("[PIPELINE] analyze_and_decide raised for %s: %s", symbol, exc)
        return

    final_action = result.get("final_action", "hold")
    logger.info(
        "[PIPELINE] %s complete — final_action=%s requires_human=%s",
        symbol,
        final_action,
        result.get("requires_human"),
    )

    # ── Log decision to SQLite (ALL actions including HOLD) ──────────────────
    try:
        _fund = result.get("fund_decision") or {}
        _trade = result.get("trade_decision") or {}
        _analysts = result.get("analyst_reports") or {}
        _tech = _analysts.get("technical") or {}
        _confidence = float(
            result.get("boosted_confidence")
            or _fund.get("final_conviction")
            or _trade.get("confidence")
            or 0.0
        )
        _summary = result.get("summary") or _fund.get("reasoning") or ""
        _reasoning = _fund.get("reasoning") or _trade.get("reasoning") or _summary
        _regime = _tech.get("regime") or None
        _signal_data = {
            "source": "manual",
            "symbol": symbol,
            "action": final_action,
            "summary": _summary,
        }
        _log_decision_to_db(
            symbol=symbol,
            action=final_action,
            confidence=_confidence,
            source="manual",
            summary=_summary,
            reasoning=_reasoning,
            regime=_regime,
            signal_data=_signal_data,
            full_pipeline_data=result,
        )
    except Exception as _dec_exc:
        logger.warning("[DECISION] Decision logging block failed for %s: %s", symbol, _dec_exc)

    # Route directional decisions: queue for human approval OR auto-log as paper trade
    is_directional = final_action not in ("hold", "HOLD")
    requires_human = bool(result.get("requires_human", True))

    try:
        from config import settings as _cfg

        _paper_mode = not _cfg.LIVE_TRADING_ENABLED
    except Exception:
        _paper_mode = True  # default safe: treat as paper if config unavailable

    # Execution audit log — fires for every directional decision regardless of outcome
    _confidence = float((result.get("fund_decision") or {}).get("final_conviction") or 0.0)
    _threshold = 0.0  # paper mode: no confidence threshold gate
    logger.info(
        "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f executed=%s reason=%s",
        symbol,
        final_action,
        _confidence,
        _threshold,
        str(is_directional and not requires_human),
        (
            "hold"
            if not is_directional
            else ("queued_for_approval" if requires_human else "auto_logged")
        ),
    )

    if is_directional and requires_human and _db_manager is not None:
        # Human approval required — queue in pending_trade_approvals
        try:
            from approval.snapshot import pipeline_result_for_approval_snapshot

            trade_dec = result.get("trade_decision") or {}
            analyst_reports = result.get("analyst_reports") or {}
            technical_report = analyst_reports.get("technical") or {}
            entry_price = (
                trade_dec.get("limit_price")
                or technical_report.get("current_price")
                or technical_report.get("price")
            )
            final_qty = result.get("final_quantity", 1) or 1
            timeframe = technical_report.get("timeframe")  # Extract timeframe from signal
            snap = pipeline_result_for_approval_snapshot(result)
            approval_id = _db_manager.insert_pending_approval(
                symbol=symbol,
                action=final_action,
                quantity=float(final_qty),
                entry_price=float(entry_price) if entry_price else None,
                pipeline_snapshot=snap,
                timeframe=timeframe,
            )
            logger.info(
                "[APPROVAL] Queued %s %s qty=%s entry=%s for human review — approval_id=%s",
                symbol,
                final_action.upper(),
                final_qty,
                f"{float(entry_price):.4f}" if entry_price else "none",
                approval_id[:8],
            )
            from notifications.pending_approval_notify import (
                notify_pending_approval_queued,
            )

            await notify_pending_approval_queued(
                approval_id=approval_id,
                symbol=symbol,
                action=final_action,
                quantity=float(final_qty),
                entry_price=float(entry_price) if entry_price else None,
            )
        except Exception as exc:
            logger.error("[APPROVAL] Failed to queue pending approval for %s: %s", symbol, exc)

    elif is_directional and requires_human and _db_manager is None:
        logger.warning(
            "[APPROVAL] Cannot queue %s %s — db_manager not injected. Trade skipped.",
            symbol,
            final_action.upper(),
        )

    elif is_directional and not requires_human and _paper_tracker is not None:
        # No human approval required — auto-log paper trade immediately
        try:
            _guard_background_paper_open(symbol)

            trade_dec = result.get("trade_decision") or {}
            analyst_reports = result.get("analyst_reports") or {}
            technical_report = analyst_reports.get("technical") or {}
            fund_decision = result.get("fund_decision") or {}

            # Entry price: prefer limit_price, then current market price from technical analyst
            entry_price = (
                trade_dec.get("limit_price")
                or technical_report.get("current_price")
                or technical_report.get("price")
            )
            stop_price = trade_dec.get("stop_price") or None
            target_price = trade_dec.get("target_price") or trade_dec.get("take_profit") or None
            conviction = fund_decision.get("final_conviction", 0.0) or trade_dec.get(
                "confidence", 0.0
            )
            final_qty = result.get("final_quantity", 1) or 1

            if entry_price:
                broker_order = await _submit_broker_entry_with_stop(
                    symbol=symbol,
                    action=final_action,
                    quantity=final_qty,
                    entry_price=float(entry_price),
                    stop_price=float(stop_price) if stop_price else None,
                )

                # Collect regime metadata from technical analyst for attribution
                regime_label = technical_report.get("regime") or "unknown"
                regime_bias = (
                    technical_report.get("trend") or technical_report.get("bias") or "unknown"
                )
                regime_layers = technical_report.get(
                    "regime_layers_aligned"
                ) or technical_report.get("layers_aligned")
                stc_val = (technical_report.get("indicators") or {}).get("stc_value")

                # Persist per-analyst signals so AgentFeedbackTracker.record_outcome
                # can compute Brier/IC calibration when this trade closes (Novel #2).
                _analyst_signals = build_analyst_signals_map(analyst_reports)
                trade_id = _paper_tracker.add_paper_trade(
                    symbol=symbol,
                    side=final_action,
                    quantity=float(final_qty),
                    entry_price=float(entry_price),
                    stop_loss=float(stop_price) if stop_price else None,
                    take_profit=float(target_price) if target_price else None,
                    strategy_params={
                        "source": "pipeline",
                        "conviction": round(float(conviction), 4),
                        "direction": final_action.upper(),
                        "summary": result.get("summary", ""),
                        "regime": regime_label,
                        "bias": regime_bias,
                        "regime_layers_aligned": regime_layers,
                        "entry_stc_value": (
                            round(float(stc_val), 2) if stc_val is not None else None
                        ),
                        "pipeline_conviction": round(float(conviction), 4),
                        "predicted_direction": final_action.upper(),
                        "analyst_signals": _analyst_signals,
                        "broker_entry_order_id": (
                            broker_order.get("entry_order_id") if broker_order else None
                        ),
                        "broker_stp_order_id": (
                            broker_order.get("stp_order_id") if broker_order else None
                        ),
                        "broker_stp_linked": (
                            broker_order.get("stp_linked") if broker_order else None
                        ),
                        "broker_routed_to_ib": (
                            broker_order.get("routed_to_ib") if broker_order else None
                        ),
                    },
                )
                logger.info(
                    "[PAPER] Auto-logged %s %s qty=%s @ %.4f  sl=%s  tp=%s  conviction=%.0f%%  id=%s",
                    symbol,
                    final_action.upper(),
                    final_qty,
                    float(entry_price),
                    f"{stop_price:.4f}" if stop_price else "none",
                    f"{target_price:.4f}" if target_price else "none",
                    float(conviction) * 100,
                    trade_id[:8],
                )
            else:
                logger.warning(
                    "[PAPER] Skipped auto-log for %s %s — no entry price available "
                    "(technical analyst did not return current_price)",
                    symbol,
                    final_action.upper(),
                )
        except Exception as exc:
            logger.error("[PAPER] Auto-log failed for %s: %s", symbol, exc)

    elif is_directional and not requires_human and _paper_tracker is None:
        logger.warning(
            "[PAPER] Skipping paper trade log for %s %s — paper_tracker not injected",
            symbol,
            final_action.upper(),
        )

    # Multi-channel signal broadcast for non-HOLD decisions (Telegram/Discord/
    # WhatsApp/Windows toast). Shared cooldown dedupes vs the in-pipeline send.
    if final_action not in ("hold", "HOLD"):
        try:
            from notifications.signal_broadcast import broadcast_signal

            await broadcast_signal(symbol, result, source="router")
        except Exception as exc:
            logger.error("[PIPELINE] Signal broadcast failed for %s: %s", symbol, exc)


@router.post("/run/background")
async def run_pipeline(request: PipelineRunRequest):
    """
    Execute the full 5-stage trading pipeline for a symbol.

    Starts the pipeline as a background task and returns immediately.
    When the pipeline produces a LONG or SHORT decision the result is
    automatically recorded in the paper portfolio tracker.

    Pipeline stages: analysts → debate → trader → risk manager → fund manager.

    Request body:
        symbol (str): Trading symbol (e.g., "MCL", "MNQ", "SPY")
        is_futures (bool): True for futures contracts, False for options

    Returns:
        status: "running" | "halted"
        symbol: The requested symbol
        is_futures: The instrument type
        message: Description of result
        pipeline_id: Task ID (for debugging)
    """
    try:
        if _trading_pipeline is None:
            raise ValueError("Trading pipeline not initialized (ANTHROPIC_API_KEY missing)")

        if _safety_layer is None:
            raise ValueError("Safety layer not initialized")

        # Normalize symbol
        symbol = request.symbol.upper().strip()

        # Check if kill switch is active
        safety_status = _safety_layer.get_status()
        if safety_status.get("kill_switch_active"):
            return {
                "status": "halted",
                "message": "Kill switch is active",
                "reason": safety_status.get("kill_switch_reason"),
            }

        # Queue pipeline execution as background task (non-blocking)
        # The wrapper coroutine handles paper trade logging after the pipeline completes.
        task = asyncio.create_task(
            _run_pipeline_and_log(symbol=symbol, is_futures=request.is_futures)
        )

        logger.info(
            "[PIPELINE] Started background task for %s (futures=%s)", symbol, request.is_futures
        )

        return {
            "status": "running",
            "symbol": symbol,
            "is_futures": request.is_futures,
            "message": "Pipeline execution started",
            "pipeline_id": task.get_name(),
        }
    except ValueError as e:
        logger.error(f"[PIPELINE] Validation error: {e}")
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error(f"[PIPELINE] run_pipeline failed: {e}")
        raise HTTPException(500, f"Pipeline execution failed: {e}") from e


@router.get("/cost-summary", response_model=CostSummaryResponse)
async def cost_summary() -> CostSummaryResponse:
    """
    Get LLM cost tracking summary across all pipeline runs.

    MODEL_RATES for reference:
    - claude-sonnet-4-6: input=$3/MTok, output=$15/MTok
    - claude-haiku-4-5: input=$0.25/MTok, output=$1.25/MTok

    Returns:
        today_usd: Total cost for today (UTC)
        this_week_usd: Total cost for the past 7 days
        all_time_usd: Total cost across all recorded calls
        cost_per_trade_usd: Average cost per unique run_id (approximation)
        top_expensive_stages: Top 5 stages by avg token usage
    """
    try:
        if _db_manager is None:
            # Graceful fallback if db_manager not injected
            return CostSummaryResponse(
                today_usd=0.0,
                this_week_usd=0.0,
                all_time_usd=0.0,
                cost_per_trade_usd=0.0,
                top_expensive_stages=[],
            )

        result = _db_manager.get_cost_summary()
        logger.info(
            "[COST] Summary: today=%.4f, week=%.4f, all_time=%.4f, per_trade=%.4f",
            result.get("today_usd", 0.0),
            result.get("this_week_usd", 0.0),
            result.get("all_time_usd", 0.0),
            result.get("cost_per_trade_usd", 0.0),
        )
        return CostSummaryResponse(**result)
    except Exception as e:
        logger.warning("[COST] Table unavailable or query failed (likely no migration 009): %s", e)
        # Return zeroed response gracefully if table doesn't exist
        return CostSummaryResponse(
            today_usd=0.0,
            this_week_usd=0.0,
            all_time_usd=0.0,
            cost_per_trade_usd=0.0,
            top_expensive_stages=[],
        )


@router.post("/run/sdk")
async def run_sdk_pipeline(request: PipelineRunRequest):
    """
    Run the 5-stage trading pipeline via Claude Agent SDK (managed agents).

    Additive parallel path alongside /pipeline/run. Uses the claude-agent-sdk
    to orchestrate 10 specialist subagents with parallel Stage 1 analysis and
    Stage 2 debate. Output format is compatible with /pipeline/run for dashboard
    consumption. The existing /pipeline/run endpoint is unaffected.
    """
    from fastapi import HTTPException

    if _sdk_pipeline is None:
        raise HTTPException(
            503,
            "SDK pipeline not available — requires claude-agent-sdk and ANTHROPIC_API_KEY",
        )

    result = await _sdk_pipeline.analyze_and_decide(
        symbol=request.symbol,
        interval=request.interval,
        is_futures=request.is_futures,
    )

    logger.info(
        "[SDK-PIPELINE] %s %s → %s (confidence=%.0f%%)",
        request.symbol,
        request.interval,
        result.get("final_action", "hold").upper(),
        float(result.get("confidence", 0)) * 100,
    )

    return result


@router.get("/shadow-metrics")
async def get_shadow_metrics(strategy_name: Optional[str] = None):
    """Fetch performance metrics for shadow trades."""
    if _sdk_pipeline is None:
        raise HTTPException(503, "SDK pipeline not available")

    metrics = _sdk_pipeline._shadow_tracker.get_shadow_performance(strategy_name=strategy_name)
    return metrics


@router.get("/history")
async def get_pipeline_history(limit: int = 50, symbol: str = ""):
    """
    Return historical pipeline run records from SQLite.
    Query params:
        limit  : max rows to return (default 50, capped at 200)
        symbol : filter by ticker symbol (optional, case-insensitive)
    """
    if not _db_manager:
        return {"runs": [], "count": 0, "note": "db_manager not initialized"}
    try:
        limit = min(max(1, limit), 200)
        runs = _db_manager.get_pipeline_history(
            limit=limit,
            symbol=symbol.upper() if symbol else None,
        )
        return {"runs": runs, "count": len(runs)}
    except Exception as exc:
        logger.error(f"[DB] get_pipeline_history failed: {exc}")
        return {"runs": [], "count": 0, "error": str(exc)}


@router.post("/run")
async def run_pipeline_sync(req: PipelineRunRequest):
    """Run the full 5-stage AI trading pipeline for a symbol"""
    import asyncio

    from config import settings

    if not _trading_pipeline:
        raise HTTPException(503, "Pipeline not available (no ANTHROPIC_API_KEY)")

    result = await _trading_pipeline.analyze_and_decide(
        req.symbol, req.is_futures, timeframe=req.interval
    )

    final_action = result.get("final_action", "hold")

    _fund_dec = result.get("fund_decision") or {}
    _trade_dec = result.get("trade_decision") or {}
    if _log_decision_fn:
        _log_decision_fn(
            symbol=req.symbol,
            action=final_action,
            confidence=float(
                result.get("boosted_confidence")
                or _fund_dec.get("final_conviction")
                or _trade_dec.get("confidence")
                or 0.0
            ),
            source="pipeline",
            summary=result.get("summary", ""),
            reasoning=_trade_dec.get("reasoning", ""),
            full_pipeline_data=result,
        )

    _approved_for_paper = {s.upper() for s in (settings.FUTURES_WATCHLIST or [])}
    if (
        not settings.LIVE_TRADING_ENABLED
        and final_action != "hold"
        and req.symbol.upper() in _approved_for_paper
    ):
        try:
            trade_dec = result.get("trade_decision") or {}
            entry_price = (
                trade_dec.get("limit_price")
                or trade_dec.get("stop_price")
                or (result.get("technical", {}) or {}).get("current_price")
            )
            final_qty = result.get("final_quantity", 1) or 1

            if result.get("requires_human") and _db_manager:
                approval_id = _db_manager.insert_pending_approval(
                    symbol=req.symbol,
                    action=final_action,
                    quantity=float(final_qty),
                    entry_price=float(entry_price) if entry_price else None,
                    pipeline_snapshot=result,
                    timeframe=result.get("timeframe", "1h"),
                )
                result["pending_approval_id"] = approval_id
                logger.info(
                    f"[PAPER] Human gate — inserted pending approval {approval_id[:8]} "
                    f"for {req.symbol} {final_action.upper()}"
                )
                try:
                    from notifications.pending_approval_notify import (
                        notify_pending_approval_queued as _notify_approval,
                    )

                    asyncio.create_task(
                        _notify_approval(
                            approval_id=approval_id,
                            symbol=req.symbol,
                            action=final_action,
                            quantity=float(final_qty),
                            entry_price=float(entry_price) if entry_price else None,
                        )
                    )
                except Exception as _notify_exc:
                    logger.warning("[PAPER] Approval notify task failed: %s", _notify_exc)
                try:
                    from notifications.openclaw_notifier import (
                        notify_approval_required as _oc_approval,
                    )

                    asyncio.create_task(
                        _oc_approval(
                            symbol=req.symbol,
                            action=final_action,
                            quantity=float(final_qty),
                            entry_price=float(entry_price) if entry_price else 0.0,
                        )
                    )
                except Exception as _oc_exc:
                    logger.warning("[PAPER] OpenClaw approval notify failed: %s", _oc_exc)
            elif _paper_tracker and entry_price:
                _analyst_signals = build_analyst_signals_map(result.get("analyst_reports"))
                trade_id = _paper_tracker.add_paper_trade(
                    symbol=req.symbol,
                    side=final_action,
                    quantity=float(final_qty),
                    entry_price=float(entry_price),
                    stop_loss=(
                        float(trade_dec.get("stop_price")) if trade_dec.get("stop_price") else None
                    ),
                    take_profit=float(
                        trade_dec.get("target_price") or trade_dec.get("take_profit") or 0
                    )
                    or None,
                    strategy_params={
                        "source": "pipeline",
                        "summary": result.get("summary", ""),
                        "predicted_direction": final_action.upper(),
                        "analyst_signals": _analyst_signals,
                    },
                )
                result["paper_trade_id"] = trade_id
                logger.info(
                    f"[PAPER] Auto-logged {req.symbol} {final_action.upper()} "
                    f"qty={final_qty} @ {entry_price:.4f}  id={trade_id[:8]}"
                )
            elif not entry_price:
                logger.warning(
                    f"[PAPER] Skipped auto-log for {req.symbol} {final_action.upper()} "
                    f"— could not determine entry price from pipeline result"
                )
        except Exception as exc:
            logger.error(f"[PAPER] Auto-log failed for {req.symbol}: {exc}")

    # Legacy catch-all auto-log path. The watchlist-gated block above already
    # handles every symbol in _approved_for_paper -- either deferring to a
    # human approval (requires_human=True) or auto-logging via
    # add_paper_trade() (requires_human=False). This block must only run
    # for the leftover case that block never reaches (symbol not on
    # _approved_for_paper). Without this guard it ran unconditionally after
    # the block above for every watchlist symbol too, defeating the human
    # approval gate (opened a live paper trade the instant the gate above
    # had just queued a pending approval for the same decision) and, even
    # when no approval was required, duplicated the trade a second time
    # (two open_trade calls for one pipeline decision). Found during the
    # PR #331 naked-row completeness sweep (US-010); see
    # docs/incident-notes/2026-07-07-trade-287-stop-enforcement-chain.md.
    _already_handled = bool(result.get("pending_approval_id") or result.get("paper_trade_id"))
    if (
        not settings.LIVE_TRADING_ENABLED
        and final_action != "hold"
        and _paper_tracker
        and not _already_handled
    ):
        try:
            trade_dec = result.get("trade_decision") or {}
            entry_price = (
                trade_dec.get("limit_price")
                or trade_dec.get("stop_price")
                or (result.get("technical", {}) or {}).get("current_price")
            )
            final_qty = result.get("final_quantity", 1) or 1

            if entry_price:
                trade_id = _paper_tracker.open_trade(
                    symbol=req.symbol,
                    action=final_action,
                    quantity=float(final_qty),
                    price=float(entry_price),
                    notes=result.get("summary", ""),
                    analyst_signals=build_analyst_signals_map(
                        result.get("analyst_reports")
                    ),
                )
                result["paper_trade_id"] = trade_id
                logger.info(
                    f"[PAPER] Auto-logged {req.symbol} {final_action.upper()} "
                    f"qty={final_qty} @ {entry_price:.4f}  id={trade_id[:8]}"
                )
            else:
                logger.warning(
                    f"[PAPER] Skipped auto-log for {req.symbol} {final_action.upper()} "
                    f"— could not determine entry price from pipeline result"
                )
        except Exception as exc:
            logger.error(f"[PAPER] Auto-log failed for {req.symbol}: {exc}")

    from notifications.signal_broadcast import broadcast_signal

    asyncio.create_task(broadcast_signal(req.symbol, result, source="router_sync"))

    return result


@router.get("/status")
async def pipeline_status():
    """Pipeline availability and last run info"""
    return {
        "available": _trading_pipeline is not None,
        "sdk_available": _sdk_pipeline is not None,
        "last_run": _decision_log_ref[-1] if _decision_log_ref else None,
        "decision_count": len(_decision_log_ref),
    }
