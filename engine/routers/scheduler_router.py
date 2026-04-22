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


# Global reference (injected from main.py)
_scheduler = None


def inject_scheduler(scheduler) -> None:
    """Inject scheduler instance from main.py."""
    global _scheduler
    _scheduler = scheduler


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
