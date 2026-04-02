"""Pipeline notification router - test webhooks."""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


class PipelineRunRequest(BaseModel):
    """Request to execute the trading pipeline for a symbol"""

    symbol: str = Field(..., description="Trading symbol (e.g., MCL, MNQ, SPY)")
    is_futures: bool = Field(True, description="True for futures, False for options")


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

# Global references (injected from main.py)
_scheduler = None
_trading_pipeline = None
_safety_layer = None
_db_manager = None


def inject_dependencies(scheduler, trading_pipeline, safety_layer, db_manager):
    """Inject global dependencies from main.py"""
    global _scheduler, _trading_pipeline, _safety_layer, _db_manager
    _scheduler = scheduler
    _trading_pipeline = trading_pipeline
    _safety_layer = safety_layer
    _db_manager = db_manager


@router.post("/notifications/telegram/test")
async def test_telegram():
    """Test Telegram notification config"""
    from datetime import datetime
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
                    job.next_run_time.isoformat()
                    if job.next_run_time is not None
                    else None
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
    from datetime import datetime
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


@router.post("/run")
async def run_pipeline(request: PipelineRunRequest):
    """
    Execute the full 5-stage trading pipeline for a symbol.

    Starts the pipeline as a background task and returns immediately.
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
        task = asyncio.create_task(
            _trading_pipeline.analyze_and_decide(symbol=symbol, is_futures=request.is_futures)
        )

        logger.info(f"[PIPELINE] Started background task for {symbol} (futures={request.is_futures})")

        return {
            "status": "running",
            "message": "Pipeline execution started",
            "symbol": symbol,
            "is_futures": request.is_futures,
            "pipeline_id": id(task),
        }
    except Exception as e:
        logger.error(f"[PIPELINE] Execution failed: {e}")
        raise HTTPException(500, f"Pipeline execution failed: {e}") from e
