"""
Instruments router — WFE status and monitoring.

Exposes GET /instruments/wfe-status and POST /instruments/wfe-status/{symbol}
for tracking walk-forward efficiency (WFE) scores and recalculation schedules.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/instruments", tags=["instruments"])

WFE_CACHE_PATH = Path(__file__).parent.parent / "data" / "wfe_cache.json"

# Approved instruments with their last known WFEs (seed data from walk-forward results)
DEFAULT_WFE_DATA = {
    "MCL": {
        "wfe": 0.82,
        "interval": "1h",
        "status": "APPROVED",
        "last_calculated": "2026-03-30",
    },
    "MNQ": {
        "wfe": 0.57,
        "interval": "1h",
        "status": "APPROVED",
        "last_calculated": "2026-03-30",
    },
    "MGC": {
        "wfe": 0.14,
        "interval": "1d",
        "status": "HALTED",
        "last_calculated": "2026-03-30",
    },
    "MES": {
        "wfe": 0.09,
        "interval": "1h",
        "status": "DO_NOT_TRADE",
        "last_calculated": "2026-03-30",
    },
}

WFE_RECALC_INTERVAL_DAYS = 28  # 4-week rolling recalculation cycle
WFE_ALERT_THRESHOLD = 0.40


class WFEUpdateRequest(BaseModel):
    wfe: float
    interval: str


def _load_wfe_data() -> dict:
    """Load WFE cache from disk, falling back to DEFAULT_WFE_DATA if missing or corrupt."""
    try:
        if WFE_CACHE_PATH.exists():
            with WFE_CACHE_PATH.open("r") as f:
                loaded = json.load(f)
            # Merge with defaults so any new instruments appear
            merged = dict(DEFAULT_WFE_DATA)
            merged.update(loaded)
            return merged
    except Exception as exc:
        logger.warning("Could not load WFE cache from %s: %s — using defaults", WFE_CACHE_PATH, exc)
    return dict(DEFAULT_WFE_DATA)


def _save_wfe_data(data: dict) -> None:
    """Persist WFE data to disk."""
    WFE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WFE_CACHE_PATH.open("w") as f:
        json.dump(data, f, indent=2)


def _build_instrument_status(symbol: str, record: dict, today: date) -> dict:
    """Compute derived fields for a single instrument record."""
    last_calc_str = record.get("last_calculated", "2026-03-30")
    last_calc = date.fromisoformat(last_calc_str)
    next_due = last_calc + timedelta(days=WFE_RECALC_INTERVAL_DAYS)
    days_since = (today - last_calc).days
    days_until_due = (next_due - today).days
    wfe = float(record.get("wfe", 0.0))

    alert = False
    alert_reasons = []
    if wfe < WFE_ALERT_THRESHOLD:
        alert = True
        alert_reasons.append(f"WFE {wfe:.2f} is below minimum threshold {WFE_ALERT_THRESHOLD}")
    if days_until_due <= 0:
        alert = True
        alert_reasons.append(
            f"Recalculation overdue by {abs(days_until_due)} day(s) "
            f"(due {next_due.isoformat()})"
        )

    return {
        "symbol": symbol,
        "wfe": wfe,
        "interval": record.get("interval", "1h"),
        "status": record.get("status", "UNKNOWN"),
        "last_calculated": last_calc_str,
        "days_since_last_calc": days_since,
        "next_due_date": next_due.isoformat(),
        "days_until_due": days_until_due,
        "alert": alert,
        "alert_reason": "; ".join(alert_reasons) if alert_reasons else None,
    }


@router.get(
    "/wfe-status",
    summary="WFE status for all tracked instruments",
    description=(
        "Returns walk-forward efficiency scores, recalculation schedule, and alert flags "
        "for every tracked instrument. Alerts fire when WFE < 0.40 or recalculation is overdue."
    ),
)
async def get_wfe_status():
    """Return WFE status and schedule for all instruments."""
    try:
        wfe_data = _load_wfe_data()
        today = date.today()

        instruments = [
            _build_instrument_status(symbol, record, today) for symbol, record in wfe_data.items()
        ]

        total_approved = sum(1 for i in instruments if i["status"] == "APPROVED")
        total_halted = sum(1 for i in instruments if i["status"] in ("HALTED", "DO_NOT_TRADE"))
        total_alerts = sum(1 for i in instruments if i["alert"])

        # Next recalculation: earliest due date among approved instruments
        approved = [i for i in instruments if i["status"] == "APPROVED"]
        next_recalc = min(i["next_due_date"] for i in approved) if approved else None

        return {
            "instruments": instruments,
            "summary": {
                "total_instruments": len(instruments),
                "total_approved": total_approved,
                "total_halted": total_halted,
                "total_alerts": total_alerts,
                "next_recalculation_due": next_recalc,
                "recalc_interval_days": WFE_RECALC_INTERVAL_DAYS,
                "alert_threshold": WFE_ALERT_THRESHOLD,
            },
        }
    except Exception as exc:
        logger.exception("Failed to retrieve WFE status: %s", exc)
        raise HTTPException(status_code=500, detail=f"WFE status retrieval failed: {exc}") from exc


@router.post(
    "/wfe-status/{symbol}",
    summary="Update WFE score after a walk-forward run",
    description=(
        "Record a new walk-forward efficiency score for the given symbol. "
        "Persists to wfe_cache.json and returns the updated instrument status."
    ),
)
async def update_wfe_status(symbol: str, body: WFEUpdateRequest):
    """Update WFE score for a single instrument after a walk-forward recalculation."""
    try:
        symbol = symbol.upper()
        wfe_data = _load_wfe_data()

        existing = wfe_data.get(symbol, {})
        today_str = date.today().isoformat()

        # Determine new trading status based on WFE thresholds
        if body.wfe >= 0.50:
            new_status = "APPROVED"
        elif body.wfe >= 0.40:
            new_status = existing.get("status", "APPROVED")  # keep current if marginal
        elif body.wfe >= 0.20:
            new_status = "HALTED"
        else:
            new_status = "DO_NOT_TRADE"

        wfe_data[symbol] = {
            "wfe": round(body.wfe, 4),
            "interval": body.interval,
            "status": new_status,
            "last_calculated": today_str,
        }

        _save_wfe_data(wfe_data)
        logger.info("WFE updated for %s: wfe=%.4f status=%s", symbol, body.wfe, new_status)

        updated = _build_instrument_status(symbol, wfe_data[symbol], date.today())
        return {
            "success": True,
            "symbol": symbol,
            "instrument": updated,
        }
    except Exception as exc:
        logger.exception("Failed to update WFE for %s: %s", symbol, exc)
        raise HTTPException(
            status_code=500, detail=f"WFE update failed for {symbol}: {exc}"
        ) from exc
