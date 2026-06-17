"""eod_router.py — End-of-Day summary data router.

Writes and reads daily EOD summary JSON files from engine/data/eod/YYYY-MM-DD.json.

Endpoints
---------
GET  /eod/history?days=90   — last N EOD records sorted by date descending
POST /eod/record            — write today's EOD summary (called by scheduler)
GET  /eod/latest            — most recent EOD record
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.routers.eod")

# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

_EOD_DIR = Path(__file__).parent.parent / "data" / "eod"
_EOD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EODRecord(BaseModel):
    date: str                       # YYYY-MM-DD
    daily_pnl: float
    trades: int
    win_rate: float                 # 0.0–1.0
    profit_factor: float
    max_drawdown_pct: float
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    regime: Optional[str] = None
    instruments: List[str] = []
    notes: Optional[str] = None
    recorded_at: str                # ISO timestamp


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/eod", tags=["eod"])


# ── Helper functions ────────────────────────────────────────────────────────


def _eod_file(date_str: str) -> Path:
    """Return the Path for a given YYYY-MM-DD EOD file."""
    return _EOD_DIR / f"{date_str}.json"


def _read_eod_file(path: Path) -> dict:
    """Read and parse a single EOD JSON file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Malformed EOD file %s: %s", path, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Malformed EOD file {path.name}: {exc}",
        ) from exc
    except OSError as exc:
        logger.error("Cannot read EOD file %s: %s", path, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Cannot read EOD file {path.name}: {exc}",
        ) from exc


def _sorted_eod_files(limit: int | None = None) -> List[Path]:
    """Return EOD JSON files sorted by filename (date) descending."""
    files = sorted(
        _EOD_DIR.glob("????-??-??.json"),
        key=lambda p: p.stem,
        reverse=True,
    )
    if limit is not None:
        files = files[:limit]
    return files


# ── GET /eod/history ────────────────────────────────────────────────────────


@router.get(
    "/history",
    response_model=List[EODRecord],
    summary="Get EOD history",
)
def get_eod_history(
    days: int = 90,
) -> List[EODRecord]:
    """
    Return the last ``days`` EOD records sorted by date descending.

    - **days**: Number of most-recent daily records to return (default 90).
    """
    if days < 1 or days > 3650:
        raise HTTPException(
            status_code=422,
            detail="days must be between 1 and 3650",
        )

    files = _sorted_eod_files(limit=days)

    if not files:
        return []

    records: List[EODRecord] = []
    for path in files:
        try:
            data = _read_eod_file(path)
            records.append(EODRecord(**data))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping EOD file %s due to error: %s", path, exc)
            continue

    return records


# ── GET /eod/latest ─────────────────────────────────────────────────────────


@router.get(
    "/latest",
    response_model=EODRecord,
    summary="Get most recent EOD record",
)
def get_eod_latest() -> EODRecord:
    """
    Return the single most recent EOD record.

    Raises 404 if no EOD records exist yet.
    """
    files = _sorted_eod_files(limit=1)
    if not files:
        raise HTTPException(
            status_code=404,
            detail="No EOD records found. Run POST /eod/record to create one.",
        )
    data = _read_eod_file(files[0])
    try:
        return EODRecord(**data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse latest EOD record: {exc}",
        ) from exc


# ── POST /eod/record ────────────────────────────────────────────────────────


@router.post(
    "/record",
    response_model=EODRecord,
    status_code=201,
    summary="Write today's EOD summary",
)
def record_eod(payload: EODRecord) -> EODRecord:
    """
    Write (or overwrite) today's EOD summary to disk as a JSON file.

    Called by the scheduler at market close. The ``date`` field in the
    payload determines the filename (``engine/data/eod/YYYY-MM-DD.json``).
    The ``recorded_at`` field is overwritten with the current UTC timestamp
    to ensure accuracy.

    - **date**: YYYY-MM-DD string for the session date.
    - **daily_pnl**: Net P&L for the day.
    - **trades**: Number of trades taken.
    - **win_rate**: Win rate as a decimal (0.0–1.0).
    - **profit_factor**: Gross profits / gross losses ratio.
    - **max_drawdown_pct**: Maximum intraday drawdown as a percentage.
    """
    # Validate date format
    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{payload.date}'. Expected YYYY-MM-DD.",
        ) from exc

    # Stamp recorded_at with current UTC time
    now_iso = datetime.now(timezone.utc).isoformat()
    record = payload.model_copy(update={"recorded_at": now_iso})

    dest = _eod_file(record.date)

    try:
        dest.write_text(
            json.dumps(record.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("EOD record written to %s", dest)
    except OSError as exc:
        logger.error("Failed to write EOD record to %s: %s", dest, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write EOD file: {exc}",
        ) from exc

    return record
