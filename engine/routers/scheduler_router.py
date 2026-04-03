"""Scheduler management router - query and manage scheduled jobs."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
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
