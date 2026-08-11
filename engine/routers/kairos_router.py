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
    """List registered watchers with today's per-watcher hit stats.

    daemon.get_status()["watchers"] is only a list of bare name strings —
    per-watcher counters aren't tracked on the daemon itself. Enrich each
    name here from today's ObservationLog so the dashboard's Watchers list
    gets the {name, enabled, hit_count_today, warning_count_today,
    critical_count_today, last_observation} shape it expects.
    """
    daemon = get_kairos()
    if not daemon:
        return {"watchers": [], "enabled": False}
    status = daemon.get_status()
    watcher_names = status.get("watchers", [])

    from kairos.observation_log import ObservationLog

    log = ObservationLog()
    today_obs = log.read_today()

    stats_by_watcher: dict[str, dict] = {}
    for obs in today_obs:
        name = obs.get("watcher")
        if not name:
            continue
        entry = stats_by_watcher.setdefault(
            name,
            {
                "hit_count_today": 0,
                "warning_count_today": 0,
                "critical_count_today": 0,
                "last_observation": None,
            },
        )
        entry["hit_count_today"] += 1
        severity = obs.get("severity")
        if severity == "warning":
            entry["warning_count_today"] += 1
        elif severity == "critical":
            entry["critical_count_today"] += 1
        timestamp = obs.get("timestamp")
        if timestamp and (
            entry["last_observation"] is None or timestamp > entry["last_observation"]
        ):
            entry["last_observation"] = timestamp

    watchers = []
    for name in watcher_names:
        stats = stats_by_watcher.get(name, {})
        watchers.append(
            {
                "name": name,
                # All registered watchers run every tick — there is no
                # per-watcher disable switch on the daemon today.
                "enabled": True,
                "hit_count_today": stats.get("hit_count_today", 0),
                "warning_count_today": stats.get("warning_count_today", 0),
                "critical_count_today": stats.get("critical_count_today", 0),
                "last_observation": stats.get("last_observation"),
            }
        )

    return {"watchers": watchers, "running": status.get("running", False)}


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
