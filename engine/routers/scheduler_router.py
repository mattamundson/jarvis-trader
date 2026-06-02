"""Scheduler management router - query and manage scheduled jobs."""

import logging
from datetime import datetime
from typing import Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict

from config import settings

router = APIRouter(prefix="/scheduler", tags=["scheduler"])
logger = logging.getLogger(__name__)


class JobInfo(BaseModel):
    """Information about a scheduled job."""

    id: str
    name: str
    next_run_time: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class JobsListResponse(BaseModel):
    """Response containing list of scheduled jobs."""

    total_jobs: int
    jobs: list[JobInfo]

    model_config = ConfigDict(from_attributes=True)


class TriggerResponse(BaseModel):
    """Response for manual trigger endpoint."""

    triggered: bool
    timestamp: str

    model_config = ConfigDict(from_attributes=True)


# Global reference (injected from main.py)
_scheduler = None
# Additional globals required by the migrated /scheduler/scan-now handler.
_trading_pipeline = None
_safety_layer = None
_db_manager = None


def inject_scheduler(scheduler) -> None:
    """Inject scheduler instance from main.py."""
    global _scheduler
    _scheduler = scheduler


def inject_scan_dependencies(trading_pipeline=None, safety_layer=None, db_manager=None) -> None:
    """Inject dependencies required by the migrated /scheduler/scan-now handler."""
    global _trading_pipeline, _safety_layer, _db_manager
    if trading_pipeline is not None:
        _trading_pipeline = trading_pipeline
    if safety_layer is not None:
        _safety_layer = safety_layer
    if db_manager is not None:
        _db_manager = db_manager


@router.get("/jobs")
async def get_scheduled_jobs() -> JobsListResponse:
    """
    Get list of registered scheduler jobs.

    Returns:
        total_jobs: Number of scheduled jobs
        jobs: List of job details (id, name, next_run_time)
    """
    try:
        jobs_list: list[JobInfo] = []

        if _scheduler is None:
            return JobsListResponse(total_jobs=0, jobs=[])

        for job in _scheduler.get_jobs():
            next_run_str = job.next_run_time.isoformat() if job.next_run_time is not None else None
            jobs_list.append(
                JobInfo(
                    id=job.id,
                    name=job.name or job.id,
                    next_run_time=next_run_str,
                )
            )

        return JobsListResponse(total_jobs=len(jobs_list), jobs=jobs_list)

    except Exception as e:
        logger.error(f"Failed to get scheduled jobs: {e}")
        raise HTTPException(500, f"Failed to get scheduled jobs: {e}") from e


@router.post("/morning-brief/trigger")
async def trigger_morning_brief(background_tasks: BackgroundTasks) -> dict:
    """Manually trigger morning intelligence brief (for testing).

    Auth is handled globally by middleware. Runs assembly + send in background.
    """

    async def _run() -> None:
        try:
            from notifications.morning_brief import assemble_morning_brief
            from notifications.openclaw_notifier import send_raw

            brief = await assemble_morning_brief()
            await send_raw(brief)
            logger.info("[MorningBrief] Manual trigger complete")
            try:
                import asyncio
                from notifications.discord_notifier import discord_morning_brief
                asyncio.create_task(discord_morning_brief(brief))
            except Exception as exc:
                logger.debug("[Scheduler] Discord brief send failed: %s", exc)
        except Exception as exc:
            logger.error("[MorningBrief] Manual trigger failed: %s", exc)

    background_tasks.add_task(_run)
    return {"status": "triggered", "message": "Morning brief sending in background"}


@router.post("/discord-import/trigger")
async def trigger_discord_import() -> TriggerResponse:
    """
    Manually trigger the Discord nightly import job.

    Returns:
        triggered: True if the job was triggered successfully
        timestamp: ISO timestamp of the trigger
    """
    try:
        if _scheduler is None:
            raise HTTPException(500, "Scheduler not initialized")

        job = _scheduler.get_job("nightly_discord_import")
        if job is None:
            raise HTTPException(404, "Discord import job not found in scheduler")

        await job.func()

        return TriggerResponse(triggered=True, timestamp=datetime.utcnow().isoformat())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger Discord import: {e}")
        raise HTTPException(500, f"Failed to trigger Discord import: {e}") from e


# ── Migrated from main.py inline routes ──────────────────────────────────────

# Supporting definitions carried over from main.py so the migrated scan-now
# handler below remains functional (decision logging + WhatsApp delivery).
_decision_log: list[dict] = []  # In-memory ring buffer, 100 entries


def _log_decision(
    symbol: str,
    action: str,
    confidence: float = 0.0,
    source: str = "unknown",
    summary: str = "",
    reasoning: str = "",
    regime: str | None = None,
    signal_data: dict | None = None,
    full_pipeline_data: dict | None = None,
) -> None:
    """Append a decision to the in-memory ring buffer AND persist to SQLite."""
    entry: dict = {
        "id": len(_decision_log) + 1,
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "source": source,
        "summary": summary,
    }
    _decision_log.append(entry)
    if len(_decision_log) > 100:
        _decision_log.pop(0)

    # Persist to SQLite (non-blocking best-effort — never crash the caller)
    if _db_manager:
        try:
            _db_manager.insert_decision(
                symbol=symbol,
                action=action,
                confidence=confidence,
                regime=regime,
                signal_data=signal_data or {"source": source, "summary": summary},
                reasoning=reasoning or summary,
                full_pipeline_data=full_pipeline_data,
            )
        except Exception as _db_err:
            logger.warning(f"[DB] Failed to persist decision for {symbol}: {_db_err}")


def _log_pipeline_whatsapp_to_alert_log(
    symbol: str,
    message: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Persist pipeline WhatsApp outcomes (sent, failed, suppressed) for audit."""
    if _db_manager is None:
        return
    try:
        _db_manager.insert_alert_log(
            alert_type="pipeline_signal",
            message=message,
            channel="whatsapp",
            symbol=symbol,
            status=status,
            error=error,
        )
    except Exception as exc:
        logger.warning("alert_log pipeline_signal insert failed (non-fatal): %s", exc)


async def _deliver_pipeline_whatsapp_if_eligible(
    symbol: str,
    action: str,
    qty: int,
    price_info,
    reasoning: str,
    confidence: float,
) -> Tuple[bool, Optional[str]]:
    """
    Send Twilio WhatsApp for a non-HOLD pipeline result when cooldown allows.

    Returns (delivered_to_twilio, suppressed_reason). ``suppressed_reason`` is None
    on successful send; ``send_failed`` when Twilio returns false; otherwise a
    short code for API responses (manual scan).
    """
    from notifications.pipeline_alert_cooldown import (
        get_last_pipeline_alert_sent,
        mark_pipeline_alert_sent,
        pipeline_alert_decision,
    )
    from notifications.whatsapp import get_notifier

    notifier = get_notifier()
    now = datetime.now()
    last_sent = get_last_pipeline_alert_sent(symbol)
    decision = pipeline_alert_decision(
        last_sent=last_sent,
        now=now,
        cooldown_minutes=settings.ALERT_COOLDOWN_MINUTES,
        notifier_enabled=notifier.enabled,
    )
    price_str = f" @ {price_info:.2f}" if price_info else ""
    pct = int(confidence * 100)
    short_reason = (reasoning[:100] + "...") if len(reasoning) > 100 else reasoning
    msg = (
        f"JARVIS: {symbol} -> {action.upper()} {qty}{price_str}\n"
        f"Confidence: {pct}%\n"
        f"Reason: {short_reason}"
    )

    if decision == "send":
        sent = await notifier.send(msg)
        if sent:
            mark_pipeline_alert_sent(symbol, now)
            _log_pipeline_whatsapp_to_alert_log(symbol, msg, "sent")
            logger.info("WhatsApp alert sent for %s (%s)", symbol, action.upper())
            return True, None
        _log_pipeline_whatsapp_to_alert_log(
            symbol, msg, "failed", error="twilio_send_returned_false"
        )
        logger.warning("WhatsApp alert failed for %s", symbol)
        return False, "send_failed"

    if decision == "suppressed_cooldown":
        tail = last_sent.strftime("%H:%M") if last_sent else "unknown"
        logger.info(
            "WhatsApp alert for %s suppressed — cooldown active (last sent %s)",
            symbol,
            tail,
        )
        _log_pipeline_whatsapp_to_alert_log(
            symbol,
            msg,
            "suppressed_cooldown",
            error=(f"last_sent={last_sent.isoformat()}" if last_sent else "last_sent=n/a"),
        )
        return False, f"cooldown_active_since_{tail}"

    logger.info("WhatsApp alert for %s suppressed — WhatsApp not configured", symbol)
    _log_pipeline_whatsapp_to_alert_log(
        symbol, msg, "suppressed", error="whatsapp_not_configured"
    )
    return False, "whatsapp_not_configured"


@router.post("/scan-now")
async def trigger_scan_now():
    """
    Manually trigger a full watchlist scan immediately.
    Runs the same pipeline as the scheduled job — useful for testing outside market hours.
    Respects kill switch. Does NOT bypass the 2-hour WhatsApp rate limit.
    """
    if not _trading_pipeline:
        raise HTTPException(503, "Pipeline not available (no ANTHROPIC_API_KEY)")
    if not _safety_layer:
        raise HTTPException(503, "Safety layer not initialized")

    safety = _safety_layer.get_status()
    if safety.get("kill_switch_active"):
        return {"status": "skipped", "reason": "kill_switch_active"}

    symbols_to_scan = [(sym, True) for sym in settings.FUTURES_WATCHLIST] + [
        (sym, False) for sym in settings.OPTIONS_WATCHLIST[:3]
    ]

    logger.info(f"Manual scan triggered: {[s[0] for s in symbols_to_scan]}")

    scan_results = []
    for symbol, is_futures in symbols_to_scan:
        try:
            result = await _trading_pipeline.analyze_and_decide(symbol, is_futures)
            action = result.get("final_action", "hold")

            fund_dec = result.get("fund_decision") or {}
            trade_dec = result.get("trade_decision") or {}
            confidence = fund_dec.get("final_conviction", trade_dec.get("confidence", 0.0))
            qty = result.get("final_quantity", 0)
            price_info = trade_dec.get("limit_price") or trade_dec.get("stop_price")
            reasoning = trade_dec.get("reasoning", "")

            # Log to decision feed (in-memory + SQLite)
            _log_decision(
                symbol=symbol,
                action=action,
                confidence=float(confidence),
                source="manual_scan",
                summary=result.get("summary", ""),
                reasoning=reasoning,
                full_pipeline_data=result,
            )

            alert_sent = False
            alert_suppressed_reason = None

            if action not in ("hold",):
                alert_sent, alert_suppressed_reason = await _deliver_pipeline_whatsapp_if_eligible(
                    symbol=symbol,
                    action=action,
                    qty=qty,
                    price_info=price_info,
                    reasoning=reasoning,
                    confidence=float(confidence),
                )

            scan_results.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "confidence": round(confidence, 4),
                    "final_quantity": qty,
                    "summary": result.get("summary", ""),
                    "errors": result.get("errors", []),
                    "alert_sent": alert_sent,
                    "alert_suppressed_reason": alert_suppressed_reason,
                }
            )

        except Exception as e:
            logger.error(f"Manual scan failed for {symbol}: {e}")
            scan_results.append({"symbol": symbol, "error": str(e)})

    return {
        "status": "complete",
        "scanned_at": datetime.now().isoformat(),
        "symbols_scanned": len(scan_results),
        "results": scan_results,
    }

@router.get("/scheduler/status")
async def scheduler_status():
    """Scheduled job status"""
    if not scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
            }
        )
    return {
        "running": scheduler.running,
        "jobs": jobs,
        "total_decisions_logged": len(_decision_log),
    }


