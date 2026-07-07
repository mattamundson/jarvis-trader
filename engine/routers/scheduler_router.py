"""Scheduler management router - query and manage scheduled jobs."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict

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


# Global references (injected from main.py)
_scheduler = None
_trading_pipeline = None
_safety_layer = None
_decision_log_ref: list[dict] = []
_log_decision_fn = None
_deliver_whatsapp_fn = None


def inject_scheduler(
    scheduler,
    trading_pipeline=None,
    safety_layer=None,
    decision_log=None,
    log_decision_fn=None,
    deliver_whatsapp_fn=None,
) -> None:
    """Inject scheduler and optional pipeline dependencies from main.py."""
    global _scheduler, _trading_pipeline, _safety_layer, _decision_log_ref, _log_decision_fn, _deliver_whatsapp_fn
    _scheduler = scheduler
    if trading_pipeline is not None:
        _trading_pipeline = trading_pipeline
    if safety_layer is not None:
        _safety_layer = safety_layer
    if decision_log is not None:
        _decision_log_ref = decision_log
    if log_decision_fn is not None:
        _log_decision_fn = log_decision_fn
    if deliver_whatsapp_fn is not None:
        _deliver_whatsapp_fn = deliver_whatsapp_fn


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


@router.get("/status")
async def scheduler_status():
    """Scheduled job status"""
    if not _scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
            }
        )
    return {
        "running": _scheduler.running,
        "jobs": jobs,
        "total_decisions_logged": len(_decision_log_ref),
    }


@router.post("/scan-now")
async def trigger_scan_now():
    """
    Manually trigger a full watchlist scan immediately.
    Runs the same pipeline as the scheduled job — useful for testing outside market hours.
    Respects kill switch. Does NOT bypass the 2-hour WhatsApp rate limit.
    """
    from config import settings

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

            if _log_decision_fn:
                _log_decision_fn(
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

            if action not in ("hold",) and _deliver_whatsapp_fn:
                alert_sent, alert_suppressed_reason = await _deliver_whatsapp_fn(
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
        "scanned_at": datetime.utcnow().isoformat(),
        "symbols_scanned": len(scan_results),
        "results": scan_results,
    }
