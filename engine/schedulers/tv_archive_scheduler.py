"""
JARVIS TRADER — TV Snapshot Archive Scheduler

Captures a TVIndicatorSnapshot for each watchlist symbol every hour at :01
(one minute after the hourly bar close) and persists it to SQLite via
TVSnapshotArchive.

The scheduler is intentionally conservative:
  * One call per symbol, sequentially (no fan-out) — TradingView CDP is
    single-session, parallel calls can race.
  * Each call is wrapped in try/except — a single symbol failing must not
    stop the sweep.
  * If TradingView is offline, `get_snapshot()` returns data_quality
    "unavailable" and we still record that (useful for uptime analytics).

Usage:
    from schedulers.tv_archive_scheduler import start_scheduler
    scheduler = start_scheduler()  # returns the AsyncIOScheduler instance
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger("jarvis_trader.tv_archive_scheduler")

# Default watchlist used when config.FUTURES_WATCHLIST is unavailable.
_DEFAULT_WATCHLIST: List[str] = ["MES", "MCL", "MNQ"]


def _resolve_watchlist() -> List[str]:
    """Prefer the engine config's FUTURES_WATCHLIST; fall back to defaults."""
    try:
        from config import settings  # type: ignore

        watchlist = getattr(settings, "FUTURES_WATCHLIST", None)
        if watchlist:
            return [str(s).upper() for s in watchlist]
    except Exception as exc:
        logger.debug("[TV-ARCHIVE] config.FUTURES_WATCHLIST unavailable: %s", exc)
    return list(_DEFAULT_WATCHLIST)


async def archive_all_once() -> dict:
    """
    Sweep every watchlist symbol once and archive its current TV snapshot.

    Returns a summary dict — useful for debugging and for manual trigger
    endpoints.
    """
    from analytics.tv_snapshot_archive import TVSnapshotArchive
    from data.tv_indicator_bridge import get_tv_bridge

    archive = TVSnapshotArchive()
    bridge = get_tv_bridge()

    symbols = _resolve_watchlist()
    results: dict = {"symbols": [], "archived": 0, "errors": 0, "offline": 0}

    for symbol in symbols:
        try:
            # get_snapshot is sync (subprocess-based); run in a thread
            snap = await asyncio.to_thread(bridge.get_snapshot, symbol)
            row_id = archive.archive_snapshot(snap, symbol_override=symbol)
            is_live = getattr(snap, "data_quality", "unavailable") == "live"
            if not is_live:
                results["offline"] += 1
            results["archived"] += 1 if row_id > 0 else 0
            results["symbols"].append(
                {
                    "symbol": symbol,
                    "row_id": row_id,
                    "data_quality": getattr(snap, "data_quality", "unavailable"),
                }
            )
            logger.info(
                "[TV-ARCHIVE] %s archived id=%s quality=%s",
                symbol,
                row_id,
                getattr(snap, "data_quality", "unavailable"),
            )
        except Exception as exc:
            results["errors"] += 1
            logger.warning("[TV-ARCHIVE] %s failed: %s", symbol, exc)
            results["symbols"].append({"symbol": symbol, "error": str(exc)})

    archive.close()
    logger.info(
        "[TV-ARCHIVE] Sweep complete — archived=%d offline=%d errors=%d",
        results["archived"],
        results["offline"],
        results["errors"],
    )
    return results


def start_scheduler() -> Optional[object]:
    """
    Register the hourly sweep job with APScheduler.

    Must be called from an active asyncio loop. Returns the scheduler
    instance so the caller can shut it down gracefully on app stop.
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error("[TV-ARCHIVE] APScheduler not installed — scheduler disabled")
        return None

    scheduler = AsyncIOScheduler(timezone="UTC")
    # Fire at minute=1 every hour — one minute after each hourly bar close.
    scheduler.add_job(
        archive_all_once,
        CronTrigger(minute=1),
        id="tv_snapshot_archive_hourly",
        replace_existing=True,
        misfire_grace_time=60,
    )

    try:
        scheduler.start()
    except Exception as exc:
        logger.error("[TV-ARCHIVE] scheduler.start failed: %s", exc)
        return None

    logger.info(
        "[TV-ARCHIVE] Hourly sweep scheduled (cron minute=1, UTC) for %d symbols",
        len(_resolve_watchlist()),
    )
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # One-shot sweep for manual testing
    result = asyncio.run(archive_all_once())
    print(result)
