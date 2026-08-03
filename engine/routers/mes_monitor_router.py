"""
mes_monitor_router.py

MES 24x7 monitor endpoints — status, alerts, history.
Read-only. Does not place orders or modify safety configs.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from middleware.auth import verify_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mes-monitor", tags=["mes-monitor"])


class MonitorStatusResponse(BaseModel):
    symbol: str
    state: str
    last_price: Optional[float] = None
    last_signal: Optional[str] = None
    last_confidence: Optional[float] = None
    last_update_utc: Optional[str] = None


class AlertResponse(BaseModel):
    timestamp: str
    symbol: str
    direction: Optional[str]
    confidence: float
    price: float
    reason: str
    regime: str


def _default_briefs_dir() -> Path:
    return Path(os.environ.get("MES_BRIEFS_DIR", "docs/morning_briefs"))


def _default_suggestions_csv() -> Path:
    return Path(os.environ.get("MES_SUGGESTIONS_CSV", "data/mes_monitor_suggestions.csv"))


@router.get(
    "/status",
    summary="MES monitor status",
    response_model=MonitorStatusResponse,
)
async def get_mes_status(_api_key: str = Depends(verify_api_key)):
    """
    Return current monitor status.
    In initial implementation, this is a conservative placeholder.
    """
    return MonitorStatusResponse(
        symbol="MES",
        state="active",
        last_price=None,
        last_signal=None,
        last_confidence=None,
        last_update_utc=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/alerts",
    summary="Recent MES monitor alerts",
    response_model=List[AlertResponse],
)
async def get_mes_alerts(
    limit: Optional[int] = Query(20, ge=1, le=200),
    _api_key: str = Depends(verify_api_key),
):
    briefs_dir = _default_briefs_dir()
    alerts: List[AlertResponse] = []
    if briefs_dir.exists():
        files = sorted(briefs_dir.glob("mes_alert_*.json"), reverse=True)[:limit]
        for path in files:
            try:
                data = path.read_text(encoding="utf-8")
                import json
                payload = json.loads(data)
                alerts.append(
                    AlertResponse(
                        timestamp=payload.get("timestamp", ""),
                        symbol=payload.get("symbol", "MES"),
                        direction=payload.get("direction"),
                        confidence=float(payload.get("confidence", 0.0)),
                        price=float(payload.get("price", 0.0)),
                        reason=payload.get("reason", ""),
                        regime=payload.get("regime", ""),
                    )
                )
            except Exception as exc:
                logger.warning("Failed to read alert file %s: %s", path, exc)
    return alerts


@router.get(
    "/history",
    summary="MES monitor suggestion history",
    response_model=List[AlertResponse],
)
async def get_mes_history(
    limit: Optional[int] = Query(50, ge=1, le=500),
    _api_key: str = Depends(verify_api_key),
):
    csv_path = _default_suggestions_csv()
    history: List[AlertResponse] = []
    if csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)[-limit:]
                for row in rows:
                    history.append(
                        AlertResponse(
                            timestamp=row.get("timestamp", ""),
                            symbol=row.get("symbol", "MES"),
                            direction=row.get("direction"),
                            confidence=float(row.get("confidence", 0.0)),
                            price=float(row.get("price", 0.0)),
                            reason=row.get("reason", ""),
                            regime=row.get("regime_reason", ""),
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to read suggestion history: %s", exc)
    return history
