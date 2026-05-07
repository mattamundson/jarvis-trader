import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger(__name__)


class EventsResponse:
    """Response model for events endpoint."""
    def __init__(self, events: list[dict], count: int, buffer_size: int):
        self.events = events
        self.count = count
        self.buffer_size = buffer_size


@router.get("/recent")
async def get_recent_events(limit: Optional[int] = Query(20, ge=1, le=100)):
    """Get recent events from the ring buffer.

    Args:
        limit: Maximum number of events to return (1-100, default 20)

    Returns:
        JSON with events list, count, and buffer capacity
    """
    try:
        from events.bus import get_recent

        events = get_recent(limit)
        return {
            "events": events,
            "count": len(events),
            "buffer_size": 150,
        }
    except Exception as e:
        logger.error(f"Error retrieving recent events: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
