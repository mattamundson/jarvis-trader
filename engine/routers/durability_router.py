"""GET /ops/durability -- how long has the engine run clean?

Exposes the down-alert watchdog's outage ledger over HTTP so the dashboard can
show "days clean since the last outage" without a human running the CLI
(scripts/ops/durability.mjs). Read-only; never touches the order path or the
safety layer.

The ledger is written by scripts/ops/down-alert.mjs: an append-only JSONL of
completed outages (down_alert_events.jsonl) plus a live state file
(down_alert_state.json). This endpoint mirrors durability.mjs's computation in
Python. Fail-safe: with no ledger it returns an honest empty state, never a
fabricated streak.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ops-durability"])

_DAY_MS = 86_400_000.0


class Outage(BaseModel):
    downSince: str
    recoveredAt: str
    durationMs: float
    alerted: bool = False


class DurabilityResponse(BaseModel):
    """Clean-run durability derived from the down-alert outage ledger."""

    monitoring_since: str | None
    currently_down: bool
    down_since: str | None
    outage_count: int
    current_streak_days: float | None
    longest_streak_days: float | None
    total_downtime_ms: float
    mtbf_ms: float | None
    last_outage: Outage | None
    has_data: bool


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def _events_path() -> Path:
    override = os.getenv("DOWN_ALERT_EVENTS")
    return Path(override) if override else _data_dir() / "down_alert_events.jsonl"


def _state_path() -> Path:
    override = os.getenv("DOWN_ALERT_STATE")
    return Path(override) if override else _data_dir() / "down_alert_state.json"


def _parse_ms(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000.0
    except (ValueError, AttributeError):
        return None


def _read_outages() -> list[dict]:
    try:
        raw = _events_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("downSince") and rec.get("recoveredAt"):
            out.append(rec)
    out.sort(key=lambda o: _parse_ms(o.get("recoveredAt")) or 0.0)
    return out


def _read_state() -> dict | None:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compute_durability() -> DurabilityResponse:
    """Derive durability metrics from the outage ledger + live state (pure/read-only)."""
    outages = _read_outages()
    state = _read_state() or {}
    now = datetime.now(timezone.utc).timestamp() * 1000.0

    monitoring_since = state.get("monitoringSince") or (
        outages[0]["downSince"] if outages else None
    )
    currently_down = bool(state.get("downSince"))
    down_since = state.get("downSince") if currently_down else None

    last_recovered = outages[-1]["recoveredAt"] if outages else None
    streak_start = _parse_ms(last_recovered) or _parse_ms(monitoring_since)
    streak_end = _parse_ms(down_since) if currently_down else now
    current_streak_ms = (
        max(0.0, streak_end - streak_start) if streak_start is not None else None
    )

    longest_ms = 0.0
    mon_ms = _parse_ms(monitoring_since)
    if mon_ms is not None and outages:
        prev = mon_ms
        for o in outages:
            ds = _parse_ms(o.get("downSince"))
            rec = _parse_ms(o.get("recoveredAt"))
            if ds is not None:
                longest_ms = max(longest_ms, ds - prev)
            if rec is not None:
                prev = rec
    if current_streak_ms is not None:
        longest_ms = max(longest_ms, current_streak_ms)

    total_downtime = sum(float(o.get("durationMs") or 0.0) for o in outages)
    observed = (now - mon_ms) if mon_ms is not None else 0.0
    mtbf = (observed / len(outages)) if outages else None

    return DurabilityResponse(
        monitoring_since=monitoring_since,
        currently_down=currently_down,
        down_since=down_since,
        outage_count=len(outages),
        current_streak_days=(current_streak_ms / _DAY_MS) if current_streak_ms is not None else None,
        longest_streak_days=(longest_ms / _DAY_MS) if longest_ms else None,
        total_downtime_ms=total_downtime,
        mtbf_ms=mtbf,
        last_outage=Outage(**outages[-1]) if outages else None,
        has_data=monitoring_since is not None,
    )


@router.get("/ops/durability", response_model=DurabilityResponse)
async def get_durability() -> DurabilityResponse:
    """Return clean-run durability from the down-alert outage ledger."""
    try:
        return compute_durability()
    except Exception as exc:  # noqa: BLE001 - endpoint boundary, never 500 on read
        logger.warning("durability computation failed: %s", exc)
        raise HTTPException(status_code=500, detail="durability computation failed") from exc
