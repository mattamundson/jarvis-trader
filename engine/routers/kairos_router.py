"""KAIROS proactive monitoring daemon router."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from kairos import get_kairos

router = APIRouter(prefix="/kairos", tags=["kairos"])


@router.get("/status")
async def get_kairos_status():
    """Get KAIROS daemon status."""
    daemon = get_kairos()
    if not daemon:
        return {"running": False, "enabled": False, "message": "KAIROS not enabled"}
    return daemon.get_status()


@router.get("/observations")
async def get_observations(
    severity: Optional[str] = Query(None, description="Filter: info, warning, critical"),
    minutes: int = Query(60, description="Look back N minutes (0 = today's full log)"),
):
    """Get today's KAIROS observations."""
    daemon = get_kairos()
    if not daemon:
        return {"observations": [], "enabled": False}

    from kairos.observation_log import ObservationLog

    log = ObservationLog()

    if minutes > 0:
        obs = log.get_recent(minutes=minutes)
    else:
        obs = log.read_today()

    if severity:
        obs = [o for o in obs if o.get("severity") == severity]

    return {
        "observations": obs,
        "total": len(obs),
        "counts": log.count_by_severity(),
    }


@router.get("/observations/{date_str}")
async def get_observations_by_date(date_str: str):
    """Get observations for a specific date (YYYY-MM-DD)."""
    from kairos.observation_log import ObservationLog

    log = ObservationLog()
    obs = log.read_date(date_str)
    return {"date": date_str, "observations": obs, "total": len(obs)}


@router.get("/watchers")
async def get_watchers():
    """List registered watchers and their hit rates."""
    daemon = get_kairos()
    if not daemon:
        return {"watchers": [], "enabled": False}
    status = daemon.get_status()
    return {"watchers": status.get("watchers", []), "running": status.get("running", False)}


@router.post("/tick")
async def manual_tick():
    """Manually trigger one KAIROS tick (for testing)."""
    daemon = get_kairos()
    if not daemon:
        raise HTTPException(status_code=503, detail="KAIROS not enabled")
    await daemon.tick()
    return {"status": "tick_completed", "tick_count": daemon._tick_count}


@router.get("/dream/{date_str}")
async def get_dream_summary(date_str: str):
    """Get nightly consolidation summary for a specific date."""
    from kairos.dreaming import KairosDreamer
    from kairos.observation_log import ObservationLog

    dreamer = KairosDreamer(observation_log=ObservationLog())
    summary = await dreamer.dream(target_date=date_str)
    return summary


@router.post("/dream")
async def run_dream():
    """Manually trigger nightly consolidation for today."""
    from kairos.dreaming import KairosDreamer
    from kairos.observation_log import ObservationLog

    dreamer = KairosDreamer(observation_log=ObservationLog())
    summary = await dreamer.dream()
    return summary
